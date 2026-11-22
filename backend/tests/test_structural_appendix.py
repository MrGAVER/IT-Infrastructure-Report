"""
Тесты Word-документа «Приложение к структурной схеме» (services/structural_appendix*.py, эндпоинт
POST /api/v1/reports/structural-appendix).

Главный тест воссоздаёт в БД оборудование из образца заказчика (09101_Структурная_схема_Приложение_1,
имена серийных номеров и систем — как в образце) и сверяет с ним все три таблицы построчно. Намеренные
отличия от образца — только там, где сам образец противоречив или нельзя вывести из данных:

- «Маршрутизатор, Huawei AR651» и «ПАК Шлюз безопасности, GATE 100, V. 4.1» в образце содержат тип
  устройства внутри наименования, а у остальных устройств типа в наименовании нет; в реестре
  наименование — «производитель модель» (здесь «Huawei AR651», «GATE 100, V. 4.1»), тип добавляется
  только в заголовках таблицы VLAN;
- ИС «ASA-09101-5525» в таблице 1 образца и «ASA-5525» в таблицах 2–3 — одно устройство, в реестре у
  него одно системное имя (здесь «ASA-5525»);
- порядок групп таблицы VLAN в образце (коммутатор, МЭ, маршрутизатор, шлюз) из данных не выводится —
  документ идёт в порядке создания устройств.

Запуск: pytest backend/tests/test_structural_appendix.py -v
"""

from __future__ import annotations

from datetime import datetime, timedelta
from itertools import count
from pathlib import Path

import docx
import pytest
from docx.oxml.ns import qn

from app.constants import OwnerType
from app.models import (
    Building,
    Connection,
    ConnectionType,
    DeviceCategory,
    DeviceInterface,
    DeviceModel,
    DeviceStack,
    DeviceStackMember,
    DeviceType,
    IPAddress,
    Manufacturer,
    PhysicalDevice,
    PhysicalDeviceVLAN,
    Room,
    StructuralUnit,
    VLAN,
)
from app.services.structural_appendix import collect_structural_appendix
from app.services.structural_appendix_docx import (
    DEFAULT_IS_NAME,
    StructuralAppendixError,
    _text,
    build_structural_appendix,
    normalize_is_name,
    render_structural_appendix,
)

ROOM = "Серверная комната"


class Registry:
    """Строитель реестра: каждая запись получает следующую секунду created_at — порядок создания
    (он же порядок документа) не зависит от разрешения системных часов."""

    def __init__(self, session):
        self.session = session
        self._clock = count()
        self._base = datetime(2026, 1, 1, 9, 0, 0)
        # Каталоги может уже заполнить фикстура client (стандартные значения) — берём существующие.
        category = session.query(DeviceCategory).filter_by(name="Все").first() or DeviceCategory(name="Все")
        session.add(category)
        session.flush()
        self.category = category
        self.building = Building(name="Здание 1")
        session.add(self.building)
        session.flush()
        self.room = Room(building_id=self.building.id, name=ROOM)
        session.add(self.room)
        self.conn_type = session.query(ConnectionType).filter_by(name="Витая пара").first() or ConnectionType(name="Витая пара")
        session.add(self.conn_type)
        session.flush()
        self.vlans = {}

    def _stamp(self):
        return self._base + timedelta(seconds=next(self._clock))

    def device(self, type_name, maker, model, serial, system_name):
        s = self.session
        dtype = s.query(DeviceType).filter_by(name=type_name).first() or DeviceType(name=type_name, category_id=self.category.id)
        s.add(dtype)
        s.flush()
        manufacturer = s.query(Manufacturer).filter_by(name=maker).first() or Manufacturer(name=maker)
        s.add(manufacturer)
        s.flush()
        device_model = s.query(DeviceModel).filter_by(manufacturer_id=manufacturer.id, device_type_id=dtype.id, model=model).first() or DeviceModel(
            manufacturer_id=manufacturer.id, device_type_id=dtype.id, model=model
        )
        s.add(device_model)
        s.flush()
        dev = PhysicalDevice(
            device_type_id=dtype.id,
            manufacturer_id=manufacturer.id,
            model_id=device_model.id,
            serial_number=serial,
            system_name=system_name,
            created_at=self._stamp(),
            building_id=self.building.id,
            room_id=self.room.id,
        )
        s.add(dev)
        s.flush()
        return dev

    def port(self, dev, name, *, mgmt=False, data=False, ips=()):
        iface = DeviceInterface(physical_device_id=dev.id, name=name, is_management=mgmt, is_data_transfer=data)
        self.session.add(iface)
        self.session.flush()
        for ip in ips:
            self.session.add(IPAddress(owner_type=OwnerType.DEVICE_INTERFACE, owner_id=iface.id, ip_address=ip))
        self.session.flush()
        return iface

    def link(self, a, b, *, active=True):
        conn = Connection(source_interface_id=a.id, destination_interface_id=b.id, connection_type_id=self.conn_type.id, is_active=active, created_at=self._stamp())
        self.session.add(conn)
        self.session.flush()
        return conn

    def vlan(self, dev, number, name, ip=None, prefix=None):
        if number not in self.vlans:
            self.vlans[number] = VLAN(vlan_id=number, name=name)
            self.session.add(self.vlans[number])
            self.session.flush()
        self.session.add(PhysicalDeviceVLAN(physical_device_id=dev.id, vlan_id=self.vlans[number].id, ip_address=ip, prefix_length=prefix))
        self.session.flush()


