"""
Лёгкая замена SQLAlchemy/session для тестирования backend/app/reporting.py без установки
реальных зависимостей (fastapi/sqlalchemy). Раньше такие проверки писались как одноразовые
скрипты в ходе ручной отладки — здесь они оформлены как переиспользуемый, запускаемый набор.

Если в окружении есть настоящий SQLAlchemy, эти тесты можно один в один переписать на реальную
in-memory SQLite сессию — форма мока намеренно повторяет реальный API (`session.scalars(select(X)...).all()`).
"""
from __future__ import annotations

import sys
import types
import importlib.util
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent / "app"

MODEL_NAMES = [
    "Building", "Connection", "ConnectionType", "Container", "Department", "DeviceInterface",
    "DeviceModel", "DeviceSoftware", "DeviceType", "EmbeddedOperatingSystem",
    "ISDepartment", "ISPlacementAsset", "ISProtocol",
    "InformationSystem", "InformationSystemSource", "InterfaceIP", "InterfaceType",
    "InterfaceVLAN", "Manufacturer", "OpenPort", "OperatingSystem", "PhysicalDevice",
    "PhysicalDeviceVLAN", "PlacementAsset", "ProtocolPortCatalog", "Rack", "Room",
    "SoftwareAsset", "StructuralUnit", "SupportMethod", "SupportOrganization", "VLAN", "VMIP", "VMSoftware",
    "VirtualMachine", "CryptoProtectionMeans",
]


class DummyAttr:
    """Заглушка для сравнений вида Model.column == value внутри select(...).where(...)."""
    def __eq__(self, other):
        return True


class Query:
    def __init__(self, entity):
        self.entity = entity

    def where(self, *a, **k):
        return self

    def order_by(self, *a, **k):
        return self


def select(entity, *a, **k):
    return Query(entity)


class ObjMeta(type):
    def __getattr__(cls, item):
        return DummyAttr()


class Obj(metaclass=ObjMeta):
    def __init__(self, **kw):
        self.__dict__.update(kw)

    def __getattr__(self, item):
        # Имитирует nullable-колонки ORM: неуказанный атрибут молча считается None,
        # а не бросает AttributeError, как обычный Python-объект.
        return None


class FakeResult:
    def __init__(self, items):
        self.items = items

    def all(self):
        return self.items


class FakeSession:
    """session.scalars(select(Model)...).all() -> все объекты данного типа из таблицы."""
    def __init__(self, table: dict[str, list]):
        self.table = table

    def scalars(self, stmt):
        return FakeResult(self.table.get(stmt.entity.__name__, []))

    def get(self, cls, id_):
        return None


def load_reporting_module():
    """Импортирует backend/app/reporting.py с подменёнными sqlalchemy/app.models,
    возвращает (build_report, model_classes).

    Код-ревью (тест-изоляция): раньше подмены sys.modules['app.models'] и т.п. НИКОГДА не
    восстанавливались — эта функция вызывается из TestReporting.setUp() (unittest, tests/
    test_reporting.py) перед КАЖДЫМ тестом того класса и оставляла поддельные модули в
    sys.modules насовсем. Баг был незаметен только по случайному алфавитному порядку файлов:
    ни один тестовый файл после test_reporting.py не использовал db_session (тот делает
    `from app.models import Base` заново при каждом вызове фикстуры — tests/conftest.py) —
    как только в проекте появился файл test_validate_resource_registry.py (по алфавиту он
    идёт последним), падать стал уже он с ImportError: cannot import name 'Base', хотя причина
    была не в нём. Теперь исходные записи sys.modules сохраняются и гарантированно
    восстанавливаются в finally: mod.__dict__ уже захватил прямые ссылки на поддельные классы/
    функции к моменту exec() (`from app.models import *` в reporting.py биндит имена в globals
    исполняемого модуля), поэтому восстановление sys.modules сразу после exec() ничего не
    ломает в уже собранном build_report."""
    fake_modules: dict[str, types.ModuleType] = {}

    sa = types.ModuleType("sqlalchemy")
    sa.select = select
    fake_modules["sqlalchemy"] = sa
    orm = types.ModuleType("sqlalchemy.orm")
    orm.Session = type("Session", (), {})
    fake_modules["sqlalchemy.orm"] = orm

    model_classes = {}
    models_module = types.ModuleType("app.models")
    for name in MODEL_NAMES:
        cls = ObjMeta(name, (Obj,), {})
        model_classes[name] = cls
        setattr(models_module, name, cls)
    fake_modules["app.models"] = models_module

    app_module = types.ModuleType("app")
    app_module.__path__ = []  # делает "app" пакетом, чтобы относительные импорты reporting.py работали
    fake_modules["app"] = app_module

    services_module = types.ModuleType("app.services")
    services_module.__path__ = []
    fake_modules["app.services"] = services_module

    # computed.py и excel_safety.py не имеют зависимостей от SQLAlchemy — подключаем настоящие
    # модули как есть, а не мокаем: их логика ("IP/порт управления устройства",
    # excel_safe — код-ревью п.3.2) должна тестироваться реальной, а не заглушкой.
    computed_spec = importlib.util.spec_from_file_location("app.services.computed", APP_DIR / "services" / "computed.py")
    computed_module = importlib.util.module_from_spec(computed_spec)
    computed_spec.loader.exec_module(computed_module)
    fake_modules["app.services.computed"] = computed_module

    excel_safety_spec = importlib.util.spec_from_file_location("app.services.excel_safety", APP_DIR / "services" / "excel_safety.py")
    excel_safety_module = importlib.util.module_from_spec(excel_safety_spec)
    excel_safety_spec.loader.exec_module(excel_safety_module)
    fake_modules["app.services.excel_safety"] = excel_safety_module

    saved_modules = {name: sys.modules.get(name) for name in fake_modules}
    sys.modules.update(fake_modules)
    try:
        src = (APP_DIR / "reporting.py").read_text()
        src = src.replace(
            "from .models import *  # noqa: F401,F403",
            "from app.models import *  # noqa: F401,F403",
        )
        src = src.replace(
            "from .services.computed import ip_label, device_management_ports_and_ips",
            "from app.services.computed import ip_label, device_management_ports_and_ips",
        )
        src = src.replace(
            "from .services.excel_safety import excel_safe_row",
            "from app.services.excel_safety import excel_safe_row",
        )
        mod = types.ModuleType("app.reporting")
        exec(compile(src, str(APP_DIR / "reporting.py"), "exec"), mod.__dict__)
        return mod.build_report, model_classes
    finally:
        for name, original in saved_modules.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original


def empty_table() -> dict[str, list]:
    return {name: [] for name in MODEL_NAMES}
