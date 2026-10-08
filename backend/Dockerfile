FROM node:22-slim AS frontend-vue-build
WORKDIR /frontend-vue
# Сначала только манифесты — слой с npm ci кешируется, пока package-lock.json не меняется.
COPY frontend-vue/package.json frontend-vue/package-lock.json ./
RUN npm ci
COPY frontend-vue/ ./
RUN npm run build

FROM python:3.12-slim
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
RUN groupadd --system app && useradd --system --gid app --home-dir /app app \
    && chown -R app:app /app
USER app
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=5 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=3).status==200 else 1)"
CMD ["sh","-c","alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