def seed_sample(session) -> Registry:
    """Оборудование и подключения образца (серверная: 2 сервера, СХД, МЭ, маршрутизатор, стек из двух
    коммутаторов, шлюз безопасности)."""
    r = Registry(session)
    srv205 = r.device("Сервер", "HP", "ProLiant DL360p Gen8", "SN1", "srv-205")
    srv206 = r.device("Сервер", "HP", "ProLiant DL360p Gen8", "SN2", "srv-206")
    shd = r.device("СХД", "HP", "MSA P2000", "SN3", "shd")
    asa = r.device("Межсетевой экран", "Cisco", "ASA 5525", "SN4", "ASA-5525")
    router = r.device("Маршрутизатор", "Huawei", "AR651", "SN5", "RO-A651")
    sw1 = r.device("Коммутатор", "Cisco", "WS-C3750X-48", "SN6", "SW-C3750-2")
    gate = r.device("Шлюз безопасности", "Gate", "GATE 100, V. 4.1", "SN7", "G100")
    sw2 = r.device("Коммутатор", "Cisco", "WS-C3750X-48", "SN9", "SW-C3750-2")
    stack = DeviceStack(name="Стек SW-C3750-2")
    session.add(stack)
    session.flush()
    session.add_all([DeviceStackMember(stack_id=stack.id, physical_device_id=sw1.id, position=1), DeviceStackMember(stack_id=stack.id, physical_device_id=sw2.id, position=2)])

    # Порты управления (IP управления берутся с них; к линиям связи не относятся).
    ilo_205 = r.port(srv205, "ilo", mgmt=True, ips=["192.168.1.205"])
    r.port(asa, "Management0/0", mgmt=True, ips=["192.168.5.42"])
    r.port(router, "Vlanif1", mgmt=True, ips=["172.9.101.1"])
    r.port(gate, "Mgmt", mgmt=True, ips=["192.168.4.41"])
    r.port(sw1, "Vlan1", mgmt=True, ips=["192.168.1.2"])
    r.port(sw2, "Vlan1", mgmt=True, ips=["192.168.1.2"])

    ilo_206 = r.port(srv206, "ilo", mgmt=True, ips=["192.168.1.206"])
    ilo_a = r.port(shd, "ilo", mgmt=True, ips=["192.168.1.106", "192.168.1.107", "192.168.1.108", "192.168.1.109"])
    ilo_b = r.port(shd, "ilo", mgmt=True)

    # Линии связи — в порядке образца (внутри группы назначения порядок создания сохраняется).
    r.link(ilo_205, r.port(sw2, "gi 2/0/35"))
    r.link(ilo_206, r.port(sw2, "gi 2/0/36"))
    r.link(ilo_a, r.port(sw1, "gi 1/0/47"))
    r.link(ilo_b, r.port(sw1, "gi 1/0/48"))
    for dev, nic, sw_port in (
        (srv205, "vmnic0", "gi 2/0/40"),
        (srv205, "vmnic1", "gi 2/0/39"),
        (srv205, "vmnic2", "gi 2/0/41"),
        (srv206, "vmnic0", "gi 2/0/43"),
        (srv206, "vmnic1", "gi 2/0/44"),
        (srv206, "vmnic2", "gi 2/0/42"),
    ):
        r.link(r.port(dev, nic, data=True), r.port(sw2, sw_port))
    for dev, hba, fc in ((srv205, "vmhba2", "FC.B1"), (srv205, "vmhba3", "FC.A1"), (srv206, "vmhba2", "FC.B2"), (srv206, "vmhba3", "FC.A2")):
        r.link(r.port(dev, hba, data=True), r.port(shd, fc, data=True))
    r.link(r.port(shd, "B3", data=True), r.port(sw2, "gi 2/0/5"))
    r.link(r.port(shd, "A3", data=True), r.port(sw2, "gi 2/0/6"))
    r.link(r.port(sw1, "Gi1/0/40"), r.port(router, "gi 0/0/0", data=True))
    r.link(r.port(sw1, "Gi1/0/42"), r.port(gate, "Gi 0/1", data=True))
    r.link(r.port(sw2, "Gi2/0/33"), r.port(asa, "gi 0/0", mgmt=True, data=True))
    r.link(r.port(gate, "Gi 0/0", mgmt=True, data=True), r.port(sw1, "Gi1/0/41"))

    for sw in (sw1, sw2):  # общая настройка стека: одинаковые копии на обоих участниках
        r.vlan(sw, 1, "default", "192.168.1.0", 24)
        r.vlan(sw, 2, "Otd2", "192.168.2.0", 24)
    r.vlan(asa, 1, "default", "192.168.1.0", 24)
    r.vlan(asa, 3, "Otd3", "192.168.3.0", 24)
    r.vlan(router, 4, "vl4", "192.168.4.40", 24)
    r.vlan(gate, 4, "vl4", "192.168.4.40", 24)
    r.vlan(gate, 5, "Vl5", "192.168.5.40", 24)
    session.commit()
    return r


