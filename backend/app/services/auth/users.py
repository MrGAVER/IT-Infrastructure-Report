"""Учётные записи: поиск, создание, изменение, удаление, смена собственного пароля, защита последнего администратора."""

from __future__ import annotations

from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...constants import AuditAction, ErrorCode, UserRole
from ...models import User
from ..crud import audit
from ..preferences import delete_user_preferences
from ..timeutil import iso_utc
from ._common import naive_utc_now
from .lockout import account_locked, register_failed_password
from .passwords import hash_password, validate_password_strength, verify_password
from .sessions import revoke_all_sessions, revoke_all_sessions_except


def find_user_by_username(session: Session, username: str) -> Optional[User]:
    """Регистронезависимый поиск на стороне Python, а не через SQL lower() — тот же принцип, что
    в миграциях/бэкфиллах справочников (SQLite lower() не умеет в кириллицу; см. память проекта).
    Таблица пользователей на практике маленькая (единицы-десятки учётных записей), полный перебор
    дешевле, чем заводить ради этого объёма регистронезависимый индекс."""
    normalized = username.strip().casefold()
    if not normalized:
        return None
    for user in session.scalars(select(User)).all():
        if user.username.casefold() == normalized:
            return user
    return None


def lock_active_admins(session: Session) -> list[User]:
    """SELECT ... FOR UPDATE по ВСЕМ активным администраторам (не исключая никого) — задел на
    многопроцессный деплой (см. README: серверный вариант — Docker + PostgreSQL, несколько
    процессов backend за одной БД). Без блокировки строк «проверить количество, затем изменить»
    — это классический TOCTOU: два администратора A и B, каждый на СВОЁМ процессе одновременно
    разжалуют/удаляют себя или друг друга — оба параллельно читают «остался ещё один админ» (видя
    ДРУГ ДРУГА как безопасную гарантию) и оба проходят проверку, итог — ноль администраторов.

    Лочить нужно ВЕСЬ набор активных админов, а не «остальных, кроме текущего» — иначе транзакция
    над A блокирует только строку B, транзакция над B блокирует только строку A: блокировки не
    пересекаются, гонка никуда не уходит. Блокируя одинаковый набор строк в обеих транзакциях,
    вторая обязана дождаться коммита первой и затем увидит уже актуальное (после первого
    изменения) состояние — что и требуется для корректной проверки.

    На SQLite FOR UPDATE — безопасный no-op (проверено эмпирически, диалект просто не рендерит
    предложение): гонка там и так невозможна — SQLite сериализует писателей на уровне файла БД
    целиком, а не по строкам. Полноценный эффект блокировки нужен и проявляется только на
    PostgreSQL при нескольких одновременно пишущих процессах/инстансах backend."""
    return list(session.scalars(select(User).where(User.role == UserRole.ADMIN, User.is_active.is_(True)).with_for_update()).all())


def ensure_not_last_admin(session: Session, user: User) -> None:
    """Запрещает удалить/деактивировать/понизить в правах единственную оставшуюся активную
    учётную запись администратора — иначе при включённой аутентификации администрировать её
    (в т.ч. снова выключить переключатель) стало бы физически некому, включая того, кто совершает
    это действие. Вызывающий должен находиться в той же транзакции, что и последующая мутация
    (см. lock_active_admins) — только тогда блокировка строк реально что-то гарантирует."""
    if user.role != UserRole.ADMIN or not user.is_active:
        return
    remaining_others = sum(1 for admin in lock_active_admins(session) if admin.id != user.id)
    if remaining_others == 0:
        raise HTTPException(
            400,
            {
                "message": "Нельзя удалить или лишить прав последнего активного администратора.",
                "code": ErrorCode.LAST_ADMIN_ACCOUNT,
            },
        )


def create_user(session: Session, *, username: str, password: str, role: str) -> User:
    username = username.strip()
    if not username:
        raise HTTPException(422, "Имя пользователя не может быть пустым")
    if role not in UserRole.ALL:
        raise HTTPException(422, f"Недопустимая роль: {role!r}")
    if find_user_by_username(session, username) is not None:
        raise HTTPException(409, {"message": f"Пользователь «{username}» уже существует.", "code": ErrorCode.DUPLICATE_USERNAME})
    validate_password_strength(password, username=username)
    user = User(username=username, password_hash=hash_password(password), role=role, is_active=True)
    session.add(user)
    session.flush()  # id генерируется при flush и нужен записи аудита; нарушение уникальности имени проявится уже здесь
    audit(session, "users", user.id, AuditAction.CREATE, f"Создана учётная запись «{username}» (роль: {role})")
    session.commit()  # учётная запись и запись аудита — одной транзакцией: не бывает пользователя без следа в журнале
    session.refresh(user)
    return user


