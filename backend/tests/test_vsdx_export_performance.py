"""ИА-01 (код-ревью r3): экспорт `.vsdx` не должен снова стать квадратичным по числу узлов.

Раньше копирование фигур (`copy_shape → set_max_ids`) обходило всю страницу на каждую копию: 80 узлов — 6 с, 120 — 13 с, показатель роста ≈ 1,84.
`_ShapeTemplate` убрал обход — рост линейный, ≈ 15 мс на узел (замер: 100 узлов — 1,5 с, 400 — 6,2 с, 24 засечки порта на узел). Потолок
`MAX_VSDX_NODES` и таймаут рендера (`services/vsdx_process.py`) подобраны именно под этот рост: вернись квадратичность, 1000 узлов перестали бы
укладываться в 60 с.

Пороги заданы с большим запасом относительно замера: тест ловит возврат к квадратичному росту, а не шум CI-раннера.
- отношение времени 400 узлов к времени 100 узлов: линейный рост даёт ≈ 4, квадратичный — 13 и больше (на прежнем коде, коммит 4303d4c, замерено 19:
  100 узлов — 5,5 с, 400 — 105,7 с); порог 8 отделяет их с запасом в обе стороны;
- 400 узлов за 25 с (замер ≈ 6 с; на прежнем коде — 105,7 с).
Тест роста проверен красным на прежнем коде (до `_ShapeTemplate`, коммит 4303d4c); второй предел прежний код превышает в четыре раза по тому же замеру.
"""

from __future__ import annotations

import contextlib
import os
import time

import pytest

from app.services.diagram_export import export_vsdx

SMALL_NODES = 100
LARGE_NODES = 400
PORT_TICKS = 24  # как у коммутатора на 24 порта: засечки — самая тяжёлая часть рендера
MAX_GROWTH_RATIO = 8.0
MAX_LARGE_SECONDS = 25.0


def _chain_graph(nodes: int) -> dict:
    """Цепочка из `nodes` коммутаторов, каждый связан со следующим; раскладка — сетка по 20 узлов в строке."""
    icon = {"mode": "generated", "shape": "switch", "color": "#4f7cff", "glyph": '<rect x="2" y="6" width="20" height="9"/>', "port_ticks": PORT_TICKS}
    return {
        "nodes": [{"id": f"dev-{i}", "type": "device", "label": f"sw-{i}", "x": (i % 20) * 300, "y": (i // 20) * 200, "icon": icon} for i in range(nodes)],
        "edges": [
            {
                "id": f"conn-{i}",
                "source_node_id": f"dev-{i}",
                "target_node_id": f"dev-{i + 1}",
                "source_interface": {"id": f"src-{i}", "name": "Gi0/1", "port_index": 0},
                "target_interface": {"id": f"dst-{i}", "name": "Gi0/2", "port_index": 1},
                "connection_type": "Витая пара",
                "is_active": True,
                "vlans": [],
            }
            for i in range(nodes - 1)
        ],
    }


def _render_seconds(nodes: int) -> float:
    """Секунды на один `export_vsdx` графа из `nodes` узлов; stdout библиотеки `vsdx` (сотни тысяч отладочных строк) глушится."""
    graph = _chain_graph(nodes)
    with open(os.devnull, "w", encoding="utf-8") as sink, contextlib.redirect_stdout(sink):
        started = time.perf_counter()
        export_vsdx(graph)
        return time.perf_counter() - started


@pytest.fixture(scope="module")
def timings() -> dict[int, float]:
    """Время для SMALL_NODES (лучшее из двух: первый прогон прогревает импорты и кэши) и для LARGE_NODES (один прогон — он самый долгий)."""
    _render_seconds(10)
    return {SMALL_NODES: min(_render_seconds(SMALL_NODES), _render_seconds(SMALL_NODES)), LARGE_NODES: _render_seconds(LARGE_NODES)}


@pytest.mark.slow
def test_vsdx_export_time_grows_linearly_with_the_number_of_nodes(timings):
    ratio = timings[LARGE_NODES] / timings[SMALL_NODES]
    assert ratio < MAX_GROWTH_RATIO, (
        f"{LARGE_NODES} узлов — {timings[LARGE_NODES]:.2f} с, {SMALL_NODES} — {timings[SMALL_NODES]:.2f} с: в "
        f"{ratio:.1f} раза при {LARGE_NODES // SMALL_NODES}-кратном росте числа узлов (линейный рост ≈ 4, лимит "
        f"{MAX_GROWTH_RATIO:g}); похоже на возврат квадратичного роста"
    )


@pytest.mark.slow
def test_a_large_diagram_is_exported_within_the_limit(timings):
    assert timings[LARGE_NODES] <= MAX_LARGE_SECONDS, f"{LARGE_NODES} узлов — {timings[LARGE_NODES]:.2f} с (лимит {MAX_LARGE_SECONDS:g} с)"
