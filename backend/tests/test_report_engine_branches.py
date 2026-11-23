"""
A-06 (код-ревью main @ b375f58): ветки движка и рендера отчётов, которые не вызывал ни один тест.

report_engine: операции фильтра (`ne`, `contains`, `not_contains`, `not_empty`, `is_true`, `is_false`), некорректный фильтр, источники
колонки (`index`, `static`, неизвестный, поле без пути), структурная проверка шаблона (`validate_path`, `validate_config`) со всеми
сообщениями об ошибках.
report_render: ошибки docx-блоков (нет блоков, таблица без сущности/колонок, неизвестный тип, лист без сущности/колонок), выравнивание
абзаца по центру, разрыв страницы, пустые ячейки, диспетчер форматов, ошибка отдельной секции в предпросмотре (остальные секции строятся).

Тесты проверяют поведение — какие строки остаются после фильтра, какой текст в сообщении об ошибке, что лежит в готовом docx, — а
не просто вызывают строки.

Запуск: pytest backend/tests/test_report_engine_branches.py -v
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH

from app.models import VLANDomain
from app.services.report_engine import (
    ReportBuilderError,
    ReportContext,
    column_value,
    iter_report_rows,
    validate_config,
    validate_path,
)
from app.services.report_meta import build_entity_metadata
from app.services.report_render import block_tables, build_docx, build_report_from_template, preview_rows

META = build_entity_metadata()


@pytest.fixture()
def domains(db_session):
    """Три домена: у «Кампус» и «ЦОД» включена автосинхронизация, у «Лаборатория» нет; описание есть не у всех."""
    db_session.add_all(
        [
            VLANDomain(name="Кампус", description="основной", auto_sync=True),
            VLANDomain(name="ЦОД", description="", auto_sync=True),
            VLANDomain(name="Лаборатория", description="тестовый стенд", auto_sync=False),
        ]
    )
    db_session.commit()
    return db_session


def _names(session, filters: list[dict]) -> list[str]:
    ctx = ReportContext(session)
    return sorted(row.name for row, _, _ in iter_report_rows(ctx, "vlan-domains", filters=filters))


# ---------------------------------------------------------------------------------------------------------------------
# report_engine: фильтры
# ---------------------------------------------------------------------------------------------------------------------


class TestFilters:
    def test_ne_drops_rows_with_the_value(self, domains):
        assert _names(domains, [{"path": "name", "op": "ne", "value": "ЦОД"}]) == ["Кампус", "Лаборатория"]

    def test_contains_and_not_contains_ignore_case_and_outer_spaces(self, domains):
        assert _names(domains, [{"path": "description", "op": "contains", "value": "  СТЕНД "}]) == ["Лаборатория"]
        assert _names(domains, [{"path": "description", "op": "not_contains", "value": "стенд"}]) == ["Кампус", "ЦОД"]

    def test_not_empty_keeps_only_rows_with_a_value(self, domains):
        assert _names(domains, [{"path": "description", "op": "not_empty"}]) == ["Кампус", "Лаборатория"]

    def test_is_true_and_is_false_use_the_yes_no_rendering(self, domains):
        assert _names(domains, [{"path": "auto_sync", "op": "is_true"}]) == ["Кампус", "ЦОД"]
        assert _names(domains, [{"path": "auto_sync", "op": "is_false"}]) == ["Лаборатория"]

    def test_several_filters_are_combined_with_and(self, domains):
        filters = [{"path": "auto_sync", "op": "is_true"}, {"path": "description", "op": "not_empty"}]

        assert _names(domains, filters) == ["Кампус"]

    def test_default_operation_is_eq(self, domains):
        assert (
            _names(domains, [{"path": "name", "op": "eq", "value": "кампус"}])
            == _names(domains, [{"path": "name", "value": "кампус"}])
            == ["Кампус"]
        )

    @pytest.mark.parametrize(
        "broken",
        [
            {"op": "eq", "value": "x"},  # нет пути
            {"path": "", "op": "eq", "value": "x"},  # пустой путь
            {"path": "name", "op": "starts_with", "value": "x"},  # неизвестная операция
        ],
    )
    def test_incorrect_filter_is_rejected_with_its_text(self, domains, broken):
        with pytest.raises(ReportBuilderError) as caught:
            _names(domains, [broken])

        assert str(caught.value).startswith("Некорректный фильтр")
        assert str(broken) in str(caught.value), "в сообщении — сам фильтр, чтобы его можно было найти в шаблоне"


# ---------------------------------------------------------------------------------------------------------------------
# report_engine: источники колонки
# ---------------------------------------------------------------------------------------------------------------------


class TestColumnValue:
    @staticmethod
    def _value(session, column: dict, *, index: int = 1, params: dict | None = None):
        ctx = ReportContext(session)
        row = next(iter(ctx.all_rows("vlan-domains").values()))
        return column_value(ctx, "vlan-domains", row, None, None, column, index, params or {})

    def test_index_column_gives_the_row_number(self, domains):
        assert self._value(domains, {"source": "index"}, index=7) == 7

    def test_static_column_substitutes_report_parameters(self, domains):
        assert (
            self._value(domains, {"source": "static", "value": "Отчёт для {{customer}}"}, params={"customer": "ООО «Север»"})
            == "Отчёт для ООО «Север»"
        )

    def test_static_column_with_unknown_parameter_gives_an_empty_place(self, domains):
        assert self._value(domains, {"source": "static", "value": "[{{nobody}}]"}) == "[]"

    def test_field_column_without_a_path_is_an_error_naming_the_header(self, domains):
        with pytest.raises(ReportBuilderError, match="У колонки 'Имя' не задан путь поля"):
            self._value(domains, {"source": "field", "header": "Имя"})

    def test_unknown_source_is_an_error(self, domains):
        with pytest.raises(ReportBuilderError, match="Неизвестный источник колонки: magic"):
            self._value(domains, {"source": "magic"})


# ---------------------------------------------------------------------------------------------------------------------
# report_engine: структурная проверка шаблона
# ---------------------------------------------------------------------------------------------------------------------


class TestValidatePath:
    def test_valid_paths_pass(self):
        validate_path(META, "vlans", "name")
        validate_path(META, "vlans", "domain.name")
        validate_path(META, "vlan-domains", "vlans[].name")

    @pytest.mark.parametrize(
        ("entity", "path", "message"),
        [
            ("vlans", "", "Пустой путь поля"),
            ("vlans", " . ", "Пустой путь поля"),
            ("no-such-entity", "name", "неизвестная сущность 'no-such-entity'"),
            ("vlans", "no_such_field", "у сущности 'vlans' нет поля 'no_such_field'"),
            ("vlans", "nothing.name", "у сущности 'vlans' нет связи 'nothing'"),
            ("vlan-domains", "nothing[].name", "у сущности 'vlan-domains' нет связи-\"многие\" 'nothing[]'"),
        ],
    )
    def test_broken_paths_are_rejected_with_a_readable_message(self, entity, path, message):
        with pytest.raises(ReportBuilderError) as caught:
            validate_path(META, entity, path)

        assert message in str(caught.value)


def _table(**overrides) -> dict:
    block = {"type": "table", "root_entity": "vlans", "columns": [{"header": "VLAN", "path": "vlan_id"}]}
    return {**block, **overrides}


class TestValidateConfig:
    def test_well_formed_template_passes(self):
        validate_config(
            META,
            "docx",
            {
                "blocks": [
                    {"type": "heading", "text": "Заголовок"},
                    {"type": "paragraph", "text": "Текст"},
                    {"type": "page_break"},
                    _table(filters=[{"path": "name", "op": "contains", "value": "a"}], sort_by="vlan_id"),
                    _table(
                        root_entity="vlan-domains",
                        expand="vlans",
                        columns=[{"source": "index"}, {"header": "Статика", "source": "static", "value": "x"}],
                    ),
                ]
            },
        )

    @pytest.mark.parametrize(
        ("config", "message"),
        [
            ({"blocks": [{"type": "heading"}]}, "Блок 1 (heading): не задан текст"),
            ({"blocks": [{"type": "paragraph", "text": ""}]}, "Блок 1 (paragraph): не задан текст"),
            ({"blocks": [_table(root_entity=None)]}, "Блок 1 (таблица): не задана либо неизвестна исходная сущность"),
            ({"blocks": [_table(root_entity="no-such-entity")]}, "Блок 1 (таблица): не задана либо неизвестна исходная сущность"),
            ({"blocks": [_table(expand="nothing")]}, "Блок 1 (таблица): у сущности 'vlans' нет связи-\"многие\" 'nothing'"),
            ({"blocks": [_table(filters=[{"op": "eq"}])]}, "Блок 1 (таблица): у фильтра не задан путь поля"),
            ({"blocks": [_table(filters=[{"path": "name", "op": "like"}])]}, "Блок 1 (таблица): неизвестная операция фильтра 'like'"),
            ({"blocks": [_table(filters=[{"path": "nope", "op": "eq"}])]}, "нет поля 'nope'"),
            ({"blocks": [_table(sort_by="nope")]}, "нет поля 'nope'"),
            ({"blocks": [_table(columns=[])]}, "Блок 1 (таблица): не задано ни одной колонки"),
            ({"blocks": [_table(columns=[{"path": "vlan_id"}])]}, "Блок 1 (таблица): у колонки без заголовка нужно хотя бы одно из полей"),
            ({"blocks": [_table(columns=[{"header": "X", "source": "magic"}])]}, "Блок 1 (таблица): неизвестный источник колонки 'magic'"),
            ({"blocks": [{"type": "page_break"}, {"type": "chart"}]}, "Блок 2: неизвестный тип 'chart'"),
        ],
    )
    def test_each_defect_gets_its_own_message_with_the_block_number(self, config, message):
        with pytest.raises(ReportBuilderError) as caught:
            validate_config(META, "docx", config)

        assert message in str(caught.value)

    def test_unknown_format_is_rejected(self):
        with pytest.raises(ReportBuilderError, match=r"Неизвестный формат отчёта: 'pdf' \(ожидается xlsx или docx\)"):
            validate_config(META, "pdf", {"blocks": []})


# ---------------------------------------------------------------------------------------------------------------------
# report_render
# ---------------------------------------------------------------------------------------------------------------------


class TestBuildDocxErrors:
    @pytest.mark.parametrize(
        ("config", "message"),
        [
            ({}, "В шаблоне не задано ни одного блока"),
            ({"blocks": []}, "В шаблоне не задано ни одного блока"),
            (
                {"blocks": [{"type": "table", "columns": [{"header": "X", "path": "name"}]}]},
                "Блок-таблица должен содержать исходную сущность и хотя бы одну колонку",
            ),
            (
                {"blocks": [{"type": "table", "root_entity": "vlans", "columns": []}]},
                "Блок-таблица должен содержать исходную сущность и хотя бы одну колонку",
            ),
            ({"blocks": [{"type": "heading", "text": "ок"}, {"type": "diagram"}]}, "Неизвестный тип блока: diagram"),
        ],
    )
    def test_invalid_block_is_reported_and_no_file_is_left(self, db_session, tmp_path, config, message):
        with pytest.raises(ReportBuilderError) as caught:
            build_docx(db_session, config, tmp_path / "reports", template_name="Т", params={})

        assert str(caught.value) == message
        assert not list((tmp_path / "reports").glob("*.docx")) if (tmp_path / "reports").exists() else True


class TestBuildDocxContent:
    def test_center_alignment_page_break_heading_level_and_empty_cells(self, domains, tmp_path):
        config = {
            "blocks": [
                {"type": "heading", "text": "Отчёт за {{period}}", "level": 99},  # уровень ограничивается девятью
                {"type": "paragraph", "text": "По центру", "align": "center"},
                {"type": "paragraph", "text": "Обычный"},
                {"type": "page_break"},
                {
                    "type": "table",
                    "root_entity": "vlan-domains",
                    "sort_by": "name",
                    "columns": [
                        {"header": "№ {{period}}", "source": "index"},
                        {"header": "Домен", "path": "name"},
                        {"header": "Описание", "path": "description"},
                    ],
                },
            ]
        }

        path = build_docx(domains, config, tmp_path, template_name="Домены / тест", params={"period": "2026"})

        assert path.suffix == ".docx" and path.parent == tmp_path and "/" not in path.name
        document = Document(str(path))
        paragraphs = {p.text: p for p in document.paragraphs}
        assert "Отчёт за 2026" in paragraphs and paragraphs["Отчёт за 2026"].style.name == "Heading 9"
        assert paragraphs["По центру"].alignment == WD_ALIGN_PARAGRAPH.CENTER
        assert paragraphs["Обычный"].alignment is None
        assert 'w:type="page"' in document.element.body.xml, "разрыв страницы попал в документ"
        (table,) = document.tables
        assert [cell.text for cell in table.rows[0].cells] == ["№ 2026", "Домен", "Описание"]
        assert [[cell.text for cell in row.cells] for row in table.rows[1:]] == [
            ["1", "Кампус", "основной"],
            ["2", "Лаборатория", "тестовый стенд"],
            ["3", "ЦОД", ""],
        ], "строки отсортированы по имени, пустое описание — пустая ячейка"


class TestSheetErrorsSurfaceThroughTables:
    def test_table_without_columns_in_a_sheet_style_block_names_the_title(self, db_session, tmp_path):
        # _sheet_rows сам проверяет исходную сущность и колонки: докс-блок их проверяет раньше, поэтому до этих веток доходит
        # только предпросмотр.
        result = preview_rows(db_session, {"blocks": [{"type": "table", "title": "Без колонок", "root_entity": "vlans", "columns": []}]})

        assert result["sections"] == [{"title": "Без колонок", "error": "У листа 'Без колонок' нет ни одной колонки"}]

    def test_table_without_entity_names_the_title(self, db_session):
        result = preview_rows(
            db_session, {"blocks": [{"type": "table", "title": "Без сущности", "columns": [{"header": "X", "path": "name"}]}]}
        )

        assert result["sections"] == [{"title": "Без сущности", "error": "У листа 'Без сущности' не задана исходная сущность"}]


class TestPreviewRows:
    def test_failing_section_is_reported_and_the_others_are_still_built(self, domains):
        config = {
            "blocks": [
                {"type": "heading", "text": "Не таблица — в предпросмотре не участвует"},
                {
                    "type": "table",
                    "title": "Сломанная",
                    "root_entity": "vlan-domains",
                    "columns": [{"header": "Без пути", "source": "field"}],
                },
                {
                    "type": "table",
                    "title": "Домены",
                    "root_entity": "vlan-domains",
                    "sort_by": "name",
                    "columns": [{"header": "Домен", "path": "name"}],
                },
            ]
        }

        result = preview_rows(domains, config, limit=2)

        broken, good = result["sections"]
        assert broken == {"title": "Сломанная", "error": "У колонки 'Без пути' не задан путь поля"}
        assert good == {"title": "Домены", "headers": ["Домен"], "rows": [["Кампус"], ["Лаборатория"]], "total": 3}, (
            "rows обрезаны по limit, total — полное число строк"
        )

    def test_block_tables_keeps_only_tables(self):
        blocks = [{"type": "heading"}, {"type": "table", "title": "A"}, {"type": "page_break"}, {"type": "table", "title": "B"}]

        assert [b["title"] for b in block_tables(blocks)] == ["A", "B"]


class TestBuildReportFromTemplate:
    @staticmethod
    def _template(fmt: str, config: dict) -> SimpleNamespace:
        return SimpleNamespace(format=fmt, config=json.dumps(config, ensure_ascii=False), name="Шаблон")

    def test_docx_template_is_rendered_by_the_docx_builder(self, domains, tmp_path):
        path = build_report_from_template(domains, self._template("docx", {"blocks": [{"type": "heading", "text": "Привет"}]}), tmp_path)

        assert path.suffix == ".docx" and Document(str(path)).paragraphs[0].text == "Привет"

    def test_xlsx_template_is_rendered_by_the_grid_builder(self, domains, tmp_path):
        config = {"sheets": [{"title": "Домены", "root_entity": "vlan-domains", "columns": [{"header": "Домен", "path": "name"}]}]}

        path = build_report_from_template(domains, self._template("xlsx", config), tmp_path)

        assert path.suffix == ".xlsx"

    def test_unknown_format_is_rejected(self, domains, tmp_path):
        with pytest.raises(ReportBuilderError, match="Неизвестный формат отчёта: pdf"):
            build_report_from_template(domains, self._template("pdf", {}), tmp_path)

    def test_template_without_config_means_no_blocks(self, domains, tmp_path):
        template = SimpleNamespace(format="docx", config="", name="Пустой")

        with pytest.raises(ReportBuilderError, match="В шаблоне не задано ни одного блока"):
            build_report_from_template(domains, template, tmp_path)
