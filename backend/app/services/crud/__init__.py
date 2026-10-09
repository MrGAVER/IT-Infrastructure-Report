"""Generic CRUD и синхронизация вложенных коллекций (бывший services/crud/, разрезанный по ответственностям).

Публичный API пакета прежний: всё, что раньше импортировалось из `services.crud`, доступно и отсюда, поэтому
вызывающий код и тесты менять не нужно. Модули:
  - columns: Метаданные ресурсов: какая модель стоит за ключом ресурса и какие колонки в неё можно писать.
  - payload: Проверка входного payload generic CRUD: запись в защищённые ресурсы, схемы Pydantic и неизвестные ключи.
  - audit_log: Запись в журнал аудита и человекочитаемое описание изменений (кто — см. services/actor_context.py).
  - validators: Доменная валидация записей generic CRUD: реестр валидаторов по моделям, слот в стойке.
  - vlan_domains: Согласование VLAN устройств с VLAN-доменами при создании и изменении ресурсов.
  - generic: Generic CRUD: список с фильтрами и пагинацией, создание и изменение записей любого ресурса.
  - deletion: Удаление записей: проверка ссылающихся записей, очистка полиморфных владельцев.
  - owned_rows: Синхронизация «собственных» строк владельца: открытые порты, IP-адреса, развёрнутое ПО (устройства, ВМ, интерфейсы).
  - interfaces: Синхронизация портов (интерфейсов) устройства и их групп.
  - device_vlans: Синхронизация VLAN физического устройства.
  - information_system: Детали информационной системы: связанные таблицы и источники.

Зависимости между модулями направлены в одну сторону (generic -> validators/vlan_domains/owned_rows -> audit_log/columns/payload);
циклов нет. Если тест подменяет функцию (monkeypatch), патчить нужно модуль, который её ВЫЗЫВАЕТ, а не этот пакет.
"""
from __future__ import annotations

from .columns import (  # noqa: F401
    model_for,
    columns_for,
    allowed_columns,
)
from .payload import (  # noqa: F401
    ensure_writable,
    validate_payload_schema,
    _SERVICE_PAYLOAD_KEYS,
    _ECHOED_READONLY_KEYS,
    _reject_unknown_keys,
    _format_schema_validation_error,
)
from .audit_log import (  # noqa: F401
    audit,
    _fmt_audit_value,
    _describe_update,
)
from .validators import (  # noqa: F401
    _validate_physical_device,
    _find_rack_slot_occupant,
    _release_rack_slot,
    _validate_physical_device_vlan,
    _validate_device_model,
    _validate_virtual_machine_entry,
    _validate_container_entry,
    _validate_physical_device_vlan_entry,
    _validate_device_model_entry,
    _validate_connection_entry,
    _validate_device_type_entry,
    _validate_diagram_icon_entry,
    _validate_ip_address_entry,
    _validate_information_system_entry,
    _validate_device_stack_member_entry,
    _RESOURCE_VALIDATORS,
    validate_resource,
)
from .vlan_domains import (  # noqa: F401
    _domain_device_ids,
    _unassign_moved_vlan_from_former_domain_devices,
    _auto_assign_new_domain_vlan_to_domain_devices,
    assign_domain_vlans_to_device,
)
from .generic import (  # noqa: F401
    _parse_range_datetime,
    list_resource,
    create_resource,
    update_resource,
)
from .deletion import (  # noqa: F401
    _find_referencing_counts,
    _POLYMORPHIC_OWNER_CLEANUP,
    assert_deletable,
    delete_resource,
)
from .owned_rows import (  # noqa: F401
    _IP_PURPOSE_MAX_LENGTH,
    _SOFTWARE_VERSION_MAX_LENGTH,
    _resolve_protocol_catalog_entry,
    _OPEN_PORT_OWNER_LABELS,
    _validate_open_port_number_is_free,
    _validate_open_port_catalog,
    _sync_owned_rows,
    sync_owner_open_ports,
    sync_owner_ip_addresses,
    sync_owner_deployed_software,
    _sync_owner_collection,
    _sync_vm_collection,
    sync_vm_open_ports,
    sync_vm_ip_addresses,
    sync_vm_deployed_software,
    sync_device_deployed_software,
)
from .interfaces import (  # noqa: F401
    _VLAN_MODES,
    _sync_single_interface,
    _sync_interface_open_ports,
    sync_interfaces,
    list_interface_groups,
    get_interface_groups,
    _GroupState,
    _normalize_group_item,
    _sync_interface_groups,
    _sync_group_vlans,
    _sync_group_open_ports,
    _resolve_interface_group,
    _apply_group_to_interface,
    _delete_stale_groups,
)
from .device_vlans import (  # noqa: F401
    _normalize_device_vlan_item,
    sync_device_vlans,
)
from .information_system import (  # noqa: F401
    get_information_system_details,
    _LINKED_TABLE_SPECS,
    _UNIQUE_SOURCE_OWNERS,
    _assert_no_new_duplicate_sources,
    _sync_linked_table,
    _sync_source_ip_addresses,
    _sync_information_system_sources,
    _unique_source_key,
    sync_information_system_details,
)

