"""Контроль частоты показа заданий и состав сессии (поверх ``assessment_bank.psychometrics``, банк не меняется).

* **Sympson — Hetter.** Выбранное по информации семейство показывается с вероятностью K_f, иначе берётся
  следующее по информации. K_f откалиброваны симуляцией (``tools/calibrate_exposure.py``) так, чтобы доля
  сессий, в которых показано семейство, не превышала r_max. Коэффициенты лежат в ``exposure_k.json`` рядом
  с этим файлом — по направлению; нет файла или семейства в нём — K = 1 (без ограничения).
* **Ротация субпулов.** Оцениваемые семейства каждого блока разбиты на n субпулов «змейкой» по трудности
  (``pool_from_specs``): каждый субпул покрывает весь диапазон. Сессия получает один субпул: первая — по
  seed сессии (равномерно), повторная — другой субпул, чем в прошлой попытке (параллельная форма).
  Субпул, который утёк, выводится из ротации настройкой ASSESSMENT_SUBPOOL_QUARANTINE (номера через запятую).
* **Состав сессии.** Не больше ``max_per_format`` заданий формата: open_book_3step — 2 (три шага, ~15 мин,
  адаптивный выбор иначе тянет их из-за большой информации), open_answer — 1 (~20 мин). Лимит действует и в
  дотестировании у порога (там и так только короткие задания, см. ``CATConfig.ext_item_time_s``).
"""
from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path

from assessment_bank.psychometrics import CATSession, ExposureControl, PoolItem

K_FILE = Path(__file__).with_name("exposure_k.json")
DEFAULT_FORMAT_LIMITS = {"open_book_3step": 2, "open_answer": 1}


class AppCATSession(CATSession):
    """CATSession с ограничением числа заданий одного формата в сессии."""

    def __init__(self, *args, max_per_format: dict[str, int] | None = None, **kwargs):
        self.max_per_format = dict(DEFAULT_FORMAT_LIMITS if max_per_format is None else max_per_format)
        super().__init__(*args, **kwargs)
        self._fmt = {fid: i.format for fid, i in self.items.items()}

    def format_counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for a in self.administered:
            if not a.canary:
                f = self._fmt.get(a.family_id) or getattr(self.items.get(a.family_id), "format", "")
                out[f] = out.get(f, 0) + 1
        return out

    def _limit(self, cands: list[PoolItem]) -> list[PoolItem]:
        if not self.max_per_format:
            return cands
        cnt = self.format_counts()
        return [i for i in cands if cnt.get(i.format, 0) < self.max_per_format.get(i.format, 10**6)]

    def _candidates(self) -> list[PoolItem]:
        return self._limit(super()._candidates())

    def _ext_candidates(self) -> list[PoolItem]:
        return self._limit(super()._ext_candidates())


@lru_cache(maxsize=1)
def exposure_table() -> dict:
    try:
        return json.loads(K_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def exposure_control(direction: str) -> ExposureControl | None:
    """Свежий ExposureControl с K_f направления (счётчики не нужны: сессия пересобирается на каждом запросе)."""
    t = exposure_table()
    if not t:
        return None
    return ExposureControl(r_max=float(t.get("r_max", 0.3)), k=dict(t.get("k", {}).get(direction, {})))


def choose_subpool(n_subpools: int, seed: int, previous: list[int] | None = None,
                   quarantined: set[int] | None = None) -> int | None:
    """Субпул новой сессии. None — ротация выключена (n ≤ 1) или все субпулы на карантине."""
    if n_subpools <= 1:
        return None
    active = [k for k in range(n_subpools) if k not in (quarantined or set())]
    if not active:
        return None
    prev = [p for p in (previous or []) if p in active]
    if prev and len(active) > 1:
        last = prev[0]
        # повторная попытка — следующий активный субпул после прошлого (параллельная форма)
        return active[(active.index(last) + 1) % len(active)]
    return active[int(seed) % len(active)]


def parse_quarantine(s: str | None) -> set[int]:
    out = set()
    for part in (s or "").replace(";", ",").split(","):
        part = part.strip()
        if part.isdigit():
            out.add(int(part))
    return out
