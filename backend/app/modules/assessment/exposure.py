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
from app.modules.assessment.sprt import (
    CODE_OPEN_FORMATS,
    DEFAULT_ALPHA,
    DEFAULT_CODE_OPEN_SHARE,
    DEFAULT_DELTA,
    filter_code_open_pool,
    select_target_cut,
    sprt_bound,
    step_llr,
)
from app.modules.catalog.seed_data import ALL_GRADE_CUTS as GRADE_CUTS

K_FILE = Path(__file__).with_name("exposure_k.json")
DEFAULT_FORMAT_LIMITS = {"open_book_3step": 2, "open_answer": 1, "incident_sim": 1}
LONG_FORMATS = frozenset({"open_book_3step", "open_answer", "incident_sim"})
MAX_LONG_FORMATS_TOTAL = 2  # не более 2 длинных многошаговых/развёрнутых заданий за сессию, чтобы уложиться в 60 мин


class AppCATSession(CATSession):
    """CATSession с ограничением числа заданий одного формата, квотой ≥ 1/3 кодовых/открытых заданий,
    классификационным отбором у порогов грейдов и последовательным критерием Вальда (SPRT).
    """

    def __init__(self, *args, max_per_format: dict[str, int] | None = None, max_item_time_s: float | None = None,
                 seen: dict[str, int] | None = None, ext_lru: bool = False,
                 code_open_share: float | None = None, sprt_alpha: float = DEFAULT_ALPHA,
                 sprt_delta: float = DEFAULT_DELTA, **kwargs):
        self.max_per_format = dict(DEFAULT_FORMAT_LIMITS if max_per_format is None else max_per_format)
        self.max_item_time_s = max_item_time_s
        # По умолчанию в полном тесте (без жёсткого ограничения времени одного задания экспресс-режима) доля кода/открытых ≥ 1/3
        if code_open_share is None:
            self.code_open_share = DEFAULT_CODE_OPEN_SHARE if max_item_time_s is None else 0.0
        else:
            self.code_open_share = float(code_open_share)
        self.sprt_alpha = float(sprt_alpha)
        self.sprt_delta = float(sprt_delta)
        self.sprt_llr: float = 0.0
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

    def _target(self) -> float:
        """Целевая точка максимальной информации: в режиме ``select_at="cut"`` после ``cut_after`` шагов
        выбирает порог заявленного/ближайшего неопределённого грейда через ``sprt.select_target_cut``.
        """
        if self.cfg.select_at == "cut" and self.n_scored >= self.cfg.cut_after:
            return select_target_cut(
                self.theta, self.se, self.claimed_grade, self.cfg.cuts, self.uncertain_cuts()
            )
        return super()._target()

    def record(self, item: PoolItem, x, log_t: float | None = None, time_s: float = 0.0) -> None:
        super().record(item, x, log_t=log_t, time_s=time_s)
        if not item.canary:
            cut = float(GRADE_CUTS.get(self.claimed_grade, 0.0))
            self.sprt_llr += step_llr(x, item.a_eff, item.b, cut, fmt=item.format, delta=self.sprt_delta)

    def is_finished(self) -> bool:
        if (
            self.n_scored >= self.cfg.min_items
            and self.cfg.stop_rule == "classification"
            and abs(self.sprt_llr) >= sprt_bound(self.sprt_alpha)
            and self.grade_determined()
        ):
            self.stop_reason = "classified"
            return True
        return super().is_finished()

    def _limit(self, cands: list[PoolItem]) -> list[PoolItem]:
        if self.max_item_time_s is not None:
            cands = [i for i in cands if i.time_limit_s <= self.max_item_time_s]
        if not self.max_per_format:
            return cands
        cnt = self.format_counts()
        out = [i for i in cands if cnt.get(i.format, 0) < self.max_per_format.get(i.format, 10**6)]
        n_long = sum(cnt.get(f, 0) for f in LONG_FORMATS)
        if n_long >= MAX_LONG_FORMATS_TOTAL:
            short_out = [i for i in out if i.format not in LONG_FORMATS]
            if short_out:
                out = short_out
        return out

    def _apply_format_quota(self, cands: list[PoolItem]) -> list[PoolItem]:
        """Применяет квоту ≥ 1/3 практических заданий (код и развёрнутые ответы) и гарантирует хотя бы одно
        развёрнутое задание в полном тесте ТОЛЬКО внутри уже отобранного яруса новизны (не вытесняя новые семейства
        виденными).
        """
        if not cands:
            return cands
        out = cands
        cnt = self.format_counts()
        if (
            self.cfg.min_items >= 8
            and self.n_scored >= 4
            and cnt.get("open_answer", 0) + cnt.get("open_book_3step", 0) == 0
            and (self.max_per_format.get("open_answer", 0) > 0 or self.max_per_format.get("open_book_3step", 0) > 0)
        ):
            open_cands = [i for i in out if i.format in ("open_answer", "open_book_3step")]
            if open_cands:
                out = open_cands
        if self.code_open_share > 0.0 and out:
            n_co = sum(v for k, v in cnt.items() if k in CODE_OPEN_FORMATS)
            out = filter_code_open_pool(out, self.n_scored, n_co, self.code_open_share)
        return out

    def _candidates(self) -> list[PoolItem]:
        base = self._limit(super()._candidates())
        if not self.seen:
            return self._apply_format_quota(base)
        # 1) новые семейства своего субпула — как прежде (кончился блок — берётся другой блок, см. CATSession._next_main);
        # 2) новые семейства других активных субпулов; 3) LRU по блокам — виденные давнее всего, с новым вариантом
        fresh = [i for i in base if i.family_id not in self.seen]
        if fresh:
            return self._apply_format_quota(fresh)
        left = self.cfg.max_time_s - self.time_used
        reserve = self._limit([i for i in self._reserve if i.family_id not in self.used and i.time_limit_s <= left])
        fresh = [i for i in reserve if i.family_id not in self.seen]
        if fresh:
            return self._apply_format_quota(fresh)
        oldest = [i for common in (True, False) for i in self._oldest([r for r in reserve if (r.block == "common") == common])]
        return self._apply_format_quota(oldest)

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
