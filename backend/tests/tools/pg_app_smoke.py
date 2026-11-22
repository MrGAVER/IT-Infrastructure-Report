"""Живой смоук приложения на PostgreSQL: тот же путь, что у контейнера (`alembic upgrade head && uvicorn`), затем
запросы по HTTP к настоящему серверу. Не pytest: запускается из CI и вручную.

Использование (из каталога backend, база должна быть пустой и принадлежать смоуку). Либо готовый адрес:
    DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/infra_smoke python tests/tools/pg_app_smoke.py
либо части — так сервер настраивает docker-compose.yml (пароль любых символов, экранирование делает приложение):
    INFRA_REGISTRY_DB_HOST=localhost POSTGRES_USER=u POSTGRES_PASSWORD='p@ss' POSTGRES_DB=infra_smoke python tests/tools/pg_app_smoke.py
Выход 0 — всё прошло; иначе в stderr причина и хвост лога сервера.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

PORT = int(os.environ.get("SMOKE_PORT", "8765"))
BASE = f"http://127.0.0.1:{PORT}/api/v1"


def call(method: str, path: str, body=None, expect=(200, 201)):
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(BASE + path, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            status, payload = response.status, response.read()
    except urllib.error.HTTPError as error:
        status, payload = error.code, error.read()
    if status not in expect:
        raise AssertionError(f"{method} {path} → {status}: {payload[:400]!r}")
    return json.loads(payload) if payload[:1] in (b"{", b"[") else payload


def main() -> int:
    sys.path.insert(0, os.getcwd())  # скрипт запускают из каталога backend; пакет app лежит там
    from app.config import DATABASE_URL  # тот же разбор переменных окружения, что у сервера (DATABASE_URL или INFRA_REGISTRY_DB_HOST + POSTGRES_*)

    if not DATABASE_URL.startswith("postgresql"):
        print("Нужен PostgreSQL: задайте DATABASE_URL или INFRA_REGISTRY_DB_HOST (+ POSTGRES_USER/PASSWORD/DB)", file=sys.stderr)
        return 2
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True)
    log = tempfile.NamedTemporaryFile("w+", suffix=".log", delete=False)
    server = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(PORT)], stdout=log, stderr=subprocess.STDOUT)
    try:
        for _ in range(60):
            try:
                health = call("GET", "/health")
                break
            except Exception:
                if server.poll() is not None:
                    raise RuntimeError("сервер завершился при старте")
                time.sleep(1)
        else:
            raise RuntimeError("сервер не ответил за 60 с")
        assert health["status"] == "ok", health

        category = call("GET", "/resources/device-categories?limit=1")["items"][0]["id"]
        device_type = call("POST", "/resources/device-types", {"name": "Коммутатор (смоук)", "category_id": category})["id"]
        vlans = [call("POST", "/resources/vlans", {"vlan_id": n, "name": f"VLAN {n}"})["id"] for n in (10, 20)]
        for vlan in vlans:
            call("POST", "/resources/device-type-vlans", {"device_type_id": device_type, "vlan_id": vlan})
        devices = [call("POST", "/resources/devices", {"device_type_id": device_type, "serial_number": f"SMOKE-{i}", "system_name": f"SW-{i}"})["id"] for i in (1, 2)]
        for index, device in enumerate(devices, 1):
            call(
                "PUT",
                f"/devices/{device}/interfaces",
                {"interfaces": [{"name": f"Gi0/{index}", "vlan_mode": "trunk", "vlan_ids": vlans, "ips": [{"ip_address": f"10.0.{index}.1", "prefix_length": 24}]}]},
                expect=(200,),
            )
        ports = {i["physical_device_id"]: i["id"] for i in call("GET", "/resources/interfaces?limit=100")["items"]}
        link_type = call("POST", "/resources/connection-types", {"name": "Витая пара (смоук)"})["id"]
        call("POST", "/resources/connections", {"source_interface_id": ports[devices[0]], "destination_interface_id": ports[devices[1]], "connection_type_id": link_type})

        report = call("POST", "/reports/inventory", {})
        assert report.get("file_name"), f"отчёт не создан: {report}"
        content = call("GET", "/reports/download/" + urllib.parse.quote(report["file_name"]), expect=(200,))  # имя файла содержит кириллицу
        assert content[:2] == b"PK", "выгрузка Excel не похожа на xlsx"
        from io import BytesIO

        import openpyxl

        sheet = openpyxl.load_workbook(BytesIO(content))["Организация подключений"]
        ports = [row[5] for row in sheet.iter_rows(min_row=1, values_only=True) if row and row[5] in ("Gi0/1", "Gi0/2")]
        assert sorted(ports) == ["Gi0/1", "Gi0/2"], f"в листе подключений нет созданных портов: {ports}"
        audit = call("GET", "/audit-log?limit=5")
        assert audit, "журнал аудита пуст"
        print("OK: миграции, запуск, создание данных, Excel-отчёт и журнал аудита на PostgreSQL")
        return 0
    except Exception as error:  # noqa: BLE001 — смоук: любая ошибка = провал
        log.flush()
        log.seek(0)
        print(f"ПРОВАЛ: {error}\n--- хвост лога сервера ---\n{log.read()[-3000:]}", file=sys.stderr)
        return 1
    finally:
        server.terminate()
        try:
            server.wait(10)
        except subprocess.TimeoutExpired:
            server.kill()


if __name__ == "__main__":
    sys.exit(main())
