"""Создание песочниц жюри на SQLite — по очереди между потоками процесса (развёртывание с нуля 11.10: запасная
песочница в фоне и вход эксперта писали одновременно → «database is locked», пример устной защиты не создавался)."""
from __future__ import annotations

import threading
import time
from types import SimpleNamespace

from app.modules.jury import seed


class _FakeDb:
    def __init__(self, dialect: str):
        self._bind = SimpleNamespace(dialect=SimpleNamespace(name=dialect))

    def get_bind(self):
        return self._bind


def test_sqlite_lock_serializes_threads():
    inside, overlap = [0], [False]
    gate = threading.Barrier(4)

    def work():
        gate.wait()
        with seed._lock(_FakeDb("sqlite")):
            inside[0] += 1
            if inside[0] > 1:
                overlap[0] = True
            time.sleep(0.05)
            inside[0] -= 1

    ts = [threading.Thread(target=work) for _ in range(4)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(5)
    assert not overlap[0]
    assert inside[0] == 0


def test_sqlite_lock_is_reentrant():
    # ensure → create_jury → ensure_ideas и т. п. не должны зависнуть, если вложатся в одном потоке
    db = _FakeDb("sqlite")
    with seed._lock(db):
        with seed._lock(db):
            pass
