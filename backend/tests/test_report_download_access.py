"""R1-05 код-ревью: скачивание отчёта журнала аудита — только администратору.

Формирование отчёта (`POST /api/v1/reports/audit-log`) требует роль администратора, а скачивание готового файла
(`GET /api/v1/reports/download/{filename}`) проверяло только аутентификацию: имя файла, попавшее в журнал прокси, историю браузера или
чат, открывало роли viewer логины, адреса и неудачные входы из журнала. Теперь имена с префиксом аудит-отчётов проверяются той же
зависимостью (`require_admin_if_auth_enabled`), что и формирование. Префикс — одна константа `AUDIT_REPORT_PREFIX` на генератор имени
и на проверку; сравнение без учёта регистра и формы Unicode, потому что в Windows (EXE) и macOS файл находится по имени без учёта регистра:
иначе `журнал_аудита_…` обходил бы проверку по точному префиксу.

Запуск: pytest backend/tests/test_report_download_access.py -v
"""
from __future__ import annotations

import unicodedata

import pytest
from test_resources_access import _enable_auth_with_viewer, _headers

from app.services.audit_export import AUDIT_REPORT_PREFIX, is_audit_report_name

AUDIT_URL = "/api/v1/reports/audit-log"
INVENTORY_URL = "/api/v1/reports/inventory"
DOWNLOAD = "/api/v1/reports/download/{}"


def _generate(client, url: str, headers: dict | None = None) -> str:
    response = client.post(url, headers=headers or {})
    assert response.status_code == 200, response.text
    return response.json()["file_name"]


@pytest.fixture()
def reports(client):
    """Аутентификация включена; готовы отчёт аудита и обычный отчёт. Возвращает (токен admin, токен viewer, имя аудит-отчёта, имя обычного)."""
    admin, viewer = _enable_auth_with_viewer(client)
    return admin, viewer, _generate(client, AUDIT_URL, _headers(admin)), _generate(client, INVENTORY_URL, _headers(admin))


def test_viewer_cannot_download_the_audit_report(client, reports):
    _, viewer, audit_name, _ = reports
    response = client.get(DOWNLOAD.format(audit_name), headers=_headers(viewer))
    assert response.status_code == 403
    assert "администратор" in response.json()["detail"]


def test_viewer_still_downloads_ordinary_reports(client, reports):
    _, viewer, _, inventory_name = reports
    response = client.get(DOWNLOAD.format(inventory_name), headers=_headers(viewer))
    assert response.status_code == 200 and response.content


def test_admin_downloads_both(client, reports):
    admin, _, audit_name, inventory_name = reports
    for name in (audit_name, inventory_name):
        response = client.get(DOWNLOAD.format(name), headers=_headers(admin))
        assert response.status_code == 200 and response.content, name


@pytest.mark.parametrize(
    "tamper",
    [
        lambda name: name.lower(),  # Windows и macOS найдут тот же файл при другом регистре
        lambda name: name.upper(),
        lambda name: unicodedata.normalize("NFD", name),  # «й» в разложенной форме
    ],
    ids=["lower", "upper", "nfd"],
)
def test_viewer_cannot_bypass_the_check_by_changing_the_name_form(client, reports, tamper):
    _, viewer, audit_name, _ = reports
    response = client.get(DOWNLOAD.format(tamper(audit_name)), headers=_headers(viewer))
    assert response.status_code == 403, "проверка должна сработать до поиска файла и не зависеть от регистра файловой системы"


def test_download_requires_authentication_when_it_is_enabled(client, reports):
    _, _, audit_name, inventory_name = reports
    for name in (audit_name, inventory_name):
        assert client.get(DOWNLOAD.format(name)).status_code == 401


def test_single_user_mode_keeps_downloads_open(client):
    """Аутентификация выключена (режим по умолчанию): ничего не требуется — как и для формирования отчёта."""
    audit_name = _generate(client, AUDIT_URL)
    assert client.get(DOWNLOAD.format(audit_name)).status_code == 200


def test_missing_ordinary_report_is_still_404_for_viewer(client, reports):
    _, viewer, _, _ = reports
    assert client.get(DOWNLOAD.format("нет_такого.xlsx"), headers=_headers(viewer)).status_code == 404


# --- Константа префикса: одна на генератор и проверку --------------------------------------------------------------------------
def test_generator_and_check_share_one_prefix(client, reports):
    _, _, audit_name, inventory_name = reports
    assert audit_name.startswith(AUDIT_REPORT_PREFIX) and is_audit_report_name(audit_name)
    assert not inventory_name.startswith(AUDIT_REPORT_PREFIX) and not is_audit_report_name(inventory_name)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        (f"{AUDIT_REPORT_PREFIX}2026-11-08_10-00-00_ab12cd34.xlsx", True),
        (f"{AUDIT_REPORT_PREFIX}".upper() + "x.xlsx", True),
        (unicodedata.normalize("NFD", AUDIT_REPORT_PREFIX) + "x.xlsx", True),
        ("Отчёт_2026-11-08_10-00-00_ab12cd34.xlsx", False),
        ("x_" + AUDIT_REPORT_PREFIX + "y.xlsx", False),  # префикс, а не вхождение
        ("", False),
    ],
)
def test_is_audit_report_name(name, expected):
    assert is_audit_report_name(name) is expected
