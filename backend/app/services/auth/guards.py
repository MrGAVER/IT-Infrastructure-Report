"""Проверки доступа внутри эндпоинтов (зависимости FastAPI): первичная настройка и права администратора.

Работают вторым слоем поверх шлюза (auth/gate.py): не проверяют токен заново, а читают request.state, выставленный шлюзом."""
from __future__ import annotations

import hmac
from typing import Optional

from fastapi import HTTPException, Request

from ...config import SETUP_TOKEN
from ...constants import ErrorCode, UserRole
from ...models import User

# Заголовки, которые добавляет обратный прокси: если они есть, TCP-адрес клиента — это адрес прокси,
# а не пользователя, и «пришёл с localhost» ничего не доказывает.
_PROXY_HEADERS = ("x-forwarded-for", "forwarded", "x-real-ip")
_LOCALHOST_ADDRESSES = frozenset({"127.0.0.1", "::1", "::ffff:127.0.0.1"})


def _auth_enabled(request: Request) -> bool:
    """Включена ли аутентификация, по флагу, который выставил шлюз (gate.py). Нет флага — считаем, что включена (A-01).

    Для проверки прав безопасное значение по умолчанию — «включено»: отсутствие флага означает, что шлюз запрос не обслужил (новый маршрут
    вне /api/*, изменённая очерёдность middleware, прямой вызов зависимости), а не что аутентификацию выключили. Тогда без пользователя в
    request.state проверки ниже отказывают (403), а не пропускают запрос."""
    return bool(getattr(request.state, "auth_enabled", True))


def _is_direct_localhost(request: Request) -> bool:
    client = request.client
    if client is None or client.host not in _LOCALHOST_ADDRESSES:
        return False
    return not any(header in request.headers for header in _PROXY_HEADERS)


def require_setup_access(request: Request) -> None:
    """Первичная настройка аутентификации (пока она выключена): создание пользователей и сам
    переключатель. Без этой проверки любой, кто достаёт до порта, мог создать администратора, включить
    аутентификацию и тем самым закрыть реестр от его владельца.

    Пускаем либо по токену установки (INFRA_REGISTRY_SETUP_TOKEN, заголовок X-Setup-Token) — если он
    задан, то он нужен всем, включая localhost, — либо, если токена нет, только прямое соединение с
    localhost без прокси-заголовков. Остальной реестр при выключенной аутентификации по-прежнему открыт.
    """
    if SETUP_TOKEN:
        supplied = request.headers.get("x-setup-token", "")
        if hmac.compare_digest(supplied.encode("utf-8"), SETUP_TOKEN.encode("utf-8")):
            return
    elif _is_direct_localhost(request):
        return
    raise HTTPException(403, {
        "message": "Первичная настройка аутентификации доступна только с localhost или по токену установки "
                   "(заголовок X-Setup-Token, переменная INFRA_REGISTRY_SETUP_TOKEN).",
        "code": ErrorCode.SETUP_ACCESS_DENIED,
    })


def require_admin_if_auth_enabled(request: Request) -> None:
    """Журнал аудита (имена пользователей, IP-адреса, неудачные попытки входа) — только администратору (A-23).

    В отличие от `require_admin`, при выключенной аутентификации ничего не требует: однопользовательский режим по умолчанию
    открыт, как и весь остальной API (иначе журнал пропал бы у владельца локальной установки)."""
    if not _auth_enabled(request):
        return
    user: Optional[User] = getattr(request.state, "user", None)
    if user is None or user.role != UserRole.ADMIN:
        raise HTTPException(403, "Журнал аудита доступен только администратору.")


def require_admin(request: Request) -> None:
    """Явная проверка внутри конкретных эндпоинтов управления пользователями/настройками —
    вторым слоем поверх middleware (которое пропускает viewer'а на безопасные GET-методы; здесь
    же список пользователей и переключатель должны быть недоступны viewer'у ни на чтение, ни на
    запись). Не проверяет заново токен — переиспользует request.state, выставленный middleware.

    Пока аутентификация выключена, администраторов ещё нет — доступ определяет require_setup_access."""
    if not _auth_enabled(request):
        require_setup_access(request)
        return
    user: Optional[User] = getattr(request.state, "user", None)
    if user is None or user.role != UserRole.ADMIN:
        raise HTTPException(403, "Требуются права администратора.")