def table_rows(table) -> list[list[str]]:
    """Тексты ячеек по строкам; объединённая ячейка попадает в строку один раз (как её видит читатель)."""
    return [[_tc_text(tc) for tc in tr.tc_lst] for tr in table._tbl.tr_lst]


def _tc_text(tc) -> str:
    return "\n".join("".join(t.text or "" for t in p.iter(qn("w:t"))) for p in tc.iter(qn("w:p")))


def _vmerge_values(table, column_index: int) -> list[str]:
    """Для колонки: 'restart' / 'continue' / '' у каждой строки (по реальной позиции ячейки в строке)."""
    result = []
    for tr in table._tbl.tr_lst:
        tcs = tr.tc_lst
        if column_index >= len(tcs):
            result.append("")
            continue
        merge = tcs[column_index].tcPr.find(qn("w:vMerge")) if tcs[column_index].tcPr is not None else None
        result.append("" if merge is None else (merge.get(qn("w:val")) or "continue"))
    return result


@pytest.fixture()
def sample(db_session):
    return seed_sample(db_session)


def _build(session, tmp_path: Path, **kwargs) -> docx.document.Document:
    path = build_structural_appendix(session, tmp_path, is_name=kwargs.pop("is_name", "ТО"), **kwargs)
    return docx.Document(path)


