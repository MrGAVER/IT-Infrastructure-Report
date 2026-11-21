"""Pydantic-модели тел запросов роутера порт-конфигурации и подключений.

Заменяют ``payload: dict`` в ``api/port_config.py``. Правила проверки не копируются: они остаются в сервисах
(``port_edit``, ``vlan_mode_cascade``, ``connection_review``), а валидаторы моделей их вызывают через ``delegate_to_parser``
(см. ``schema_base``) — поэтому тексты ошибок прежние, а сервисы по-прежнему проверяют тело сами, когда их зовут напрямую
(тесты, другие сервисы). Модель добавляет к этому описание формы тела в OpenAPI и проверку до обработчика.

Обработчики передают в сервис ``body.model_dump(exclude_unset=True)`` — тот же словарь, что прислал клиент (без полей, которых он не
присылал): сигнатуры сервисов не менялись. Исключение — пилот однократного разбора: ``PortConfigUpdate`` разбирает тело
один раз и отдаёт результат как ``body.request``, а обработчик зовёт ``apply_port_config`` без повторного разбора того же словаря.
Остальные модели (каскад, одобрение) пока работают по-старому.

Порядок проверок прежний: форму тела (режим, edited, флаги, id подключений) сервис и раньше проверял до обращения к БД; содержимое
``port`` у каскада — после поиска порта, поэтому модель его не проверяет.
"""

from __future__ import annotations

from typing import Any, Literal, Self

from pydantic import ConfigDict, Field, ModelWrapValidatorHandler, PrivateAttr, StrictBool, field_validator, model_validator

from ..services.connection_query import MAX_SEARCH_LENGTH
from ..services.connection_review import MAX_APPROVE_BATCH, parse_approve_request
from ..services.port_edit import MAX_VLAN_IDS, PortConfigRequest, parse_port_config_request
from ..services.vlan_mode_cascade import parse_cascade_edited, parse_cascade_mode
from .schema_base import RequestBody, absent_as_null, delegate_to_parser

MAX_PLAN_HASH_LENGTH = 64  # отпечаток плана — 32 hex-символа (sha256[:32]); запас на смену алгоритма

PortMode = Literal["access", "trunk"]


def _checked_flag(name: str, value: object) -> bool:
    """Булево поле с прежним текстом ошибки (у отсутствующего поля он тот же: его подменяет на null ``absent_as_null``)."""
    if not isinstance(value, bool):
        raise ValueError(f"Поле {name} должно быть true или false")
    return value


class PortRoleUpdate(RequestBody):
    """PUT /api/v1/interfaces/{id}/port-role — обе роли заданы всегда: пара флагов однозначно определяет роль порта."""

    is_management: StrictBool = Field(description="Порт используется для управления.")
    is_data_transfer: StrictBool = Field(description="Порт используется для передачи данных.")

    @model_validator(mode="before")
    @classmethod
    def _both_flags_present(cls, raw: object) -> object:
        return absent_as_null(raw, "is_management", "is_data_transfer")  # отсутствие — тот же текст, что у неверного значения

    @field_validator("is_management", mode="before")
    @classmethod
    def _management(cls, value: object) -> bool:
        return _checked_flag("is_management", value)

    @field_validator("is_data_transfer", mode="before")
    @classmethod
    def _data_transfer(cls, value: object) -> bool:
        return _checked_flag("is_data_transfer", value)


class PortConfigUpdate(RequestBody):
    """PUT /api/v1/interfaces/{id}/port-config — роль и/или набор VLAN одной операцией.

    Хотя бы одно из role, vlan_ids, all_vlans. ``vlan_ids`` — ПОЛНЫЙ набор (id записей справочника VLAN), а не изменение;
    ``mode`` — не смена режима, а проверка, что набор выбран для текущего режима порта (иначе 409)."""

    model_config = ConfigDict(extra="forbid")

    role: str | None = Field(default=None, description="Роль порта: management, data, both или none.")
    vlan_ids: list[str] | None = Field(default=None, max_length=MAX_VLAN_IDS, description="Полный набор VLAN порта (id записей справочника).")
    all_vlans: bool | None = Field(default=None, description="«Все VLAN» устройства порта; тогда vlan_ids игнорируется. Только в режиме trunk.")
    mode: PortMode | None = Field(default=None, description="Режим, под который выбран набор VLAN; у порта другой режим — 409.")

    _request: PortConfigRequest = PrivateAttr()

    @model_validator(mode="wrap")
    @classmethod
    def _parse_whole_body_once(cls, raw: object, handler: ModelWrapValidatorHandler[Self]) -> Self:
        # Лишние поля, «хотя бы одно из», типы и допустимые значения — одним прежним разбором: он же отвечает за тексты ошибок.
        # Результат остаётся в модели (`request`), поэтому сервис второй раз тело не разбирает. Отказ разбора поднимается ДО проверки
        # полей модели — как и раньше, когда разбор стоял в валидаторе mode="before".
        if isinstance(raw, cls):  # повторная проверка готового экземпляра: разбор уже сделан
            return handler(raw)
        request = delegate_to_parser(parse_port_config_request, raw)
        model = handler(raw)
        model._request = request
        return model

    @property
    def request(self) -> PortConfigRequest:
        """Разобранное тело: правка (роль, набор VLAN, «Все VLAN») и режим, под который выбран набор (None — не проверять)."""
        return self._request


