"""Атомарность смены пароля, роли и деактивации (services/auth.py, ревью 2.158.0, П-4).

В create_user, update_user и change_own_password изменение, запись в журнал аудита и отзыв сессий шли тремя разными
commit(). Процесс, упавший между первым и последним, оставлял новый пароль при ещё действующих старых токенах и без записи
в журнале. Теперь это одна транзакция с одним commit() в конце.

Сбой «посреди операции» моделируется исключением на последнем шаге (отзыв сессий или запись аудита) с последующим
rollback(): то же самое делает БД при обрыве соединения, а не завершённая транзакция не оставляет следа. Сервисные функции
вызываются напрямую на db_session — так видно число commit() и состояние БД после отката.
"""
from __future__ import annotations

from contextlib import contextmanager

import pytest
from sqlalchemy import func, select

from app.constants import AuditAction
from app.models import AuditLog, AuthSession, User
from app.services import auth as auth_module
from app.services.auth import sessions as sessions_module
from app.services.auth import users as users_module

OLD_PASSWORD = "Alice1234"
NEW_PASSWORD = "Newpass5678"


def _boom(*_args, **_kwargs):
    raise RuntimeError("сбой посреди операции")


@contextmanager
def counting_commits(session):
    """Считает вызовы session.commit() внутри блока (сами коммиты выполняются как обычно)."""
    calls: list[int] = []
    original = session.commit

    def spy() -> None:
        calls.append(1)
        original()

    session.commit = spy
    try:
        yield calls
    finally:
        del session.commit


def _alice(db_session, role: str = "viewer") -> User:
    return auth_module.create_user(db_session, username="alice", password=OLD_PASSWORD, role=role)


def _sessions_of(db_session, user_id: str) -> int:
    return db_session.scalar(select(func.count()).select_from(AuthSession).where(AuthSession.user_id == user_id))


def _audit_rows(db_session, entity_id: str, action: str, text: str = "") -> int:
    stmt = select(func.count()).select_from(AuditLog).where(AuditLog.entity_type == "users", AuditLog.entity_id == entity_id, AuditLog.action == action)
    if text:
        stmt = stmt.where(AuditLog.details.contains(text))
    return db_session.scalar(stmt)


def _crash_and_reload(db_session) -> None:
    """Обрыв: незавершённая транзакция откатывается, дальше читаем то, что реально осталось в БД."""
    db_session.rollback()
    db_session.expire_all()


def _stored(db_session, user_id: str) -> User:
    return db_session.get(User, user_id)


class TestCreateUser:
    def test_user_and_audit_record_are_one_transaction(self, db_session):
        with counting_commits(db_session) as commits:
            user = _alice(db_session)
        assert len(commits) == 1
        assert user.id and user.password_hash
        assert _audit_rows(db_session, user.id, AuditAction.CREATE, "alice") == 1

    def test_failure_while_auditing_leaves_no_user_behind(self, db_session, monkeypatch):
        """Раньше пользователь коммитился до записи аудита: сбой между ними давал учётную запись без следа в журнале."""
        monkeypatch.setattr(users_module, "audit", _boom)
        with pytest.raises(RuntimeError):
            _alice(db_session)
        _crash_and_reload(db_session)
        assert auth_module.find_user_by_username(db_session, "alice") is None


