"""Файл настроек EXE-версии (``infra_registry.toml`` рядом с ``InfraRegistry.exe``).

Файл создаётся при первом запуске со значениями по умолчанию и подробными комментариями; дальше его правит
администратор. Формат — TOML (стандартный ``tomllib``, Python 3.11+): списки адресов и комментарии в нём
читаются без самодельного разбора.

Модуль намеренно не импортирует ``app.config``: тот разбирает переменные окружения один раз, при импорте,
а лаунчер должен сначала прочитать настройки и только потом выставить окружение (``launcher.apply_environment``).
"""

from __future__ import annotations

import ipaddress
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .network_access import parse_client_networks

SETTINGS_FILENAME = "infra_registry.toml"
DEFAULT_PORT = 8000
LOCAL_ONLY_HOST = "127.0.0.1"
ALL_INTERFACES_HOST = "0.0.0.0"  # nosec B104 # значение для сравнения с настройкой «слушать на всех адресах», сокет здесь не открывается
# Петля всегда разрешена: администратор не должен потерять доступ с собственного компьютера из-за записи в файле.
LOOPBACK_NETWORK = "127.0.0.0/8"

_KNOWN_KEYS: dict[str, frozenset[str]] = {
    "server": frozenset({"port", "open_browser"}),
    "access": frozenset({"allowed_clients", "allowed_hosts"}),
}


class SettingsError(ValueError):
    """Файл настроек нельзя применить. Текст сообщения показывается пользователю в консоли как есть."""


@dataclass(frozen=True)
class ExeSettings:
    port: int = DEFAULT_PORT
    open_browser: bool = True
    # Подсети в канонической записи («192.168.1.15/32», «192.168.1.0/24»); петля сюда не входит.
    allowed_clients: tuple[str, ...] = ()
    # Дополнительные имена в заголовке Host (по IP-адресу сервера открывается и без них).
    allowed_hosts: tuple[str, ...] = ()

    @property
    def network_access(self) -> bool:
        """Разрешены ли клиенты не с этого компьютера."""
        return bool(self.allowed_clients)

    @property
    def listen_host(self) -> str:
        """Адрес прослушивания: пока доступ только локальный, порт не виден из сети вообще (даже если
        брандмауэр его пропускает); адреса клиентов открывают порт на всех интерфейсах, а кого пускать,
        решает фильтр клиентов."""
        return ALL_INTERFACES_HOST if self.network_access else LOCAL_ONLY_HOST

    def environment(self) -> dict[str, str]:
        """Переменные окружения для ``app.config`` (читаются при его импорте)."""
        env = {"INFRA_REGISTRY_ALLOWED_CLIENTS": ",".join([LOOPBACK_NETWORK, *self.allowed_clients])}
        if self.allowed_hosts:
            env["INFRA_REGISTRY_ALLOWED_HOSTS"] = ",".join(["localhost", LOCAL_ONLY_HOST, *self.allowed_hosts])
        return env


DEFAULT_SETTINGS_TEXT = """\
# РИС — Реестр ИТ-инфраструктуры. Настройки EXE-версии.
#
# Файл создан автоматически при первом запуске. Измените значения и перезапустите приложение.
# Если файл удалить, при следующем запуске он будет создан заново со значениями по умолчанию.
# Сохраняйте файл в кодировке UTF-8. Строки, начинающиеся с «#», — комментарии.

[server]
# Порт веб-интерфейса. Параметр командной строки --port важнее этой настройки.
port = 8000

# Открывать браузер при запуске (true / false). Параметр командной строки --no-browser важнее этой настройки.
open_browser = true

[access]
# С каких компьютеров можно подключаться к приложению.
#
# По умолчанию (пустой список) работа возможна ТОЛЬКО с этого компьютера: приложение слушает порт только
# на адресе 127.0.0.1 и из сети недоступно.
#
# Чтобы открыть доступ с других компьютеров, перечислите их IP-адреса или подсети в списке ниже.
# Замените строку «allowed_clients = []» на свою (строка должна остаться одной, дублировать её нельзя).
# Каждый элемент — в кавычках, элементы разделяются запятыми. Этот компьютер разрешён всегда.
#
#   Один компьютер:
#       allowed_clients = ["192.168.1.15"]
#   Несколько конкретных компьютеров:
#       allowed_clients = ["192.168.1.15", "192.168.1.20", "10.0.5.7"]
#   Вся подсеть (запись вида адрес/длина маски, CIDR):
#       allowed_clients = ["192.168.1.0/24"]        # адреса 192.168.1.1 – 192.168.1.254
#   Подсеть и отдельные компьютеры вместе:
#       allowed_clients = ["192.168.1.0/24", "10.0.5.7"]
#
# Длина маски по маске подсети:
#   255.255.255.255 = /32 (один адрес)     255.255.255.0   = /24 (256 адресов)
#   255.255.255.128 = /25 (128 адресов)    255.255.0.0     = /16 (65 536 адресов)
#   255.255.255.192 = /26 (64 адреса)      255.0.0.0       = /8
# Свой адрес и маску можно узнать командой «ipconfig» в командной строке.
# Допускаются только адреса IPv4. Запись "0.0.0.0/0" открывает доступ ВСЕМ адресам — так делать не стоит.
#
# После изменения списка:
#   1. Перезапустите приложение.
#   2. Разрешите входящие подключения на порт приложения в брандмауэре Windows. Командная строка
#      администратора (порт 8000; при желании добавьте remoteip=192.168.1.0/24, чтобы правило
#      действовало только для вашей подсети):
#          netsh advfirewall firewall add rule name="RIS" dir=in action=allow protocol=TCP localport=8000
#   3. Откройте с другого компьютера в браузере адрес http://<IP-адрес этого компьютера>:8000
#      (например, http://192.168.1.10:8000).
#
# ВАЖНО: пока вход выключен, любой разрешённый компьютер видит и меняет весь реестр без пароля.
# Прежде чем открывать доступ, на этом компьютере зайдите в «Настройки → Аутентификация», создайте
# администратора и включите вход — включить его можно только с самого компьютера, где запущено приложение.
# Подключение идёт по HTTP без шифрования, поэтому используйте только доверенную сеть.
allowed_clients = []

# Имена, по которым можно открывать приложение с других компьютеров, если вместо IP-адреса используется имя
# (например, http://reestr-pc:8000). По IP-адресу приложение открывается и без этой настройки.
# Пример:
#     allowed_hosts = ["reestr-pc", "reestr-pc.corp.local"]
allowed_hosts = []
"""