class TestSampleRegistry:
    def test_link_rows_follow_sample_groups_and_order(self, db_session, sample):
        links = collect_structural_appendix(db_session).links
        assert len(links) == 20
        rows = [(link.left, link.right, link.purpose) for link in links]
        server = "HP ProLiant DL360p Gen8"
        switch = "Cisco WS-C3750X-48 (SW-C3750-2)"
        msa = "HP MSA P2000 (shd)"
        assert rows[:4] == [
            (f"{server} (srv-205) (ilo)", f"{switch} (gi 2/0/35)", "управление активами"),
            (f"{server} (srv-206) (ilo)", f"{switch} (gi 2/0/36)", "управление активами"),
            (f"{msa} (ilo)", f"{switch} (gi 1/0/47)", "управление активами"),
            (f"{msa} (ilo)", f"{switch} (gi 1/0/48)", "управление активами"),
        ]
        assert [r[:2] for r in rows[4:10]] == [
            (f"{server} (srv-205) (vmnic0)", f"{switch} (gi 2/0/40)"),
            (f"{server} (srv-205) (vmnic1)", f"{switch} (gi 2/0/39)"),
            (f"{server} (srv-205) (vmnic2)", f"{switch} (gi 2/0/41)"),
            (f"{server} (srv-206) (vmnic0)", f"{switch} (gi 2/0/43)"),
            (f"{server} (srv-206) (vmnic1)", f"{switch} (gi 2/0/44)"),
            (f"{server} (srv-206) (vmnic2)", f"{switch} (gi 2/0/42)"),
        ]
        assert [r[:2] for r in rows[10:14]] == [
            (f"{server} (srv-205) (vmhba2)", f"{msa} (FC.B1)"),
            (f"{server} (srv-205) (vmhba3)", f"{msa} (FC.A1)"),
            (f"{server} (srv-206) (vmhba2)", f"{msa} (FC.B2)"),
            (f"{server} (srv-206) (vmhba3)", f"{msa} (FC.A2)"),
        ]
        assert [r[2] for r in rows[4:18]] == ["передача данных"] * 14
        assert rows[18][2] == rows[19][2] == "передача данных и управление активами"
        assert rows[18][:2] == (f"{switch} (Gi2/0/33)", "Cisco ASA 5525 (ASA-5525) (gi 0/0)")
        assert rows[19][:2] == ("GATE 100, V. 4.1 (G100) (Gi 0/0)", f"{switch} (Gi1/0/41)")

    def test_vlan_groups_merge_stack_members_without_duplicates(self, db_session, sample):
        groups = {g.title: [(v.vlan_id, v.name, v.addressing) for v in g.rows] for g in collect_structural_appendix(db_session).vlan_groups}
        assert groups["Коммутатор Cisco WS-C3750X-48 (SW-C3750-2) (SN6, SN9)"] == [("1", "default", "192.168.1.0/24"), ("2", "Otd2", "192.168.2.0/24")]
        assert groups["Межсетевой экран Cisco ASA 5525 (ASA-5525) (SN4)"] == [("1", "default", "192.168.1.0/24"), ("3", "Otd3", "192.168.3.0/24")]
        assert groups["Маршрутизатор Huawei AR651 (RO-A651) (SN5)"] == [("4", "vl4", "192.168.4.40/24")]
        assert groups["Шлюз безопасности GATE 100, V. 4.1 (G100) (SN7)"] == [("4", "vl4", "192.168.4.40/24"), ("5", "Vl5", "192.168.5.40/24")]
        assert len(groups) == 4  # серверы и СХД без VLAN в таблицу не попадают

    def test_equipment_rows_match_sample_order_and_management_ips(self, db_session, sample):
        rows = [(e.name, e.serial_number, e.system_name, e.management_ips, e.placement) for e in collect_structural_appendix(db_session).equipment]
        assert rows == [
            ("HP ProLiant DL360p Gen8", "SN1", "srv-205", ["192.168.1.205"], ROOM),
            ("HP ProLiant DL360p Gen8", "SN2", "srv-206", ["192.168.1.206"], ROOM),
            ("HP MSA P2000", "SN3", "shd", ["192.168.1.106", "192.168.1.107", "192.168.1.108", "192.168.1.109"], ROOM),
            ("Cisco ASA 5525", "SN4", "ASA-5525", ["192.168.5.42"], ROOM),
            ("Huawei AR651", "SN5", "RO-A651", ["172.9.101.1"], ROOM),
            ("Cisco WS-C3750X-48", "SN6", "SW-C3750-2", ["192.168.1.2"], ROOM),
            ("Cisco WS-C3750X-48", "SN9", "SW-C3750-2", ["192.168.1.2"], ROOM),  # участник стека — следом за первым
            ("GATE 100, V. 4.1", "SN7", "G100", ["192.168.4.41"], ROOM),
        ]


