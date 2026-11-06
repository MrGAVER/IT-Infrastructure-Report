"""Общая основа Pydantic-моделей тел запросов (код-ревью main, F-06, этап 2 — роутеры, кроме диаграмм).

Модель тела — граница API: она описывает форму запроса в OpenAPI и отклоняет неверное тело до обработчика. Правила при этом остаются
там, где они были, — в сервисах (``services/report_params.py``, ``services/port_edit.py`` и т.д.): их вызывают и тесты, и другие
сервисы (каскад режимов разбирает вложенное ``port`` тем же ``parse_port_change``), поэтому второй набор правил в моделях
расходился бы с первым. Валидатор модели вызывает существующий разбор через ``delegate_to_parser``: отказ ``HTTPException(422, текст)``
превращается в ``ValueError`` с тем же текстом, а общий обработчик ``RequestValidationError`` (services/request_errors.py) отдаёт его
клиенту как есть — строкой в ``detail``. Если в теле несколько ошибок, показываются все (до трёх, через «; »): прежний код называл
только первую.

Порядок проверок. FastAPI проверяет тело до обработчика, поэтому там, где раньше запись искали раньше разбора тела, поиск
вынесен в зависимость (она выполняется раньше тела): неизвестный шаблон или ИС по-прежнему отвечают 404, а не 422 про тело.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class RequestBody(BaseModel):
    """Тело запроса. Лишние поля игнорируются, как и у прежнего ``payload: dict``: клиент может прислать объект целиком."""

    model_config = ConfigDict(extra="ignore")


def delegate_to_parser(parse: Callable[[Any], T], raw: Any) -> T:
    """Вызывает существующий разбор из сервиса и превращает его отказ 422 в ``ValueError`` с тем же текстом.

    Другие коды (404, 409) не перехватываются: разбор тела их не поднимает, а если поднимет — это ошибка, которую нельзя
    выдавать за «неверное тело»."""
    try:
        return parse(raw)
    except HTTPException as exc:
        if exc.status_code != 422:
            raise
        raise ValueError(str(exc.detail)) from None