class TestUpdateUser:
    def _with_sessions(self, db_session) -> tuple[User, list[str]]:
        user = _alice(db_session)
        tokens = [auth_module.create_session(db_session, user), auth_module.create_session(db_session, user)]
        assert _sessions_of(db_session, user.id) == 2
        return user, tokens

    def test_password_change_is_one_transaction_and_revokes_sessions(self, db_session):
        user, _tokens = self._with_sessions(db_session)
        bystander = auth_module.create_user(db_session, username="bob", password="Bobby12345", role="viewer")
        auth_module.create_session(db_session, bystander)
        with counting_commits(db_session) as commits:
            auth_module.update_user(db_session, user, password=NEW_PASSWORD)
        assert len(commits) == 1
        assert auth_module.verify_password(NEW_PASSWORD, _stored(db_session, user.id).password_hash)
        assert not auth_module.verify_password(OLD_PASSWORD, _stored(db_session, user.id).password_hash)
        assert _sessions_of(db_session, user.id) == 0
        assert _sessions_of(db_session, bystander.id) == 1  # чужие сессии не затронуты
        assert _audit_rows(db_session, user.id, AuditAction.UPDATE, "сменён пароль") == 1

    def test_failure_while_revoking_leaves_old_password_and_sessions(self, db_session, monkeypatch):
        """Тот самый разрыв из ревью: пароль уже сменён, а старые токены ещё действуют. Теперь откатывается всё вместе."""
        user, _tokens = self._with_sessions(db_session)
        monkeypatch.setattr(users_module, "revoke_all_sessions", _boom)
        with pytest.raises(RuntimeError):
            auth_module.update_user(db_session, user, password=NEW_PASSWORD)
        _crash_and_reload(db_session)
        assert auth_module.verify_password(OLD_PASSWORD, _stored(db_session, user.id).password_hash)
        assert _sessions_of(db_session, user.id) == 2
        assert _audit_rows(db_session, user.id, AuditAction.UPDATE) == 0

    def test_failure_while_auditing_leaves_old_password(self, db_session, monkeypatch):
        user, _tokens = self._with_sessions(db_session)
        monkeypatch.setattr(users_module, "audit", _boom)
        with pytest.raises(RuntimeError):
            auth_module.update_user(db_session, user, password=NEW_PASSWORD)
        _crash_and_reload(db_session)
        assert auth_module.verify_password(OLD_PASSWORD, _stored(db_session, user.id).password_hash)
        assert _sessions_of(db_session, user.id) == 2

    def test_deactivation_is_one_transaction_and_revokes_sessions(self, db_session):
        user, _tokens = self._with_sessions(db_session)
        with counting_commits(db_session) as commits:
            auth_module.update_user(db_session, user, is_active=False)
        assert len(commits) == 1
        assert _stored(db_session, user.id).is_active is False
        assert _sessions_of(db_session, user.id) == 0
        assert _audit_rows(db_session, user.id, AuditAction.UPDATE, "деактивирована") == 1

    def test_failure_while_revoking_leaves_the_account_active(self, db_session, monkeypatch):
        user, _tokens = self._with_sessions(db_session)
        monkeypatch.setattr(users_module, "revoke_all_sessions", _boom)
        with pytest.raises(RuntimeError):
            auth_module.update_user(db_session, user, is_active=False)
        _crash_and_reload(db_session)
        assert _stored(db_session, user.id).is_active is True
        assert _sessions_of(db_session, user.id) == 2

    def test_role_change_keeps_sessions_and_is_one_transaction(self, db_session):
        """Смена роли сессии не отзывает (как и раньше): токен несёт не роль, а пользователя, роль читается из БД."""
        user, _tokens = self._with_sessions(db_session)
        with counting_commits(db_session) as commits:
            auth_module.update_user(db_session, user, role="admin")
        assert len(commits) == 1
        assert _stored(db_session, user.id).role == "admin"
        assert _sessions_of(db_session, user.id) == 2
        assert _audit_rows(db_session, user.id, AuditAction.UPDATE, "роль") == 1

    def test_no_changes_writes_no_audit_record(self, db_session):
        user, _tokens = self._with_sessions(db_session)
        with counting_commits(db_session) as commits:
            auth_module.update_user(db_session, user, username="alice", role="viewer")
        assert len(commits) == 1
        assert _audit_rows(db_session, user.id, AuditAction.UPDATE) == 0
        assert _sessions_of(db_session, user.id) == 2


