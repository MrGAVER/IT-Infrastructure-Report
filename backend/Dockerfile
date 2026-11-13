# Базовые образы закреплены по digest (A-10 код-ревью r3): тег переписывается издателем, и образ, собранный завтра, мог бы отличаться от
# проверенного сегодня. Digest — у индекса образа (мультиархитектурного манифеста), поэтому сборка работает и на arm64. Тег оставлен для
# читателя и для Dependabot (.github/dependabot.yml, docker): он предлагает обновление тега и digest одним PR. Вручную:
# `docker buildx imagetools inspect python:3.12-slim` → строка Digest (не digest отдельной платформы). Значения взяты из
# docker-library/repo-info (образы от 04–05.11.2026); сборку образа проверяет шаг CI «Проверка сборки Docker-образа backend».
FROM node:25-slim@sha256:81db02c4b671288a03915da9534dbd54f96d0e7c24d80ccc54f5b36b2e684370 AS frontend-vue-build
WORKDIR /frontend-vue
# Сначала только манифесты — слой с npm ci кешируется, пока package-lock.json не меняется.
COPY frontend-vue/package.json frontend-vue/package-lock.json ./
RUN npm ci
COPY frontend-vue/ ./
RUN npm run build

FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b
WORKDIR /app
# Версии берутся из requirements.lock (с хешами), а не из диапазонов requirements.txt: образ, собранный завтра, получает те
# же пакеты, что и сегодня. Обновление lock — см. README, раздел «Зависимости backend».
COPY backend/requirements.lock .
RUN pip install --no-cache-dir --require-hashes -r requirements.lock
COPY backend/app ./app
COPY backend/alembic.ini .
COPY backend/alembic ./alembic
# Единственный UI (см. backend/app/config.py:FRONTEND_DIR) — собран на предыдущем стейдже, а не
# скопирован с хоста: так образ воспроизводим из исходников одной командой `docker build`,
# без обязательного локального `npm run build` перед сборкой образа.
COPY --from=frontend-vue-build /frontend-vue/dist ./frontend-vue/dist
# BASE_DIR в config.py вычисляется как parents[2] от config.py, что верно для дерева исходников
# (backend/app/config.py -> repo root), но НЕ для этого образа: здесь config.py лежит на один
# уровень мельче (/app/app/config.py -> parents[2] == '/', а не '/app'). Без явных переменных
# ниже APP_DATA_DIR/FRONTEND_DIR молча резолвились бы в '/', 'reports'.mkdir() в /reports упал
# бы PermissionError под непривилегированным пользователем app, и контейнер не стартовал бы —
# 'docker build' в CI это не ловит, т.к. проверяет только сборку образа, без 'docker run'. Тот
# же приём (явные переменные вместо авто-детекта BASE_DIR) уже используется для frozen
# EXE-сборки, см. launcher.py.
ENV PYTHONPATH=/app
ENV INFRA_REGISTRY_DATA_DIR=/app/data
ENV INFRA_REGISTRY_FRONTEND_DIR=/app/frontend-vue/dist
# Код (/app/app, /app/alembic, frontend-vue/dist) остаётся у root и доступен процессу приложения только для чтения: при
# уязвимости, позволяющей писать файлы, подмена кода не пережила бы перезапуск. Записывать нужно только в /app/data
# (отчёты, при SQLite — база) — он принадлежит app и подключается томом (см. docker-compose.yml: appdata). Домашний
# каталог пользователя — тоже /app/data, чтобы любые кеши библиотек (~/.cache) писались в доступное место.
RUN groupadd --system app && useradd --system --gid app --home-dir /app/data app \
    && mkdir -p /app/data && chown app:app /app/data \
    && chmod -R a+rX /app
USER app
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=5 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=3).status==200 else 1)"
# exec: uvicorn заменяет оболочку и становится PID 1, поэтому SIGTERM от `docker stop` доходит до приложения и оно завершается
# корректно, а не через 10 с по SIGKILL (без exec процесс был потомком sh, который сигнал не пересылает).
CMD ["sh","-c","alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
