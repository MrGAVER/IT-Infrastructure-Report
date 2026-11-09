"""Generic CRUD и синхронизация вложенных коллекций (бывший services/crud/, разрезанный по ответственностям).

Фасад отдаёт только ПУБЛИЧНЫЙ API пакета (имена без «_»; он же перечислен в `__all__`). Приватные помощники подмодулей
(`_RESOURCE_VALIDATORS`, `_find_referencing_counts`…) здесь не реэкспортируются: тесту, которому они нужны, следует импортировать их из
подмодуля, где они определены (`from app.services.crud.validators import _RESOURCE_VALIDATORS`) — так граница между публичным и внутренним
API пакета видна в самом импорте (R1-08 код-ревью). Модули:
  - columns: Метаданные ресурсов: какая модель стоит за ключом ресурса и какие колонки в неё можно писать.
  - payload: Проверка входного payload generic CRUD: запись в защищённые ресурсы, схемы Pydantic, неизвестные ключи, типы и длины колонок.
  - audit_log: Запись в журнал аудита и человекочитаемое описание изменений (кто — см. services/actor_context.py).
  - validators: Доменная валидация записей generic CRUD: реестр валидаторов по моделям, слот в стойке.
  - vlan_domains: Согласование VLAN устройств с VLAN-доменами при создании и изменении ресурсов.
  - hooks: Хуки ресурсов: особое поведение отдельных моделей (порядок строк, обогащение, проверки, побочные действия).
  - generic: Generic CRUD: список с фильтрами и пагинацией, создание и изменение записей любого ресурса.
  - deletion: Удаление записей: проверка ссылающихся записей, очистка полиморфных владельцев.
  - owned_rows: Синхронизация «собственных» строк владельца: открытые порты, IP-адреса, развёрнутое ПО (устройства, ВМ, интерфейсы).
  - interfaces: Синхронизация портов (интерфейсов) устройства и чтение VLAN портов формы.
  - interface_groups: Группы портов устройства: чтение, синхронизация и применение значений группы к её портам.
  - subinterfaces: Подинтерфейсы портов устройства: синхронизация, чтение, удаление.
  - interface_group_subinterfaces: Подинтерфейсы групп портов: проверка, шаблоны группы, запись в порты.
  - device_vlans: Синхронизация VLAN физического устройства.
  - information_system: Детали информационной системы: связанные таблицы и источники.

Зависимости между модулями направлены в одну сторону (generic -> hooks -> validators/vlan_domains/owned_rows -> audit_log/columns/payload);
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
    validate_column_types,
    validate_payload_schema,
)
from .audit_log import (  # noqa: F401
    audit,
)
from .validators import (  # noqa: F401
    validate_resource,
)
from .stack_vlan_settings import (  # noqa: F401
    Values,
    apply_stack_settings_to_device,
    assert_device_vlan_editable,
    domain_members,
    link_values,
    locked_vlan_ids,
    member_devices,
    normalize_ip,
    outside_domain,
    plan_member_settings,
    setting_values,
    stack_settings,
    vlan_sort_key,
    write_link,
)
from .vlan_domains import (  # noqa: F401
    assign_domain_vlans_to_device,
)
from .hooks import (  # noqa: F401
    HOOKS,
    ResourceHooks,
    hooks_for,
)
from .generic import (  # noqa: F401
    list_resource,
    create_resource,
    update_resource,
)
from .deletion import (  # noqa: F401
    assert_deletable,
    delete_resource,
)
from .owned_rows import (  # noqa: F401
    sync_owner_open_ports,
    sync_owner_ip_addresses,
    sync_owner_deployed_software,
    sync_vm_open_ports,
    sync_vm_ip_addresses,
    sync_vm_deployed_software,
    sync_device_deployed_software,
)
from .interfaces import (  # noqa: F401
    sync_interfaces,
    get_device_interface_ips,
    get_device_interface_open_ports,
    get_device_interface_vlans,
)
from .interface_groups import (  # noqa: F401
    list_interface_groups,
    get_interface_groups,
)
from .subinterfaces import (  # noqa: F401
    sync_subinterfaces,
    validate_device_subinterfaces,
    delete_subinterfaces,
    purge_subinterfaces_of_interfaces,
    subinterface_references,
    enrich_subinterfaces,
    subinterfaces_by_parent,
    get_device_subinterfaces,
)
from .interface_group_subinterfaces import (  # noqa: F401
    apply_group_subinterfaces,
    delete_group_subinterfaces,
    group_subinterfaces_by_group,
    normalize_group_subinterfaces,
    normalize_ips,
    purge_subinterfaces_of_groups,
    sync_group_subinterfaces,
    with_reused_ids,
)
from .device_vlans import (  # noqa: F401
    sync_device_vlans,
)
from .information_system import (  # noqa: F401
    get_information_system_details,
    sync_information_system_details,
)

__all__ = [
    'HOOKS',
    'ResourceHooks',
    'allowed_columns',
    'assert_deletable',
    'assign_domain_vlans_to_device',
    'apply_group_subinterfaces',
    'audit',
    'columns_for',
    'create_resource',
    'delete_group_subinterfaces',
    'delete_resource',
    'delete_subinterfaces',
    'enrich_subinterfaces',
    'ensure_writable',
    'get_device_subinterfaces',
    'group_subinterfaces_by_group',
    'hooks_for',
    'get_information_system_details',
    'get_interface_groups',
    'get_device_interface_ips',
    'get_device_interface_open_ports',
    'get_device_interface_vlans',
    'list_interface_groups',
    'list_resource',
    'model_for',
    'normalize_group_subinterfaces',
    'normalize_ips',
    'purge_subinterfaces_of_groups',
    'purge_subinterfaces_of_interfaces',
    'subinterface_references',
    'subinterfaces_by_parent',
    'sync_device_deployed_software',
    'sync_device_vlans',
    'sync_group_subinterfaces',
    'sync_information_system_details',
    'sync_interfaces',
    'sync_owner_deployed_software',
    'sync_owner_ip_addresses',
    'sync_owner_open_ports',
    'sync_subinterfaces',
    'sync_vm_deployed_software',
    'sync_vm_ip_addresses',
    'sync_vm_open_ports',
    'update_resource',
    'validate_column_types',
    'validate_device_subinterfaces',
    'validate_payload_schema',
    'validate_resource',
    'Values',
    'apply_stack_settings_to_device',
    'assert_device_vlan_editable',
    'domain_members',
    'link_values',
    'locked_vlan_ids',
    'member_devices',
    'normalize_ip',
    'outside_domain',
    'plan_member_settings',
    'setting_values',
    'stack_settings',
    'vlan_sort_key',
    'with_reused_ids',
    'write_link',
]
