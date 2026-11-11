"""R1-05 и A-05 код-ревью: скачивание отчёта журнала аудита — только администратору, и устроено «по построению».

Формирование отчёта (`POST /api/v1/reports/audit-log`) требует роль администратора, а скачивание готового файла проверяло только
аутентификацию: имя файла, попавшее в журнал прокси, историю браузера или чат, открывало роли viewer логины, адреса и неудачные входы
из журнала. R1-05 закрыл это проверкой имени по префиксу `AUDIT_REPORT_PREFIX` (без учёта регистра и формы Unicode — в Windows и macOS файл
находится по имени без учёта регистра).

A-05: одной проверки по имени мало — любой новый код, пишущий или отдающий отчёты в общем каталоге, обязан был о ней помнить. Теперь отчёты
аудита лежат в подкаталоге `reports/audit/`, а скачиваются отдельным эндпоинтом `GET /api/v1/reports/audit-log/download/{filename}` с
зависимостью администратора на самом маршруте. Общий эндпоинт скачивания ищет файл только в корне каталога, поэтому до файла из `audit/`
не дотянется при любом написании имени; проверка по префиксу осталась вторым слоем (для файлов, оставшихся в корне от прежних версий).

Запуск: pytest backend/tests/test_report_download_access.py -v
"""
from __future__ import annotations

import unicodedata

import pytest
from test_resources_access import _enable_auth_with_viewer, _headers

from app.config import REPORT_DIR
from app.services.audit_export import AUDIT_REPORT_PREFIX, audit_report_dir, build_audit_log_report, is_audit_report_name

AUDIT_URL = "/api/v1/reports/audit-log"
INVENTORY_URL = "/api/v1/reports/inventory"
DOWNLOAD = "/api/v1/reports/download/{}"
AUDIT_DOWNLOAD = "/api/v1/reports/audit-log/download/{}"


def _generate(client, url: str, headers: dict | None = None) -> dict:
    response = client.post(url, headers=headers or {})
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture()
def reports(client):
    """Аутентификация включена; готовы отчёт аудита и обычный отчёт. Возвращает (токен admin, токен viewer, имя аудит-отчёта, имя обычного)."""
    admin, viewer = _enable_auth_with_viewer(client)
    return admin, viewer, _generate(client, AUDIT_URL, _headers(admin))["file_name"], _generate(client, INVENTORY_URL, _headers(admin))["file_name"]


# --- Где лежит отчёт аудита и какой адрес скачивания получает клиент ---------------------------------------------------------------
def test_the_audit_report_is_written_to_the_audit_subdirectory(db_session, tmp_path):
    path = build_audit_log_report(db_session, tmp_path)
    assert path.parent == audit_report_dir(tmp_path) == tmp_path / "audit"
    assert path.is_file() and path.name.startswith(AUDIT_REPORT_PREFIX)
    assert [p.name for p in tmp_path.iterdir()] == ["audit"], "в корне каталога отчётов аудита быть не должно"


def test_the_response_points_to_the_dedicated_audit_endpoint(client):
    body = _generate(client, AUDIT_URL)
    assert body["download_url"] == AUDIT_DOWNLOAD.format(body["file_name"])
    assert (REPORT_DIR / "audit" / body["file_name"]).is_file()
    assert not (REPORT_DIR / body["file_name"]).exists()


def test_ordinary_reports_keep_the_general_endpoint(client):
    body = _generate(client, INVENTORY_URL)
    assert body["download_url"] == DOWNLOAD.format(body["file_name"])
    assert (REPORT_DIR / body["file_name"]).is_file()


# --- Права на скачивание -------------------------------------------------------------------------------------------------------
def test_viewer_cannot_download_the_audit_report(client, reports):
    _, viewer, audit_name, _ = reports
    for url in (AUDIT_DOWNLOAD.format(audit_name), DOWNLOAD.format(audit_name)):
        response = client.get(url, headers=_headers(viewer))
        assert response.status_code == 403, url
        assert "администратор" in response.json()["detail"]


def test_viewer_still_downloads_ordinary_reports(client, reports):
    _, viewer, _, inventory_name = reports
    response = client.get(DOWNLOAD.format(inventory_name), headers=_headers(viewer))
    assert response.status_code == 200 and response.content


