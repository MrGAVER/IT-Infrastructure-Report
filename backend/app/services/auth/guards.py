"""Проверки доступа внутри эндпоинтов (зависимости FastAPI): первичная настройка и права администратора.

Работают вторым слоем поверх шлюза (auth/gate.py): не проверяют токен заново, а читают request.state, выставленный шлюзом."""

from __future__ import annotations

import hmac
import logging
from typing import Optional

from fastapi import HTTPException, Request

from ...config import MIN_SETUP_TOKEN_LENGTH, SETUP_TOKEN, weak_setup_token
from ...constants import ErrorCode, UserRole
from ...models import User
from ..login_throttle import LoginThrottle
from ._common import request_client_ip, too_many_attempts

logger = logging.getLogger(__name__)

# Заголовки, которые добавляет обратный прокси: если они есть, TCP-адрес клиента — это адрес прокси,
# а не пользователя, и «пришёл с localhost» ничего не доказывает.
_PROXY_HEADERS = ("x-forwarded-for", "forwarded", "x-real-ip")
_LOCALHOST_ADDRESSES = frozenset({"127.0.0.1", "::1", "::ffff:127.0.0.1"})

# Троттлинг подбора токена установки: после SETUP_TOKEN_FREE_ATTEMPTS неверных значений с одного адреса каждая следующая
# попытка ждёт вдвое дольше (до SETUP_TOKEN_MAX_DELAY). Отдельный экземпляр LoginThrottle, а не ключ в троттлинге входа: у каждого
# своя ограниченная таблица, и поток неверных токенов не вытесняет записи подбора паролей (и наоборот). Состояние — в памяти процесса,
# как у входа (services/login_throttle.py). Бесплатных попыток мало: токен вводят один раз при настройке, а честная опечатка — это
# одна-две попытки.
SETUP_TOKEN_FREE_ATTEMPTS = 5
SETUP_TOKEN_BASE_DELAY = 2.0
SETUP_TOKEN_MAX_DELAY = 300.0
setup_token_throttle = LoginThrottle(free_attempts=SETUP_TOKEN_FREE_ATTEMPTS, base_delay=SETUP_TOKEN_BASE_DELAY, max_delay=SETUP_TOKEN_MAX_DELAY)


def _auth_enabled(request: Request) -> bool:
    """Включена ли аутентификация, по флагу, который выставил шлюз (gate.py). Нет флага — считаем, что включена.

    Для проверки прав безопасное значение по умолчанию — «включено»: отсутствие флага означает, что шлюз запрос не обслужил (новый маршрут
    вне /api/*, изменённая очерёдность middleware, прямой вызов зависимости), а не что аутентификацию выключили. Тогда без пользователя в
    request.state проверки ниже отказывают (403), а не пропускают запрос."""
    return bool(getattr(request.state, "auth_enabled", True))


def _is_direct_localhost(request: Request) -> bool:
    client = request.client
    if client is None or client.host not in _LOCALHOST_ADDRESSES:
        return False
    return not any(header in request.headers for header in _PROXY_HEADERS)


def _effective_setup_token() -> str:
    """Токен, который сервер действительно принимает. Слабый (заглушка из .env.example или короче MIN_SETUP_TOKEN_LENGTH) — это
    публично известное значение, а не секрет, поэтому он приравнен к незаданному: пустая строка."""
    return "" if weak_setup_token(SETUP_TOKEN) else SETUP_TOKEN


def _setup_denied_message() -> str:
    message = (
        "Первичная настройка аутентификации доступна только с localhost или по токену установки (заголовок "
        "X-Setup-Token, переменная INFRA_REGISTRY_SETUP_TOKEN)."
    )
    if weak_setup_token(SETUP_TOKEN):
        # Само значение не называем — только причину: администратор по сообщению поймёт, почему верный на вид токен не принят.
        message += (
            " Токен установки на сервере слишком слабый (совпадает с заглушкой из .env.example или короче "
            f"{MIN_SETUP_TOKEN_LENGTH} символов) и не принимается: замените его на длинную случайную строку, например "
            "openssl rand -hex 24, и перезапустите сервер."
        )
    return message


def _setup_token_accepted(request: Request, token: str) -> bool:
    """Сверяет X-Setup-Token с токеном установки под троттлингом подбора; 429, если с этого адреса слишком много неверных значений.

    Попыткой подбора считается только подставленное значение: запрос без заголовка (или с пустым) — не попытка, а обычный отказ.
    Интерфейс сначала обращается без токена, получает 403 SETUP_ACCESS_DENIED и лишь потом просит его ввести; блокировка таких
    запросов заперла бы самого владельца. Пока задержка не истекла, отказ 429 получает и верное значение: иначе по ответу можно было бы
    отличить его от неверного, не дожидаясь конца задержки. Успех сбрасывает счётчик адреса."""
    supplied = request.headers.get("x-setup-token", "")
    if not supplied:
        return False
    client_ip = request_client_ip(request) or "unknown"
    wait = setup_token_throttle.retry_after(client_ip)
    if wait > 0:
        raise too_many_attempts("Слишком много неверных значений токена установки. Повторите через {seconds} с.", wait)
    if hmac.compare_digest(supplied.encode("utf-8"), token.encode("utf-8")):
        setup_token_throttle.reset(client_ip)
        return True
    delay = setup_token_throttle.record_failure(client_ip)
    if delay > 0:
        logger.warning("Подбор токена установки (X-Setup-Token) с адреса %s: следующая попытка не раньше чем через %.0f с.", client_ip, delay)
    return False


def require_setup_access(request: Request) -> None:
    """Первичная настройка аутентификации (пока она выключена): создание пользователей и сам
    переключатель. Без этой проверки любой, кто достаёт до порта, мог создать администратора, включить
    аутентификацию и тем самым закрыть реестр от его владельца.

    Пускаем либо по токену установки (INFRA_REGISTRY_SETUP_TOKEN, заголовок X-Setup-Token) — если он
    задан, то он нужен всем, включая localhost, — либо, если токена нет, только прямое соединение с
    localhost без прокси-заголовков. Остальной реестр при выключенной аутентификации по-прежнему открыт.

    Слабый токен (заглушка из .env.example, короче MIN_SETUP_TOKEN_LENGTH) считается незаданным: его знает любой, кто видел
    .env.example, поэтому «принимать, но предупреждать» значило бы отдать первичную настройку первому, кто достанет до порта. Запуск
    при этом не блокируется, а в Docker, где прямого localhost нет, первичная настройка недоступна, пока токен не заменят."""
    token = _effective_setup_token()
    if token:
        if _setup_token_accepted(request, token):
            return
    elif _is_direct_localhost(request):
        return
    raise HTTPException(
        403,
        {
            "message": _setup_denied_message(),
            "code": ErrorCode.SETUP_ACCESS_DENIED,
        },
    )


def require_admin_if_auth_enabled(request: Request) -> None:
    """Журнал аудита (имена пользователей, IP-адреса, неудачные попытки входа) — только администратору.

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