class TestIsNameNormalization:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("ТО", "ТО"),
            ("ЕАИС ТО", "ТО"),
            ("  еаис   ТО ", "ТО"),  # регистр и лишние пробелы не важны
            ("ИС ТО", "ТО"),
            ("ИСУ", "ИСУ"),  # слово целиком: «ИСУ» — не «ИС У»
            ("ЕАИС", "ЕАИС"),  # одиночное слово остаётся именем, а не превращается в пустое
            ("ЕАИС ТО-2", "ТО-2"),
        ],
    )
    def test_leading_is_word_is_not_duplicated(self, raw, expected):
        assert normalize_is_name(raw) == expected

    def test_default_name_is_eais_to_and_renders_headings_without_duplicate_prefix(self, db_session, sample, tmp_path):
        assert DEFAULT_IS_NAME == "ЕАИС ТО"
        doc = _build(db_session, tmp_path, is_name=DEFAULT_IS_NAME)
        texts = [p.text for p in doc.paragraphs if p.text]
        assert texts[:2] == ["Приложение к структурной схеме", "ЕАИС ТО"]
        assert table_rows(doc.tables[0])[0][0] == "Сведения о назначении линий связи ИС ТО"

    def test_endpoint_without_body_uses_default_name(self, client):
        r = client.post("/api/v1/reports/structural-appendix")
        assert r.status_code == 200
        assert "ТО" in r.json()["file_name"] and "ЕАИС" not in r.json()["file_name"]


class TestRenderedDocument:
    def test_title_tables_and_titles_use_is_name(self, db_session, sample, tmp_path):
        doc = _build(db_session, tmp_path, is_name="  ТО  ")
        texts = [p.text for p in doc.paragraphs if p.text]
        assert texts[:2] == ["Приложение к структурной схеме", "ЕАИС ТО"]
        assert texts[2:] == ["Таблица 1", "Таблица 2", "Таблица 3"]
        assert len(doc.tables) == 3
        titles = [table_rows(t)[0][0] for t in doc.tables]
        assert titles == [
            "Сведения о назначении линий связи ИС ТО",
            "Перечень виртуальных локальных вычислительных сетей (VLAN) ИС ТО",
            "Перечень телекоммуникационного оборудования ИС ТО",
        ]

    def test_links_table_merges_purpose_per_group_and_spans_line_header(self, db_session, sample, tmp_path):
        table = _build(db_session, tmp_path).tables[0]
        rows = table_rows(table)
        assert rows[1] == ["Линия связи", "Назначение"]  # «Линия связи» — одна ячейка на две колонки
        assert len(rows) == 2 + 20
        merges = _vmerge_values(table, 2)
        assert merges[2:] == (["restart"] + ["continue"] * 3) + (["restart"] + ["continue"] * 13) + ["restart", "continue"]
        purposes = [r[-1] for r, m in zip(rows[2:], merges[2:]) if m == "restart"]
        assert purposes == ["управление активами", "передача данных", "передача данных и управление активами"]

    def test_vlan_table_has_full_width_group_rows(self, db_session, sample, tmp_path):
        rows = table_rows(_build(db_session, tmp_path).tables[1])
        assert rows[1] == ["Идентификатор VLAN", "Имя VLAN", "IP-адресация"]
        group_rows = [r for r in rows[2:] if len(r) == 1]
        assert len(group_rows) == 4
        assert "Коммутатор Cisco WS-C3750X-48 (SW-C3750-2) (SN6, SN9)" in [r[0] for r in group_rows]
        assert ["1", "default", "192.168.1.0/24"] in rows

    def test_equipment_table_puts_each_ip_on_its_own_line_and_merges_placement(self, db_session, sample, tmp_path):
        table = _build(db_session, tmp_path).tables[2]
        rows = table_rows(table)
        assert rows[1] == ["Наименование оборудования", "Заводской номер", "Системное имя", "IP-адрес управления", "Место размещения"]
        assert rows[4][3] == "192.168.1.106\n192.168.1.107\n192.168.1.108\n192.168.1.109"
        assert _vmerge_values(table, 4)[2:] == ["restart"] + ["continue"] * 7
        assert rows[2][4] == ROOM and all(len(r) == 5 for r in rows[2:])


