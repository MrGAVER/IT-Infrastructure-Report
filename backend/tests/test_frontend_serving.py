"""
Тесты раздачи фронтенда: Vue (frontend-vue/dist) — единственный UI на '/' (см. README.md и
frontend-vue/README.md; vanilla-фронтенд и '/legacy' удалены в 2.59.0, см. запись в changelog).

Каталог фронтенда подменяется на временный через monkeypatch модульных констант
(app.api.frontend_assets.FRONTEND_DIR, app.main.FRONTEND_DIR), а не читается из реально собранного
frontend-vue/dist — иначе тест зависел бы от того, был ли уже выполнен `npm run build` в
frontend-vue, а в CI pytest сейчас запускается раньше этого шага (см. .github/workflows/ci.yml).
StaticFiles-маунт '/assets' не тестируется отдельно — он создаётся один раз при импорте
app.main и просто оборачивает Starlette StaticFiles (библиотечный код), тестируется только
наша собственная логика маршрутизации.
"""

from __future__ import annotations

from pathlib import Path

from app import main as app_main
from app.api import frontend_assets as assets_module


def _write_index(directory: Path, marker: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "index.html").write_text(f"<html><body>{marker}</body></html>", encoding="utf-8")


def test_root_serves_vue_frontend_as_primary(client, tmp_path, monkeypatch):
    vue_dir = tmp_path / "vue-dist"
    _write_index(vue_dir, "VUE-PRIMARY")
    monkeypatch.setattr(app_main, "FRONTEND_DIR", vue_dir)  # `/` обслуживает main.spa_fallback — отдельного маршрута в api больше нет

    r = client.get("/")

    assert r.status_code == 200
    assert "VUE-PRIMARY" in r.text


def test_root_without_built_dist_gives_actionable_error_not_a_crash(client, tmp_path, monkeypatch):
    monkeypatch.setattr(app_main, "FRONTEND_DIR", tmp_path / "not-built-yet")

    r = client.get("/")

    assert r.status_code == 500
    assert "npm run build" in r.text


def test_legacy_path_no_longer_exists(client, tmp_path, monkeypatch):
    """Vanilla-фронтенд и путь '/legacy' удалены в 2.59.0 (см. changelog) — теперь по этому пути
    срабатывает тот же SPA-фоллбэк, что и для любого другого неизвестного пути (app.main:
    spa_fallback), а не выделенный роут: отдаёт index.html Vue-приложения (200), внутри которого
    сам vue-router покажет клиентский 'страница не найдена', а не HTTP 500/404 на уровне сервера."""
    vue_dir = tmp_path / "vue-dist"
    _write_index(vue_dir, "VUE-PRIMARY")
    monkeypatch.setattr(app_main, "FRONTEND_DIR", vue_dir)

    r = client.get("/legacy")

    assert r.status_code == 200
    assert "VUE-PRIMARY" in r.text


def test_client_side_route_falls_back_to_vue_index_html(client, tmp_path, monkeypatch):
    """vue-router работает в режиме createWebHistory() (см. frontend-vue/src/router/index.ts) —
    прямой переход или обновление страницы на /vms должны вернуть index.html, а не 404,
    чтобы роутер сам открыл нужный экран на клиенте (как try_files в типичном nginx-конфиге
    для SPA). Fallback-роут объявлен в app.main, не в api/frontend_assets.py — см. комментарий там."""
    vue_dir = tmp_path / "vue-dist"
    _write_index(vue_dir, "VUE-PRIMARY")
    monkeypatch.setattr(app_main, "FRONTEND_DIR", vue_dir)

    r = client.get("/vms")

    assert r.status_code == 200
    assert "VUE-PRIMARY" in r.text


def test_unknown_api_path_returns_404_json_not_html_fallback(client):
    """SPA-фоллбэк не должен маскировать сломанные /api/* запросы под 200 с HTML — иначе
    опечатка в пути или обращение к несуществующему эндпоинту молча выглядело бы как успех."""
    r = client.get("/api/v1/this-route-does-not-exist")

    assert r.status_code == 404
    assert "text/html" not in r.headers.get("content-type", "")


def test_icons_svg_served_from_frontend_dir(client, tmp_path, monkeypatch):
    vue_dir = tmp_path / "vue-dist"
    vue_dir.mkdir(parents=True, exist_ok=True)
    (vue_dir / "icons.svg").write_text("<svg></svg>", encoding="utf-8")
    monkeypatch.setattr(assets_module, "FRONTEND_DIR", vue_dir)

    r = client.get("/icons.svg")

    assert r.status_code == 200
    assert "<svg" in r.text


def test_icons_svg_missing_returns_404(client, tmp_path, monkeypatch):
    monkeypatch.setattr(assets_module, "FRONTEND_DIR", tmp_path / "empty")

    r = client.get("/icons.svg")

    assert r.status_code == 404


def test_favicon_served_from_frontend_dir(client, tmp_path, monkeypatch):
    vue_dir = tmp_path / "vue-dist"
    vue_dir.mkdir(parents=True, exist_ok=True)
    payload = b"\x00\x00\x01\x00\x01\x00" + b"\x00" * 16  # заголовок ICO: подлинность формата проверяет тест сборки фронтенда
    (vue_dir / "favicon.ico").write_bytes(payload)
    monkeypatch.setattr(assets_module, "FRONTEND_DIR", vue_dir)

    r = client.get("/favicon.ico")

    assert r.status_code == 200
    assert r.content == payload
    assert r.headers["content-type"] == "image/x-icon"
    assert r.headers["cache-control"] == assets_module.FAVICON_CACHE_CONTROL


def test_favicon_missing_returns_404_not_spa_fallback(client, tmp_path, monkeypatch):
    # Без файла ответ — 404, а не index.html от SPA-фоллбэка: иначе браузер получил бы HTML вместо иконки.
    vue_dir = tmp_path / "vue-dist"
    _write_index(vue_dir, "SPA-INDEX")
    monkeypatch.setattr(assets_module, "FRONTEND_DIR", vue_dir)
    monkeypatch.setattr(app_main, "FRONTEND_DIR", vue_dir)

    r = client.get("/favicon.ico")

    assert r.status_code == 404
    assert "SPA-INDEX" not in r.text


def test_favicon_is_public_when_authentication_is_enabled(client, tmp_path, monkeypatch):
    # /favicon.ico лежит вне /api/, поэтому аутентификация его не закрывает (иконка нужна уже на экране входа).
    vue_dir = tmp_path / "vue-dist"
    vue_dir.mkdir(parents=True, exist_ok=True)
    (vue_dir / "favicon.ico").write_bytes(b"\x00\x00\x01\x00")
    monkeypatch.setattr(assets_module, "FRONTEND_DIR", vue_dir)
    r = client.post("/api/v1/auth/users", json={"username": "admin", "password": "Admin1234", "role": "admin"})
    assert r.status_code == 201, r.text
    r = client.put("/api/v1/auth/settings", json={"enabled": True})
    assert r.status_code == 200, r.text
    assert client.get("/api/v1/devices").status_code == 401  # аутентификация действительно включена

    r = client.get("/favicon.ico")  # без токена

    assert r.status_code == 200
