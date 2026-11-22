"""
Регрессия: BASE_DIR в app/config.py вычисляется как Path(__file__).resolve().parents[2] и
корректен для дерева исходников (backend/app/config.py -> repo root), но НЕ для layout'а
внутри Docker-образа (backend/Dockerfile): там config.py лежит на один уровень мельче
(/app/app/config.py, т.к. 'backend/' не сохраняется при COPY backend/app ./app) —
parents[2] резолвится в '/', а не в '/app'.

Без явных переменных окружения ниже APP_DATA_DIR молча стал бы '/', и
REPORT_DIR.mkdir(parents=True, exist_ok=True) упал бы PermissionError под непривилегированным
пользователем контейнера (USER app) уже на 'alembic upgrade head' — alembic/env.py импортирует
app.config на самом старте, до uvicorn. Контейнер не поднялся бы вовсе, а 'docker build' в CI
(.github/workflows/ci.yml) это не ловит: проверяется только сборка образа, без 'docker run'.

Без доступного docker daemon в этом окружении полноценный интеграционный тест (собрать образ,
запустить контейнер, дождаться healthcheck) невозможен — вместо этого: (1) явно демонстрируем
арифметику самого бага и (2) страхуем регрессию, проверяя, что backend/Dockerfile по-прежнему
задаёт эти переменные явно, тем же приёмом, что уже используется для frozen EXE-сборки в
launcher.py (там BASE_DIR вообще не используется — оба пути передаются через переменные
окружения ещё до импорта app.config).
"""

from __future__ import annotations

from pathlib import Path

DOCKERFILE = Path(__file__).resolve().parents[2] / "backend" / "Dockerfile"


def test_base_dir_arithmetic_differs_between_source_tree_and_docker_layout():
    source_tree_config = Path("/repo/backend/app/config.py")
    docker_image_config = Path("/app/app/config.py")

    assert source_tree_config.parents[2] == Path("/repo")
    assert docker_image_config.parents[2] == Path("/")  # сам баг: должно быть '/app'


def test_dockerfile_overrides_data_and_frontend_dirs_explicitly():
    text = DOCKERFILE.read_text(encoding="utf-8")
    for var in ("INFRA_REGISTRY_DATA_DIR", "INFRA_REGISTRY_FRONTEND_DIR"):
        assert f"ENV {var}=" in text, (
            f'{var} должен быть задан явно в backend/Dockerfile — без него значение по умолчанию из config.py (через BASE_DIR) резолвится в "/" внутри контейнера, см. docstring этого файла.'
        )
