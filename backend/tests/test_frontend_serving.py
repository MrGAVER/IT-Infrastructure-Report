"""
Тесты раздачи фронтенда: Vue (frontend-vue/dist) — основной UI на '/', vanilla (frontend/) —
на '/legacy' на переходный период (см. README.md и frontend-vue/README.md).

Каталоги фронтендов подменяются на временные через monkeypatch модульных констант
(app.api.system.FRONTEND_DIR/LEGACY_FRONTEND_DIR, app.main.FRONTEND_DIR), а не читаются из
реально собранного frontend-vue/dist — иначе тест зависел бы от того, был ли уже выполнен
`npm run build` в frontend-vue, а в CI pytest сейчас запускается раньше этого шага
(см. .github/workflows/ci.yml). StaticFiles-маунты '/assets' и '/static' не тестируются
отдельно — они создаются один раз при импорте app.main и просто оборачивают Starlette
StaticFiles (библиотечный код), тестируется только наша собственная логика маршрутизации.
"""
from __future__ import annotations

from pathlib import Path

from app import main as app_main
from app.api import system as system_module


def _write_index(directory: Path, marker: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'index.html').write_text(f'<html><body>{marker}</body></html>', encoding='utf-8')


def test_root_serves_vue_frontend_as_primary(client, tmp_path, monkeypatch):
    vue_dir = tmp_path / 'vue-dist'
    _write_index(vue_dir, 'VUE-PRIMARY')
    monkeypatch.setattr(system_module, 'FRONTEND_DIR', vue_dir)

    r = client.get('/')

    assert r.status_code == 200
    assert 'VUE-PRIMARY' in r.text


def test_root_without_built_dist_gives_actionable_error_not_a_crash(client, tmp_path, monkeypatch):
    monkeypatch.setattr(system_module, 'FRONTEND_DIR', tmp_path / 'not-built-yet')

    r = client.get('/')

    assert r.status_code == 500
    assert 'npm run build' in r.text


def test_legacy_path_still_serves_vanilla_frontend(client, tmp_path, monkeypatch):
    legacy_dir = tmp_path / 'legacy'
    _write_index(legacy_dir, 'VANILLA-LEGACY')
    monkeypatch.setattr(system_module, 'LEGACY_FRONTEND_DIR', legacy_dir)

    r = client.get('/legacy')

    assert r.status_code == 200
    assert 'VANILLA-LEGACY' in r.text


def test_client_side_route_falls_back_to_vue_index_html(client, tmp_path, monkeypatch):
    """vue-router работает в режиме createWebHistory() (см. frontend-vue/src/router/index.ts) —
    прямой переход или обновление страницы на /vms должны вернуть index.html, а не 404,
    чтобы роутер сам открыл нужный экран на клиенте (как try_files в типичном nginx-конфиге
    для SPA). Fallback-роут объявлен в app.main, не в api/system.py — см. комментарий там."""
    vue_dir = tmp_path / 'vue-dist'
    _write_index(vue_dir, 'VUE-PRIMARY')
    monkeypatch.setattr(app_main, 'FRONTEND_DIR', vue_dir)

    r = client.get('/vms')

    assert r.status_code == 200
    assert 'VUE-PRIMARY' in r.text


def test_unknown_api_path_returns_404_json_not_html_fallback(client):
    """SPA-фоллбэк не должен маскировать сломанные /api/* запросы под 200 с HTML — иначе
    опечатка в пути или обращение к несуществующему эндпоинту молча выглядело бы как успех."""
    r = client.get('/api/v1/this-route-does-not-exist')

    assert r.status_code == 404
    assert 'text/html' not in r.headers.get('content-type', '')


def test_icons_svg_served_from_frontend_dir(client, tmp_path, monkeypatch):
    vue_dir = tmp_path / 'vue-dist'
    vue_dir.mkdir(parents=True, exist_ok=True)
    (vue_dir / 'icons.svg').write_text('<svg></svg>', encoding='utf-8')
    monkeypatch.setattr(system_module, 'FRONTEND_DIR', vue_dir)

    r = client.get('/icons.svg')

    assert r.status_code == 200
    assert '<svg' in r.text


def test_icons_svg_missing_returns_404(client, tmp_path, monkeypatch):
    monkeypatch.setattr(system_module, 'FRONTEND_DIR', tmp_path / 'empty')

    r = client.get('/icons.svg')

    assert r.status_code == 404