class CascadePreviewRequest(RequestBody):
    """POST /api/v1/interfaces/{id}/vlan-mode-cascade/preview — предпросмотр каскадной смены режима порта."""

    mode: PortMode = Field(description="Целевой режим порта-инициатора.")
    edited: dict[str, Any] | None = Field(
        default=None,
        description="Снимок формы устройства с открытой формой: {device_id, ports: {id: {mode, group?, vlan_ids?, name?}}, groups: {ключ: {mode, vlan_ids?, name?}}}. С port не сочетается.",
    )
    # Содержимое port проверяет сервис — после поиска порта, как и раньше: ошибка в роли/VLAN у несуществующего порта — 404, а не 422.
    port: dict[str, Any] | None = Field(
        default=None,
        description="Роль и ПОЛНЫЙ набор VLAN порта-инициатора {role?, vlan_ids?, all_vlans?}: проверяются под целевой режим.",
    )

    @model_validator(mode="before")
    @classmethod
    def _mode_present(cls, raw: object) -> object:
        return absent_as_null(raw, "mode")  # отсутствие — то же сообщение, что у неверного режима (_mode)

    @field_validator("mode", mode="before")
    @classmethod
    def _mode(cls, value: object) -> object:
        return delegate_to_parser(parse_cascade_mode, value)

    @field_validator("edited", mode="before")
    @classmethod
    def _edited(cls, value: object) -> object:
        delegate_to_parser(parse_cascade_edited, value)  # правила вложенной структуры — в сервисе; здесь только проверка
        return value


class CascadeApplyRequest(CascadePreviewRequest):
    """POST /api/v1/interfaces/{id}/vlan-mode-cascade — применение плана из предпросмотра (mode, edited и port те же)."""

    plan_hash: str | None = Field(default=None, max_length=MAX_PLAN_HASH_LENGTH, description="Hash плана из предпросмотра; план изменился — 409.")
    confirm: bool | None = Field(default=None, description="Должно быть true — явное подтверждение применения.")

    @field_validator("confirm", mode="before")
    @classmethod
    def _confirm(cls, value: object) -> bool | None:
        # Строка «true» или 1 — не подтверждение: она не приводится к true, а доходит до сервиса как None и получает прежнее
        # сообщение «Применение требует подтверждения» (проверка `confirm is True` осталась в сервисе).
        return value if isinstance(value, bool) else None


class ApproveMatch(RequestBody):
    """Условия «одобрить все найденные»: те же q и is_active, что у списка подключений."""

    q: str | None = Field(default=None, max_length=MAX_SEARCH_LENGTH, description="Строка поиска, как в списке подключений.")
    is_active: bool | None = Field(default=None, description="Только активные (true), только неактивные (false) или все (null).")


class ApprovePortConfigRequest(RequestBody):
    """POST /api/v1/connections/port-config/approve — одобрить расхождение конфигурации портов.

    Ровно одно из полей: ``connection_ids`` (перечисленные подключения) или ``match`` (все подключения с расхождением под условиями поиска)."""

    connection_ids: list[str] | None = Field(
        default=None,
        max_length=MAX_APPROVE_BATCH,
        description=f"Идентификаторы подключений; от 1 до {MAX_APPROVE_BATCH} за запрос.",
    )
    match: ApproveMatch | None = Field(default=None, description="Условия поиска: одобрить ВСЕ подключения с расхождением, а не только показанную страницу.")

    @model_validator(mode="before")
    @classmethod
    def _whole_body(cls, raw: object) -> object:
        delegate_to_parser(parse_approve_request, raw)
        return raw