__all__ = [
    '_ECHOED_READONLY_KEYS',
    '_GroupState',
    '_IP_PURPOSE_MAX_LENGTH',
    '_LINKED_TABLE_SPECS',
    '_OPEN_PORT_OWNER_LABELS',
    '_POLYMORPHIC_OWNER_CLEANUP',
    '_RESOURCE_VALIDATORS',
    '_SERVICE_PAYLOAD_KEYS',
    '_SOFTWARE_VERSION_MAX_LENGTH',
    '_UNIQUE_SOURCE_OWNERS',
    '_VLAN_MODES',
    '_apply_group_to_interface',
    '_assert_no_new_duplicate_sources',
    '_auto_assign_new_domain_vlan_to_domain_devices',
    '_delete_stale_groups',
    '_describe_update',
    '_domain_device_ids',
    '_find_rack_slot_occupant',
    '_find_referencing_counts',
    '_fmt_audit_value',
    '_format_schema_validation_error',
    '_normalize_device_vlan_item',
    '_normalize_group_item',
    '_parse_range_datetime',
    '_reject_unknown_keys',
    '_release_rack_slot',
    '_resolve_interface_group',
    '_resolve_protocol_catalog_entry',
    '_sync_group_open_ports',
    '_sync_group_vlans',
    '_sync_information_system_sources',
    '_sync_interface_groups',
    '_sync_interface_open_ports',
    '_sync_linked_table',
    '_sync_owned_rows',
    '_sync_owner_collection',
    '_sync_single_interface',
    '_sync_source_ip_addresses',
    '_sync_vm_collection',
    '_unassign_moved_vlan_from_former_domain_devices',
    '_unique_source_key',
    '_validate_connection_entry',
    '_validate_container_entry',
    '_validate_device_model',
    '_validate_device_model_entry',
    '_validate_device_stack_member_entry',
    '_validate_device_type_entry',
    '_validate_diagram_icon_entry',
    '_validate_information_system_entry',
    '_validate_ip_address_entry',
    '_validate_open_port_catalog',
    '_validate_open_port_number_is_free',
    '_validate_physical_device',
    '_validate_physical_device_vlan',
    '_validate_physical_device_vlan_entry',
    '_validate_virtual_machine_entry',
    'allowed_columns',
    'assert_deletable',
    'assign_domain_vlans_to_device',
    'audit',
    'columns_for',
    'create_resource',
    'delete_resource',
    'ensure_writable',
    'get_information_system_details',
    'get_interface_groups',
    'list_interface_groups',
    'list_resource',
    'model_for',
    'sync_device_deployed_software',
    'sync_device_vlans',
    'sync_information_system_details',
    'sync_interfaces',
    'sync_owner_deployed_software',
    'sync_owner_ip_addresses',
    'sync_owner_open_ports',
    'sync_vm_deployed_software',
    'sync_vm_ip_addresses',
    'sync_vm_open_ports',
    'update_resource',
    'validate_payload_schema',
    'validate_resource',
]
