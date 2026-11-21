#!/bin/sh
# Точка входа Docker-образа: резервная копия SQLite → миграции → сервер.
#
# Раньше CMD сразу выполнял `alembic upgrade head`: часть миграций необратима (удаляет данные), и обновление образа
# оставляло прежнюю базу без страховки. Теперь перед миграцией делается согласованная копия SQLite-базы
# (app/services/db_backup.py, тот же код, что в EXE). `set -e`: если копию сделать не удалось, миграция не запускается.
# PostgreSQL копируется средствами СУБД (docker compose --profile backup run --rm db-backup, README, «Обновление»):
# для него команда ниже только сообщает об этом.
#
# Запускается как `sh /app/docker-entrypoint.sh`, без бита исполнения: он теряется при распаковке на Windows.
set -eu
python -m app.services.db_backup
alembic upgrade head
# exec: uvicorn заменяет оболочку и становится PID 1, поэтому SIGTERM от `docker stop` доходит до приложения и оно завершается
# корректно, а не через 10 с по SIGKILL (без exec процесс был потомком sh, который сигнал не пересылает).
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