class TestChangeOwnPassword:
    def _with_sessions(self, db_session) -> tuple[User, str, str]:
        user = _alice(db_session)
        current = auth_module.create_session(db_session, user)
        other = auth_module.create_session(db_session, user)
        return user, current, other

    def test_change_is_one_transaction_and_keeps_only_the_current_session(self, db_session):
        user, current, _other = self._with_sessions(db_session)
        with counting_commits(db_session) as commits:
            auth_module.change_own_password(db_session, user, current_password=OLD_PASSWORD, new_password=NEW_PASSWORD, keep_token=current)
        assert len(commits) == 1
        assert auth_module.verify_password(NEW_PASSWORD, _stored(db_session, user.id).password_hash)
        remaining = db_session.scalars(select(AuthSession.token_hash).where(AuthSession.user_id == user.id)).all()
        assert remaining == [sessions_module._hash_token(current)]
        assert _audit_rows(db_session, user.id, AuditAction.UPDATE, "собственный пароль") == 1

    def test_failure_while_revoking_leaves_old_password_and_all_sessions(self, db_session, monkeypatch):
        user, _current, _other = self._with_sessions(db_session)
        monkeypatch.setattr(users_module, "revoke_all_sessions_except", _boom)
        with pytest.raises(RuntimeError):
            auth_module.change_own_password(db_session, user, current_password=OLD_PASSWORD, new_password=NEW_PASSWORD, keep_token=None)
        _crash_and_reload(db_session)
        assert auth_module.verify_password(OLD_PASSWORD, _stored(db_session, user.id).password_hash)
        assert _sessions_of(db_session, user.id) == 2
        assert _audit_rows(db_session, user.id, AuditAction.UPDATE) == 0

    def test_failure_while_auditing_leaves_old_password(self, db_session, monkeypatch):
        user, _current, _other = self._with_sessions(db_session)
        monkeypatch.setattr(users_module, "audit", _boom)
        with pytest.raises(RuntimeError):
            auth_module.change_own_password(db_session, user, current_password=OLD_PASSWORD, new_password=NEW_PASSWORD, keep_token=None)
        _crash_and_reload(db_session)
        assert auth_module.verify_password(OLD_PASSWORD, _stored(db_session, user.id).password_hash)
        assert _sessions_of(db_session, user.id) == 2


class TestRevokeHelpersCommitFlag:
    """По умолчанию помощники коммитят, как раньше (прочие вызывающие не меняются); commit=False оставляет коммит вызывающему."""

    def _user_with_two_sessions(self, db_session) -> tuple[User, str]:
        user = _alice(db_session)
        keep = auth_module.create_session(db_session, user)
        auth_module.create_session(db_session, user)
        return user, keep

    def test_revoke_all_sessions_commits_by_default(self, db_session):
        user, _keep = self._user_with_two_sessions(db_session)
        auth_module.revoke_all_sessions(db_session, user.id)
        _crash_and_reload(db_session)
        assert _sessions_of(db_session, user.id) == 0

    def test_revoke_all_sessions_without_commit_is_rolled_back_with_the_caller(self, db_session):
        user, _keep = self._user_with_two_sessions(db_session)
        auth_module.revoke_all_sessions(db_session, user.id, commit=False)
        _crash_and_reload(db_session)
        assert _sessions_of(db_session, user.id) == 2

    def test_revoke_except_commits_by_default(self, db_session):
        user, keep = self._user_with_two_sessions(db_session)
        auth_module.revoke_all_sessions_except(db_session, user.id, keep)
        _crash_and_reload(db_session)
        assert _sessions_of(db_session, user.id) == 1

    def test_revoke_except_without_commit_is_rolled_back_with_the_caller(self, db_session):
        user, keep = self._user_with_two_sessions(db_session)
        auth_module.revoke_all_sessions_except(db_session, user.id, keep, commit=False)
        _crash_and_reload(db_session)
        assert _sessions_of(db_session, user.id) == 2
