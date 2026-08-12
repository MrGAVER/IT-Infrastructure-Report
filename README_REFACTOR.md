# Infra Registry 2.12 — оптимизация и рефакторинг

## Что изменено

### Backend
- `main.py` превращен в минимальный application factory.
- CRUD вынесен в `app/services/crud.py`.
- Валидации вынесены в `app/services/validation.py`.
- Сериализация и вычисляемые поля устройств вынесены в `app/services/serialization.py`.
- Инициализация справочников вынесена в `app/services/catalogs.py`.
- API разделен на routers:
  - `app/api/system.py`
  - `app/api/resources.py`
  - `app/api/devices.py`
- Конфигурация и подключение БД вынесены в `config.py` и `db.py`.
- Убран wildcard import моделей.
- Убран `__import__('sqlalchemy')` из CRUD-кода.
- Для списка физических устройств устранен N+1 запрос: интерфейсы и IP загружаются пакетно.
- Добавлены индексы для наиболее частых FK/поисковых запросов.

### Frontend
- CSS и JavaScript вынесены из `index.html` в `frontend/static/app.css` и `frontend/static/app.js`.
- `index.html` оставлен только как шаблон оболочки приложения.
- Static-ресурсы обслуживаются FastAPI через `/static`.

### База данных
Добавлена миграция:

`3a7c1e5d9b20_performance_indexes.py`

Она добавляет индексы для:
- зданий → помещений → стоек;
- производителя/типа → моделей;
- физических устройств;
- интерфейсов и IP;
- подключений;
- ОС и VM.

База приложения в source/EXE-режиме хранится в корне приложения:

`infra_registry.db`

Для EXE — рядом с `InfraRegistry.exe`.

## Проверка

Проверены:
- Alembic `upgrade head` на чистой SQLite БД;
- обновление существующей БД;
- `/`, `/docs`, `/api/v1/health`;
- CRUD;
- Dashboard;
- список ресурсов и схемы;
- `/static/app.js` и `/static/app.css`;
- синтаксис Python и JavaScript.

## Версия

`2.12.0`