def update_user(
    session: Session,
    user: User,
    *,
    username: Optional[str] = None,
    password: Optional[str] = None,
    role: Optional[str] = None,
    is_active: Optional[bool] = None,
) -> User:
    if role is not None and role not in UserRole.ALL:
        raise HTTPException(422, f"Недопустимая роль: {role!r}")
    demoting = (role is not None and role != UserRole.ADMIN and user.role == UserRole.ADMIN) or (is_active is False)
    if demoting:
        ensure_not_last_admin(session, user)

    changes: list[str] = []
    if username is not None:
        new_username = username.strip()
        if not new_username:
            raise HTTPException(422, "Имя пользователя не может быть пустым")
        existing = find_user_by_username(session, new_username)
        if existing is not None and existing.id != user.id:
            raise HTTPException(409, {"message": f"Пользователь «{new_username}» уже существует.", "code": ErrorCode.DUPLICATE_USERNAME})
        if new_username != user.username:
            changes.append(f"имя: «{user.username}» → «{new_username}»")
            user.username = new_username
    if role is not None and role != user.role:
        changes.append(f"роль: «{user.role}» → «{role}»")
        user.role = role
    if is_active is not None and is_active != user.is_active:
        changes.append("активирована" if is_active else "деактивирована")
        user.is_active = is_active
    security_sensitive = is_active is False
    if password is not None:
        validate_password_strength(password, username=user.username)
        user.password_hash = hash_password(password)
        user.failed_attempts = 0
        user.locked_until = None
        changes.append("сменён пароль")
        security_sensitive = True

    # Изменение, запись аудита и отзыв сессий — ОДНА транзакция. Раньше это были три commit(): процесс, упавший между
    # первым и последним, оставлял новый пароль (или деактивацию) при ещё действующих старых токенах и без записи в журнале.
    if changes:
        audit(session, "users", user.id, AuditAction.UPDATE, "; ".join(changes))
    if security_sensitive:
        # Смена пароля или деактивация должны немедленно аннулировать уже выданные токены —
        # иначе украденный/оставленный открытым токен продолжал бы работать до истечения TTL.
        revoke_all_sessions(session, user.id, commit=False)
    session.commit()
    session.refresh(user)
    return user


def delete_user(session: Session, user: User) -> None:
    ensure_not_last_admin(session, user)
    username = user.username
    delete_user_preferences(session, user.id)  # у AppPreference.owner внешнего ключа нет — каскада не будет
    session.delete(user)  # ON DELETE CASCADE (AuthSession.user_id) снимает и его сессии
    audit(session, "users", user.id, AuditAction.DELETE, f"Удалена учётная запись «{username}»")
    session.commit()


def change_own_password(
    session: Session,
    user: User,
    *,
    current_password: str,
    new_password: str,
    keep_token: Optional[str] = None,
) -> User:
    """Самостоятельная смена ПОЛЬЗОВАТЕЛЕМ СВОЕГО пароля — доступна любой роли, включая viewer
    (см. ROLE_CHECK_EXEMPT_PATHS), в отличие от update_user (смена ЧУЖОГО пароля — только admin).
    Требует текущий пароль: иначе кратковременно угнанная сессия (расшаренный компьютер,
    забытая открытой вкладка) позволяла бы захватить учётку насовсем, просто задав новый пароль.
    keep_token — токен запроса, которым вызвана сама эта смена: его сессия не отзывается, иначе
    пользователь тут же вылетел бы из только что открытой вкладки настроек; отзываются все
    ОСТАЛЬНЫЕ его сессии — тот же принцип, что и при смене пароля администратором в update_user."""
    now = naive_utc_now()
    if user.locked_until and user.locked_until > now:
        # Как при входе: пока учётная запись заблокирована, пароль не проверяется. Без этого владелец (или тот, кто получил
        # его токен) продолжал бы подбирать пароль через этот эндпоинт и после блокировки.
        raise account_locked(user.locked_until, now)
    if not verify_password(current_password, user.password_hash):
        # Ошибка в поле формы, а не «сессия недействительна»: 401 в этом API означает отсутствующий или недействительный токен
        # (клиент по нему завершает сессию), поэтому здесь 422 с собственным кодом. Попытка засчитывается так же, как неверный
        # пароль при входе: тот, у кого оказался чужой токен, не должен подбирать пароль без ограничений и без следа в журнале.
        register_failed_password(session, user, details=f"Неверный текущий пароль при смене пароля «{user.username}»", now=now)
        raise HTTPException(422, {"message": "Текущий пароль указан неверно.", "code": ErrorCode.WRONG_CURRENT_PASSWORD})
    validate_password_strength(new_password, username=user.username)
    user.password_hash = hash_password(new_password)
    user.failed_attempts = 0
    user.locked_until = None
    # Новый хеш, запись аудита и отзыв остальных сессий — одна транзакция (см. update_user): иначе сбой между commit()
    # оставил бы старые токены действующими при уже сменённом пароле.
    audit(session, "users", user.id, AuditAction.UPDATE, f"«{user.username}» сменил(а) собственный пароль")
    revoke_all_sessions_except(session, user.id, keep_token, commit=False)
    session.commit()
    session.refresh(user)
    return user


def serialize_user(user: User) -> dict:
    """Публичное представление пользователя — намеренно без password_hash/failed_attempts."""
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "is_active": user.is_active,
        "last_login_at": iso_utc(user.last_login_at),
        "locked": bool(user.locked_until and user.locked_until > naive_utc_now()),
        "created_at": iso_utc(user.created_at),
    }