class TestRules:
    def test_inactive_connection_is_skipped(self, db_session, sample):
        a = db_session.query(DeviceInterface).filter_by(name="gi 2/0/35").one()
        conn = db_session.query(Connection).filter_by(destination_interface_id=a.id).one()
        conn.is_active = False
        db_session.commit()
        links = collect_structural_appendix(db_session).links
        assert len(links) == 19 and all("(gi 2/0/35)" not in link.right for link in links)

    def test_purpose_is_union_of_both_ports_and_their_subinterfaces(self, db_session):
        r = Registry(db_session)
        a = r.device("Сервер", "HP", "DL", "A1", "a")
        b = r.device("Коммутатор", "Cisco", "SW", "B1", "b")
        r.link(r.port(a, "eth0", data=True), r.port(b, "g1", mgmt=True))
        db_session.commit()
        assert collect_structural_appendix(db_session).links[0].purpose == "передача данных и управление активами"

    def test_link_without_roles_goes_last_with_empty_purpose(self, db_session):
        r = Registry(db_session)
        a = r.device("Сервер", "HP", "DL", "A1", "a")
        b = r.device("Коммутатор", "Cisco", "SW", "B1", "b")
        r.link(r.port(a, "eth0"), r.port(b, "g1"))
        r.link(r.port(a, "eth1", data=True), r.port(b, "g2"))
        db_session.commit()
        assert [link.purpose for link in collect_structural_appendix(db_session).links] == ["передача данных", ""]

    def test_manufacturer_not_repeated_when_model_already_starts_with_it(self, db_session):
        r = Registry(db_session)
        r.device("Межсетевой экран", "Cisco", "Cisco ASA 5525", "A1", "asa")
        db_session.commit()
        assert collect_structural_appendix(db_session).equipment[0].name == "Cisco ASA 5525"

    def test_placement_merge_does_not_join_same_room_name_in_different_buildings(self, db_session):
        r = Registry(db_session)
        other = Building(name="Здание 2")
        db_session.add(other)
        db_session.flush()
        other_room = Room(building_id=other.id, name=ROOM)
        db_session.add(other_room)
        db_session.flush()
        r.device("Сервер", "HP", "DL", "A1", "a")
        second = r.device("Сервер", "HP", "DL", "B1", "b")
        second.building_id, second.room_id = other.id, other_room.id
        db_session.commit()
        keys = [e.placement_key for e in collect_structural_appendix(db_session).equipment]
        assert len(set(keys)) == 2

    def test_structural_unit_filter_keeps_links_with_one_end_in_unit(self, db_session, sample):
        unit = StructuralUnit(name="Отдел")
        db_session.add(unit)
        db_session.flush()
        sample.building.structural_unit_id = unit.id
        db_session.query(PhysicalDevice).filter(PhysicalDevice.serial_number != "SN3").update({"building_id": None, "room_id": None})
        db_session.commit()
        data = collect_structural_appendix(db_session, [unit.id])
        assert [e.serial_number for e in data.equipment] == ["SN3"]
        # СХД — один конец у 8 линий (2 ilo, 4 FC, B3, A3); вторые концы остаются контекстом линии
        assert len(data.links) == 8 and all("HP MSA P2000 (shd)" in link.left + link.right for link in data.links)

    def test_empty_registry_gives_placeholder_rows(self, db_session, tmp_path):
        doc = _build(db_session, tmp_path)
        assert [table_rows(t)[-1] for t in doc.tables] == [["Нет данных"]] * 3

    def test_control_characters_from_registry_do_not_break_the_document(self, db_session, tmp_path):
        # NUL (\x00) сюда не годится: PostgreSQL не хранит его в текстовых полях (DataError при INSERT), так что
        # в реестре на PostgreSQL такого значения быть не может, а на SQLite тест был бы зелёным лишь формально.
        # Очистка \x00 проверяется отдельно, без БД, — см. TestIsName.test_text_strips_xml_invalid_characters.
        r = Registry(db_session)
        r.device("Сервер", "HP", "DL\x07", "S\x08N1", "srv\x1b-1")
        db_session.commit()
        doc = _build(db_session, tmp_path)
        assert table_rows(doc.tables[2])[2][:3] == ["HP DL", "SN1", "srv-1"]


