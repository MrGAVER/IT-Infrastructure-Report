"""Кто выполняет текущий запрос — для журнала аудита.

Журнал аудита должен отвечать на вопрос «кто это сделал». Функция crud.audit() вызывается из десятков
мест глубоко в сервисах, где HTTP-запроса нет, а протаскивать пользователя параметром через все
сигнатуры — значит трогать каждый вызов. Поэтому актор лежит в ContextVar: его выставляет
auth_gate_middleware (services/auth/gate.py) на время запроса, а audit() читает.

ContextVar, а не глобальная переменная и не request.state: значение изолировано между параллельными
запросами и корректно переходит в потоки синхронных эндпоинтов (anyio копирует контекст).
"""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Actor:
    """user_id/username — None, пока аутентификация выключена или запрос анонимный; ip — адрес клиента
    (None, если он неизвестен). username хранится вместе с id, чтобы запись журнала оставалась
    читаемой после удаления учётной записи."""
    user_id: Optional[str] = None
    username: Optional[str] = None
    ip: Optional[str] = None


NO_ACTOR = Actor()
current_actor: ContextVar[Actor] = ContextVar("current_actor", default=NO_ACTOR)
