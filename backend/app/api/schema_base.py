"""Общая основа Pydantic-моделей тел запросов (код-ревью main, F-06, этап 2 — все роутеры, включая диаграммы).

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
    """Тело запроса. Лишние поля игнорируются, как и у прежнего ``payload: dict``: клиент может прислать объект целиком.

    ``allow_inf_nan=False``: ``NaN`` и ``±Infinity`` в JSON-стандарте нет, а Python-разбор их принимает — такое число доходило до
    записи и ломало кодирование ответа (500). Вещественное поле теперь отвечает 422 («ожидается конечное число»); в произвольных
    объектах (``config`` отчёта) то же проверяет ``reject_non_finite_numbers``."""

    model_config = ConfigDict(extra="ignore", allow_inf_nan=False)


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


def absent_as_null(raw: object, *names: str) -> object:
    """Подставляет ``null`` вместо отсутствующих обязательных полей (код-ревью, BE-05).

    Для полей, у которых текст ошибки один и для «не прислали», и для «прислали не то»: валидатор поля (``mode="before"``) отвергает
    ``None`` прежним сообщением, а поле объявлено обязательным — без значения по умолчанию, поэтому в OpenAPI оно попадает в
    ``required``. Раньше для этого стояло ``Field(default=None, validate_default=True)`` с подавлением типов: тип обещал ``bool``,
    а значением по умолчанию было ``None``.

    Применяется из ``model_validator(mode="before")`` — до разбора полей, поэтому ошибки отсутствующих и неверных полей собираются
    вместе (до трёх сообщений), как и прежде. Не-объект возвращается как есть: ошибку «ожидается объект» даёт сам Pydantic.
    Если у поля нет проверяющего ``None`` валидатора, его отвергнет сам Pydantic — по типу."""
    if not isinstance(raw, dict):
        return raw
    missing = [name for name in names if name not in raw]
    return {**raw, **dict.fromkeys(missing)} if missing else raw