class TestIsName:
    def test_normalizes_whitespace_and_control_characters(self):
        assert normalize_is_name("  ЕА  ИС\x00 ТО ") == "ЕА ИС ТО"

    @pytest.mark.parametrize("raw", ["S\x00N1", "S\x08N1", "S\x0bN1", "S\x0cN1", "S\x1bN1", "S\ufffeN1", "S\uffffN1"])
    def test_text_strips_xml_invalid_characters(self, raw):
        # Без БД: NUL нельзя положить в PostgreSQL, но очистка должна его покрывать (вставка из терминала/Excel).
        assert _text(raw) == "SN1"

    def test_text_keeps_valid_whitespace_and_cyrillic(self):
        assert _text("Серверная\tкомната\n№ 1") == "Серверная\tкомната\n№ 1"

    @pytest.mark.parametrize("raw", [None, "", "   ", "\x00\x01"])
    def test_empty_is_rejected(self, raw):
        with pytest.raises(StructuralAppendixError):
            normalize_is_name(raw)

    def test_too_long_is_rejected(self):
        with pytest.raises(StructuralAppendixError):
            normalize_is_name("а" * 101)

    def test_file_name_is_safe_and_has_docx_suffix(self, db_session, tmp_path):
        path = build_structural_appendix(db_session, tmp_path, is_name='Т/О: "1"')
        assert path.suffix == ".docx" and path.parent == tmp_path
        assert not any(ch in path.name for ch in '/\\:*?"<>|')


class TestEndpoint:
    def test_generate_and_download(self, client, db_session, sample):
        r = client.post("/api/v1/reports/structural-appendix", json={"is_name": "ТО"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["file_name"].endswith(".docx")
        download = client.get(body["download_url"])
        assert download.status_code == 200
        assert download.headers["content-type"].startswith("application/vnd.openxmlformats-officedocument.wordprocessingml.document")

    def test_default_name_without_body(self, client):
        assert client.post("/api/v1/reports/structural-appendix").status_code == 200

    @pytest.mark.parametrize("payload", [{"is_name": ""}, {"is_name": 5}, {"is_name": "ТО", "structural_unit_ids": "x"}])
    def test_invalid_payload_is_422(self, client, payload):
        assert client.post("/api/v1/reports/structural-appendix", json=payload).status_code == 422

    def test_render_function_is_pure_on_data(self, db_session, sample):
        data = collect_structural_appendix(db_session)
        assert len(render_structural_appendix(data, "ТО").tables) == 3