def _section(data: dict, name: str) -> dict:
    section = data.get(name, {})
    if not isinstance(section, dict):
        raise SettingsError(f"Раздел [{name}] должен быть таблицей, а не значением.")
    unknown = sorted(set(section) - _KNOWN_KEYS[name])
    if unknown:
        raise SettingsError(
            f"Неизвестный параметр в разделе [{name}]: {', '.join(unknown)}. Допустимые параметры: {', '.join(sorted(_KNOWN_KEYS[name]))}."
        )
    return section


def _string_list(section: dict, key: str, where: str) -> list[str]:
    value = section.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise SettingsError(f'{where}: ожидается список строк в кавычках, например {key} = ["192.168.1.15"].')
    return [item.strip() for item in value if item.strip()]


def _parse_clients(entries: list[str]) -> tuple[str, ...]:
    try:
        networks = parse_client_networks(entries)
    except ValueError as exc:
        raise SettingsError(f"[access] allowed_clients: {exc}") from exc
    for network in networks:
        if network.version != 4:
            raise SettingsError(f"[access] allowed_clients: адрес {network} — не IPv4. В EXE-версии поддерживаются только адреса IPv4.")
    # Без дубликатов и без петли (она разрешена всегда), порядок как в файле.
    result: list[str] = []
    for network in networks:
        text = str(network)
        if not network.is_loopback and text not in result:
            result.append(text)
    return tuple(result)


def _parse_hosts(entries: list[str]) -> tuple[str, ...]:
    for entry in entries:
        if any(ch in entry for ch in ":/ \t"):
            raise SettingsError(
                f"[access] allowed_hosts: некорректное имя {entry!r} — нужно только имя без порта и адреса страницы "
                "(например, reestr-pc или *.corp.local)."
            )
        try:
            ipaddress.ip_address(entry)
        except ValueError:
            continue
        raise SettingsError(
            f"[access] allowed_hosts: {entry!r} — это IP-адрес. Здесь перечисляются имена; по IP-адресу приложение "
            "открывается без дополнительных настроек, а список клиентов задаётся в allowed_clients."
        )
    return tuple(dict.fromkeys(entries))


def parse_settings(text: str) -> ExeSettings:
    """Настройки из текста TOML. Ошибки — ``SettingsError`` с русским пояснением; неизвестные параметры тоже
    ошибка: опечатка в ``allowed_clients`` иначе молча оставила бы доступ закрытым, а в имени параметра
    безопасности — молча лишила бы настройку силы."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise SettingsError(f"Файл настроек повреждён или записан неверно: {exc}") from exc
    unknown_sections = sorted(set(data) - set(_KNOWN_KEYS))
    if unknown_sections:
        raise SettingsError(
            f"Неизвестный раздел в файле настроек: {', '.join(unknown_sections)}. Допустимые разделы: {', '.join(_KNOWN_KEYS)}."
        )
    server = _section(data, "server")
    access = _section(data, "access")

    port = server.get("port", DEFAULT_PORT)
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise SettingsError(f"[server] port: ожидается число от 1 до 65535, получено {port!r}.")
    open_browser = server.get("open_browser", True)
    if not isinstance(open_browser, bool):
        raise SettingsError("[server] open_browser: ожидается true или false (без кавычек).")

    return ExeSettings(
        port=port,
        open_browser=open_browser,
        allowed_clients=_parse_clients(_string_list(access, "allowed_clients", "[access] allowed_clients")),
        allowed_hosts=_parse_hosts(_string_list(access, "allowed_hosts", "[access] allowed_hosts")),
    )


def ensure_settings_file(path: Path) -> bool:
    """Создаёт файл настроек по умолчанию, если его нет. True — файл создан сейчас. Существующий файл
    никогда не перезаписывается. ``OSError`` (каталог только для чтения и т. п.) пробрасывается вызывающему."""
    try:
        with path.open("x", encoding="utf-8", newline="\r\n") as handle:  # CRLF — привычно для Блокнота Windows
            handle.write(DEFAULT_SETTINGS_TEXT)
    except FileExistsError:
        return False
    return True


def load_settings(path: Path) -> ExeSettings:
    """Читает настройки из файла (с поддержкой BOM, который добавляют некоторые редакторы Windows)."""
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise SettingsError("Файл настроек должен быть в кодировке UTF-8.") from exc
    return parse_settings(text)