def test_admin_downloads_the_audit_report_from_the_audit_endpoint_and_the_ordinary_one_from_the_general(client, reports):
    admin, _, audit_name, inventory_name = reports
    for url in (AUDIT_DOWNLOAD.format(audit_name), DOWNLOAD.format(inventory_name)):
        response = client.get(url, headers=_headers(admin))
        assert response.status_code == 200 and response.content, url


def test_download_requires_authentication_when_it_is_enabled(client, reports):
    _, _, audit_name, inventory_name = reports
    for url in (AUDIT_DOWNLOAD.format(audit_name), DOWNLOAD.format(audit_name), DOWNLOAD.format(inventory_name)):
        assert client.get(url).status_code == 401, url


def test_single_user_mode_keeps_downloads_open(client):
    """Аутентификация выключена (режим по умолчанию): ничего не требуется — как и для формирования отчёта."""
    body = _generate(client, AUDIT_URL)
    assert client.get(body["download_url"]).status_code == 200


# --- Общий эндпоинт не отдаёт файлы из audit/ ни при каком написании имени -------------------------------------------------------------
_NAME_FORMS = {
    "exact": lambda name: name,
    "lower": lambda name: name.lower(),
    "upper": lambda name: name.upper(),
    "nfd": lambda name: unicodedata.normalize("NFD", name),  # «й» в разложенной форме
    "subdir-prefix": lambda name: f"audit/{name}",
    "subdir-encoded": lambda name: f"audit%2F{name}",
    "dot-dot": lambda name: f"..%2Freports%2Faudit%2F{name}",
}


@pytest.mark.parametrize("form", sorted(_NAME_FORMS))
def test_the_general_endpoint_gives_404_for_a_file_that_lives_in_the_audit_subdirectory(client, form):
    audit_name = _generate(client, AUDIT_URL)["file_name"]  # аутентификация выключена: проверка роли пройдена, значит, отказывает именно поиск файла
    assert client.get(DOWNLOAD.format(_NAME_FORMS[form](audit_name))).status_code == 404


@pytest.mark.parametrize("form", ["lower", "upper", "nfd"])
def test_viewer_cannot_bypass_the_name_check_by_changing_the_name_form(client, reports, form):
    _, viewer, audit_name, _ = reports
    response = client.get(DOWNLOAD.format(_NAME_FORMS[form](audit_name)), headers=_headers(viewer))
    assert response.status_code == 403, "проверка по имени — второй слой: она срабатывает до поиска файла и не зависит от регистра файловой системы"


def test_a_leftover_audit_report_in_the_root_stays_admin_only(client, reports):
    """Отчёты, сформированные прежними версиями, лежат в корне каталога: второй слой (проверка по имени) продолжает их защищать."""
    admin, viewer, _, _ = reports
    legacy = REPORT_DIR / f"{AUDIT_REPORT_PREFIX}2026-01-01_00-00-00_legacy01.xlsx"
    legacy.write_bytes(b"x")
    try:
        assert client.get(DOWNLOAD.format(legacy.name), headers=_headers(viewer)).status_code == 403
        assert client.get(DOWNLOAD.format(legacy.name), headers=_headers(admin)).status_code == 200
    finally:
        legacy.unlink()


# --- Эндпоинт аудита отдаёт только файлы из audit/ ------------------------------------------------------------------------------------
def test_the_audit_endpoint_does_not_serve_ordinary_reports(client, reports):
    admin, _, _, inventory_name = reports
    assert client.get(AUDIT_DOWNLOAD.format(inventory_name), headers=_headers(admin)).status_code == 404


@pytest.mark.parametrize("name", ["нет_такого.xlsx", "..%2F..%2Fetc%2Fpasswd", "..%2F{inventory}", "%2Fetc%2Fpasswd"])
def test_the_audit_endpoint_rejects_missing_files_and_traversal(client, reports, name):
    admin, _, _, inventory_name = reports
    assert client.get(AUDIT_DOWNLOAD.format(name.replace("{inventory}", inventory_name)), headers=_headers(admin)).status_code == 404


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
