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
  ``max_item_time_s`` — только задания с рекомендуемым временем не больше этого (экспресс-тест жюри: 5–7 коротких).
* **Семейства прошлых попыток (И26, 09.10).** ``seen`` — семейства всех прошлых попыток кандидата по направлению
  с «возрастом» (0 — последняя попытка, 1 — предпоследняя, …). Они не берутся ни в основную часть, ни в
  дотестирование. Основная часть: новые семейства своего субпула (как прежде: кончился один блок — берётся другой);
  затем новые семейства других активных субпулов; когда новых нет — виденные давнее всего (LRU, по блокам), с новым
  вариантом (новый seed, bank_engine). Дотестирование у порога: новые короткие семейства; LRU — только из попыток
  до последней (семейства последней попытки туда не попадали и раньше). ``seen`` пуст или не задан — выбор как
  прежде (первая попытка и сессии, начатые до обновления, не меняются).
"""
from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path

from assessment_bank.psychometrics import CATSession, ExposureControl, PoolItem

K_FILE = Path(__file__).with_name("exposure_k.json")
DEFAULT_FORMAT_LIMITS = {"open_book_3step": 2, "open_answer": 1, "incident_sim": 2}


class AppCATSession(CATSession):
    """CATSession с ограничением числа заданий одного формата в сессии и поддержкой отбора у порогов грейдов."""

    def __init__(self, *args, max_per_format: dict[str, int] | None = None, max_item_time_s: float | None = None,
                 seen: dict[str, int] | None = None, ext_lru: bool = False,
                 code_open_share: float = 0.0, **kwargs):
        self.max_per_format = dict(DEFAULT_FORMAT_LIMITS if max_per_format is None else max_per_format)
        self.max_item_time_s = max_item_time_s
        self.code_open_share = float(code_open_share)
        super().__init__(*args, **kwargs)
        self._fmt = {fid: i.format for fid, i in self.items.items()}
        self.seen = {str(k): int(v) for k, v in (seen or {}).items()}
        self.ext_lru = ext_lru  # True — дотестирование предварительного Junior (confirm): LRU по всем прошлым попыткам
        if self.seen:
            # запасной путь: весь банк направления без канареек, исключённых (стек, Стажёр) и субпулов на карантине
            excl, blocked = set(kwargs.get("exclude") or ()), set(kwargs.get("blocked_subpools") or ())
            self._reserve = [i for i in self.items.values() if not i.canary and i.family_id not in excl
                             and (i.subpool == self.subpool or i.subpool not in blocked)]

    def format_counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for a in self.administered:
            if not a.canary:
                f = self._fmt.get(a.family_id) or getattr(self.items.get(a.family_id), "format", "")
                out[f] = out.get(f, 0) + 1
        return out

    def _limit(self, cands: list[PoolItem]) -> list[PoolItem]:
        if self.max_item_time_s is not None:
            cands = [i for i in cands if i.time_limit_s <= self.max_item_time_s]
        if not self.max_per_format:
            out = cands
        else:
            cnt = self.format_counts()
            out = [i for i in cands if cnt.get(i.format, 0) < self.max_per_format.get(i.format, 10**6)]
            # В полном тесте (min_items >= 8) гарантируем выдачу хотя бы одного развёрнутого задания (open_answer / open_book_3step)
            # к 5-му оцениваемому шагу, даже если тестовых семейств mcq_concept в банке в несколько раз больше
            if (
                self.cfg.min_items >= 8
                and not self.seen
                and self.n_scored >= 4
                and cnt.get("open_answer", 0) + cnt.get("open_book_3step", 0) == 0
                and (self.max_per_format.get("open_answer", 0) > 0 or self.max_per_format.get("open_book_3step", 0) > 0)
            ):
                open_cands = [i for i in out if i.format in ("open_answer", "open_book_3step")]
                if open_cands:
                    out = open_cands
        if self.code_open_share > 0.0 and out:
            from app.modules.assessment.sprt import CODE_OPEN_FORMATS, filter_code_open_pool
            cnt = self.format_counts()
            n_co = sum(v for k, v in cnt.items() if k in CODE_OPEN_FORMATS)
            out = filter_code_open_pool(out, self.n_scored, n_co, self.code_open_share)
        return out

    def _candidates(self) -> list[PoolItem]:
        base = self._limit(super()._candidates())
        if not self.seen:
            return base
        # 1) новые семейства своего субпула — как прежде (кончился блок — берётся другой блок, см. CATSession._next_main);
        # 2) новые семейства других активных субпулов; 3) LRU по блокам — виденные давнее всего, с новым вариантом
        fresh = [i for i in base if i.family_id not in self.seen]
        if fresh:
            return fresh
        left = self.cfg.max_time_s - self.time_used
        reserve = self._limit([i for i in self._reserve if i.family_id not in self.used and i.time_limit_s <= left])
        fresh = [i for i in reserve if i.family_id not in self.seen]
        if fresh:
            return fresh
        return [i for common in (True, False) for i in self._oldest([r for r in reserve if (r.block == "common") == common])]

    def _ext_candidates(self) -> list[PoolItem]:
        base = self._limit(super()._ext_candidates())
        if not self.seen:
            return base
        fresh = [i for i in base if i.family_id not in self.seen]
        if fresh:
            return fresh
        # LRU в дотестировании у порога — без семейств последней попытки (как прежде: они в дотестирование не
        # попадали); дотестирование предварительного Junior (confirm) — LRU по всем, чтобы не кончилось без заданий
        return self._oldest(base if self.ext_lru else [i for i in base if self.seen.get(i.family_id, 0) >= 1])

    def _oldest(self, cands: list[PoolItem]) -> list[PoolItem]:
        """LRU: из виденных кандидатом семейств — те, что он видел давнее всего (наибольший «возраст»)."""
        old = [i for i in cands if i.family_id in self.seen]
        if not old:
            return []
        m = max(self.seen[i.family_id] for i in old)
        return [i for i in old if self.seen[i.family_id] == m]


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
