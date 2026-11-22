"""R1-07 п. 2 код-ревью: вытеснение записей `LoginThrottle` не должно стоить O(n log n) под блокировкой.

Раньше при заполненной таблице (10 000 ключей) КАЖДАЯ неудачная попытка с новым ключом обходила все записи и сортировала их под общей
блокировкой — это делало подбор с множеством разных логинов дорогим для самого сервера. Теперь записи лежат в `OrderedDict` в порядке
последней неудачи (`move_to_end` при каждой неудаче), и вытеснение снимает записи с начала за O(1).

Проверяется: порядок вытеснения не изменился (самые старые уходят первыми, обновлённый ключ — последним, просроченные — до свежих), а
стоимость вытеснения не зависит от размера таблицы.

Запуск: pytest backend/tests/test_login_throttle_eviction.py -v
"""

from __future__ import annotations

import time

from app.services.login_throttle import LoginThrottle


class Clock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now

    def tick(self, seconds: float = 0.001) -> None:
        self.now += seconds


def _throttle(max_keys: int, clock: Clock, **extra) -> LoginThrottle:
    # Задержка 500 с (окно 900 с): за время теста, где часы уходят вперёд максимум на десяток секунд, она не истекает сама — так retry_after
    # > 0 значит «запись есть».
    return LoginThrottle(free_attempts=0, base_delay=500.0, max_delay=500.0, window=900.0, max_keys=max_keys, clock=clock, **extra)


def _fill(throttle: LoginThrottle, clock: Clock, keys) -> None:
    for key in keys:
        clock.tick()
        throttle.record_failure(key)


def test_oldest_keys_are_evicted_first_and_fresh_ones_stay():
    clock = Clock()
    throttle = _throttle(10_000, clock)
    _fill(throttle, clock, (("10.0.0.1", f"user{i}") for i in range(10_001)))

    assert len(throttle) == 10_000
    assert throttle.retry_after(("10.0.0.1", "user0")) == 0.0  # самый старый вытеснен: записи о нём нет
    assert throttle.retry_after(("10.0.0.1", "user1")) > 0  # следующий по возрасту ещё на месте
    assert throttle.retry_after(("10.0.0.1", "user10000")) > 0  # свежий на месте


def test_many_overflowing_keys_keep_the_table_at_the_limit():
    clock = Clock()
    throttle = _throttle(100, clock)
    _fill(throttle, clock, range(1_000))
    assert len(throttle) == 100
    assert all(throttle.retry_after(key) > 0 for key in range(900, 1_000))
    assert all(throttle.retry_after(key) == 0.0 for key in range(0, 900))


def test_a_key_that_fails_again_is_no_longer_the_oldest():
    clock = Clock()
    throttle = _throttle(3, clock)
    _fill(throttle, clock, ["a", "b", "c"])
    _fill(throttle, clock, ["a"])  # «a» снова ошиблась — теперь самый свежий; самый старый — «b»
    _fill(throttle, clock, ["d"])  # переполнение: уходит «b», а не «a»

    assert len(throttle) == 3
    assert throttle.retry_after("b") == 0.0
    assert all(throttle.retry_after(key) > 0 for key in ("a", "c", "d"))


def test_expired_entries_go_before_fresh_ones():
    clock = Clock()
    throttle = _throttle(3, clock)
    _fill(throttle, clock, ["old1", "old2"])
    clock.tick(1_000)  # окно (900 с) истекло у обеих
    _fill(throttle, clock, ["fresh1", "fresh2"])  # 4 записи → переполнение; просроченные должны уйти обе, а не одна

    assert len(throttle) == 2
    assert all(throttle.retry_after(key) > 0 for key in ("fresh1", "fresh2"))


def test_reset_and_clear_still_work_after_reordering():
    clock = Clock()
    throttle = _throttle(5, clock)
    _fill(throttle, clock, ["a", "b", "c"])
    _fill(throttle, clock, ["a"])
    throttle.reset("b")
    assert len(throttle) == 2 and throttle.retry_after("b") == 0.0
    throttle.clear()
    assert len(throttle) == 0


# --- Стоимость вытеснения не растёт с размером таблицы ---------------------------------------------------------------------------
def _eviction_seconds(table_size: int, evictions: int) -> float:
    """Время `evictions` неудач с новыми ключами при таблице, уже заполненной до table_size (каждая вызывает вытеснение)."""
    clock = Clock()
    throttle = _throttle(table_size, clock)
    _fill(throttle, clock, range(table_size))
    started = time.perf_counter()
    for index in range(evictions):
        clock.tick()
        throttle.record_failure(("extra", index))
    return time.perf_counter() - started


def test_eviction_cost_does_not_grow_with_the_table_size():
    """Было O(n log n) на каждое вытеснение (полный обход и сортировка); стало O(1). Таблица в 50 раз больше — время почти то же.
    Порог по отношению (10×) намного выше шума и намного ниже прежних ~50× и выше; берётся лучшее из трёх замеров."""
    evictions = 300
    small = min(_eviction_seconds(1_000, evictions) for _ in range(3))
    large = min(_eviction_seconds(50_000, evictions) for _ in range(3))
    assert large < max(small, 1e-4) * 10, f"вытеснение стало зависеть от размера таблицы: {small:.4f} с на 1 000 ключей и {large:.4f} с на 50 000"
