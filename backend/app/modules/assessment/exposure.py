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

import numpy as np

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
    guess_parts,
    llr3,
    select_target_cut,
    sprt_bound,
    sprt_bounds,
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
                 sprt_delta: float = DEFAULT_DELTA, sprt: dict | None = None, guess: dict | None = None,
                 randomesque_k: int = 0, **kwargs):
        self.randomesque_k = int(randomesque_k or 0)
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
        # Поправка №2 (21.10 вечер): sprt — {"alpha", "beta", "delta", "soft_max_items", "soft_max_time_s",
        # "time_weight", "actual_k"}; None — прежние правила выбора, остановки и угадывания (c = 1/4)
        self.sprt = dict(sprt) if sprt else None
        if self.sprt:
            self.sprt_alpha = float(self.sprt.get("alpha", self.sprt_alpha))
            self.sprt_delta = float(self.sprt.get("delta", self.sprt_delta))
        self.guess = {str(k): np.asarray(v, dtype=float) for k, v in (guess or {}).items()}
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

    # --- поправка №2: SPRT у заявленного порога ----------------------------------------------------------------
    def claim_status(self) -> str:
        """Решение SPRT по заявленному грейду на текущий момент: confirmed | not_confirmed | needs_followup."""
        up, lo = sprt_bounds(self.sprt_alpha, float((self.sprt or {}).get("beta", self.sprt_alpha)))
        if self.sprt_llr >= up:
            return "confirmed"
        if self.sprt_llr <= lo:
            return "not_confirmed"
        return "needs_followup"

    def claim_cut(self) -> float:
        return float(GRADE_CUTS.get(self.claimed_grade, 0.0))

    def other_uncertain(self) -> list[float]:
        """Неопределённые пороги (θ̂ ± z·SE), кроме заявленного, когда по нему SPRT уже решил."""
        unc = self.uncertain_cuts()
        if self.claim_status() != "needs_followup":
            unc = [c for c in unc if abs(c - self.claim_cut()) > 1e-9]
        return unc

    def _target(self) -> float:
        """Целевая точка максимальной информации: в режиме ``select_at="cut"`` после ``cut_after`` шагов
        выбирает порог заявленного/ближайшего неопределённого грейда через ``sprt.select_target_cut``.
        Поправка №2: пока SPRT по заявленному грейду не решил — его порог; затем — ближайший неопределённый порог
        («уровень по ответам»), иначе — текущая оценка.
        """
        if self.sprt and self.cfg.select_at == "cut" and self.n_scored >= self.cfg.cut_after:
            if self.claim_status() == "needs_followup":
                return self.claim_cut()
            unc = self.other_uncertain()
            return unc[0] if unc else self.theta
        if self.cfg.select_at == "cut" and self.n_scored >= self.cfg.cut_after:
            return select_target_cut(
                self.theta, self.se, self.claimed_grade, self.cfg.cuts, self.uncertain_cuts()
            )
        return super()._target()

    def record(self, item: PoolItem, x, log_t: float | None = None, time_s: float = 0.0) -> None:
        super().record(item, x, log_t=log_t, time_s=time_s)
        if not item.canary:
            cut = float(GRADE_CUTS.get(self.claimed_grade, 0.0))
            if self.sprt:
                xs = np.asarray(list(x), dtype=float)
                self.sprt_llr += llr3(xs, item.a_eff, item.b, self._guess_c(item), cut, self.sprt_delta)
            else:
                self.sprt_llr += step_llr(x, item.a_eff, item.b, cut, fmt=item.format, delta=self.sprt_delta)

    def is_finished(self) -> bool:
        if self.sprt:
            return self._finished_sprt()
        if (
            self.n_scored >= self.cfg.min_items
            and self.cfg.stop_rule == "classification"
            and abs(self.sprt_llr) >= sprt_bound(self.sprt_alpha)
            and self.grade_determined()
        ):
            self.stop_reason = "classified"
            return True
        return super().is_finished()

    def _finished_sprt(self) -> bool:
        """Остановка основной части (поправка №2). Жёсткие пределы — cfg.max_items / cfg.max_time_s (продление у
        спорного порога, до 30 заданий / 90 минут); обычные — soft_max_items / soft_max_time_s: после них тест идёт
        дальше, только пока SPRT по заявленному грейду не решил. Досрочно — когда решение принято и «уровень по
        ответам» определён (ни один другой порог не внутри θ̂ ± z·SE), но не раньше min_items."""
        c, n = self.cfg, self.n_scored
        soft_n = int(self.sprt.get("soft_max_items", c.max_items))
        soft_t = float(self.sprt.get("soft_max_time_s", c.max_time_s))
        undecided = self.claim_status() == "needs_followup"
        if n >= c.max_items:
            self.stop_reason = "max_items"
            return True
        if self.time_used >= c.max_time_s:
            self.stop_reason = "time"
            return True
        if (n >= soft_n or self.time_used >= soft_t) and not undecided:
            self.stop_reason = "max_items" if n >= soft_n else "time"
            return True
        if n >= c.min_items and not undecided and not self.other_uncertain():
            self.stop_reason = "classified"
            return True
        if not self._candidates():
            self.stop_reason = "pool_exhausted"
            return True
        return False

    def _score(self, item: PoolItem, target: float) -> float:
        """Поправка №2: информация 3PL (с угадыванием этого задания) в целевой точке на единицу ожидаемого времени
        в степени time_weight; без поправки — как в CATSession (2PL, time_weight из конфигурации)."""
        if not self.sprt or (self.cfg.partial_credit and self.cfg.partial_credit_select):
            return super()._score(item, target)
        a = np.asarray(item.a_eff, dtype=float)
        b = np.asarray(item.b, dtype=float)
        cc = self._guess_c(item)
        sg = 1.0 / (1.0 + np.exp(-np.clip(a * (target - b), -30, 30)))
        p = np.clip(cc + (1 - cc) * sg, 1e-9, 1 - 1e-9)
        d = (1 - cc) * a * sg * (1 - sg)
        info = float(np.sum(d * d / (p * (1 - p))))
        w = float(self.sprt.get("time_weight", 0.0))
        if w:
            info /= (float(np.exp(item.beta_time)) / 120.0) ** w
        return info

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

    def _pick(self, cands: list[PoolItem], target: float) -> PoolItem:
        """Правило v2 (TRAIN): randomesque — случайное из k лучших по информации (на минуту) у целевой точки.
        Контроль частоты показа без таблицы K_f: при k ≥ 2 ни одно задание не выдаётся детерминированно.
        В остальных режимах — прежний выбор (Симпсон — Хеттер или лучшее)."""
        k = self.randomesque_k
        if k >= 2 and cands:
            top = sorted(cands, key=lambda i: -self._score(i, target))[:k]
            return top[int(self.rng.integers(len(top)))]
        return super()._pick(cands, target)

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

    # --- А4 (21.10): угадывание в вопросах с выбором ответа (3PL с известным c = 1/K) -----------------------------
    # Банк задаёт части 2PL без угадывания, а у 621 семейства вопросов с выбором априорная различающая сила a = 3,0.
    # Тогда несколько удачных угадываний подряд у границы дают уверенное «подтверждён»: бот со случайными ответами
    # получал подтверждение Junior (боты через движок, cheat_bots.py). Оценка уровня с угадыванием c = 1/K для частей с
    # выбором варианта (K = 4 — минимальное число вариантов банка; код, строка, вывод и текст — c = 0) убирает этот
    # эффект и честнее для людей (они тоже угадывают). Настройка ASSESSMENT_GUESSING_3PL.
    _OPTION_PART_FORMATS = {"mcq_concept": None, "choose_fix": None, "open_book_3step": (0, 1), "incident_sim": (0, 1)}

    def _guess_c(self, it: PoolItem) -> np.ndarray:
        n = len(np.atleast_1d(it.b))
        if self.sprt and self.sprt.get("actual_k"):
            g = self.guess.get(it.family_id)
            if g is None:
                g = family_guess(it.family_id, it.format, n)
                self.guess[it.family_id] = g
            return g
        c = np.zeros(n)
        parts = self._OPTION_PART_FORMATS.get(it.format, ())
        if parts is None:
            c[:] = 0.25
        else:
            for j in parts:
                if j < n:
                    c[j] = 0.25
        return c

    def _estimate(self, exclude: set[int] | None = None, prior_mean: float = 0.0, prior_sd: float | None = None):
        if self.cfg.partial_credit or not _guessing_on():
            return super()._estimate(exclude, prior_mean=prior_mean, prior_sd=prior_sd)
        from assessment_bank.psychometrics.irt import GRID, ThetaEstimate
        from scipy import stats

        sd = self.cfg.prior_sd if prior_sd is None else prior_sd
        xs, aa, bb, cc = [], [], [], []
        for k, adm in enumerate(self.administered):
            if adm.canary or (exclude and k in exclude):
                continue
            it = self.items[adm.family_id]
            xs.append(np.asarray(adm.x, dtype=float))
            aa.append(np.asarray(it.a_eff, dtype=float))
            bb.append(np.asarray(it.b, dtype=float))
            cc.append(self._guess_c(it))
        if not xs:
            return ThetaEstimate(prior_mean, sd, "eap", 0)
        x, a, b, c = (np.concatenate(v) for v in (xs, aa, bb, cc))
        m = ~np.isnan(x)
        x, a, b, c = x[m], a[m], b[m], c[m]
        if not len(x):
            return ThetaEstimate(prior_mean, sd, "eap", 0)
        p = c[None, :] + (1.0 - c[None, :]) / (1.0 + np.exp(-np.clip(a[None, :] * (GRID[:, None] - b[None, :]), -30, 30)))
        p = np.clip(p, 1e-12, 1 - 1e-12)
        lp = (x[None, :] * np.log(p) + (1.0 - x[None, :]) * np.log1p(-p)).sum(axis=1) + stats.norm.logpdf(GRID, prior_mean, sd)
        w = np.exp(lp - lp.max())
        w /= w.sum()
        mu = float(np.dot(w, GRID))
        return ThetaEstimate(mu, float(np.sqrt(np.dot(w, (GRID - mu) ** 2))), "eap", int(len(x)))

    def _ext_candidates(self) -> list[PoolItem]:
        return self._ext_quota(self._ext_candidates_raw())

    def _ext_candidates_raw(self) -> list[PoolItem]:
        base = self._limit(super()._ext_candidates())
        if not self.seen:
            return base
        fresh = [i for i in base if i.family_id not in self.seen]
        if fresh:
            return fresh
        # LRU в дотестировании у порога — без семейств последней попытки (как прежде: они в дотестирование не
        # попадали); дотестирование предварительного Junior (confirm) — LRU по всем, чтобы не кончилось без заданий
        return self._oldest(base if self.ext_lru else [i for i in base if self.seen.get(i.family_id, 0) >= 1])

    def _ext_quota(self, cands: list[PoolItem]) -> list[PoolItem]:
        """Квота практических заданий (код и развёрнутые ответы с автопроверкой) и в дотестировании у порога и во
        втором этапе — по всей сессии, а не только в основной части (настройка ASSESSMENT_CODE_QUOTA_EXT).
        Без неё дотестирование шло одними вопросами с выбором ответа и доля практических падала до ~20 %."""
        if not cands or self.code_open_share <= 0.0 or not _ext_quota_on():
            return cands
        cnt = self.format_counts()
        n_co = sum(v for k, v in cnt.items() if k in CODE_OPEN_FORMATS)
        return filter_code_open_pool(cands, self.n_scored, n_co, self.code_open_share)

    def _oldest(self, cands: list[PoolItem]) -> list[PoolItem]:
        """LRU: из виденных кандидатом семейств — те, что он видел давнее всего (наибольший «возраст»)."""
        old = [i for i in cands if i.family_id in self.seen]
        if not old:
            return []
        m = max(self.seen[i.family_id] for i in old)
        return [i for i in old if self.seen[i.family_id] == m]


@lru_cache(maxsize=8192)
def _family_guess_t(fid: str, fmt: str, n_parts: int) -> tuple[float, ...]:
    """Угадывание по частям для семейства до выдачи: число вариантов шага и строк кода — по варианту с фиксированным
    зерном (у семейства они от варианта не зависят); ошибка генерации — c = 1/4 у частей с выбором."""
    from app.modules.assessment.sprt import public_guess

    try:
        from assessment_bank import generate

        pv = generate(fid, 1).public_view()
        pub = {"options": pv.get("options") or [], "code": pv.get("code"),
               "code_lines": len((pv.get("code") or "").splitlines())}
        return tuple(float(v) for v in public_guess(fmt, n_parts, pub, actual=True))
    except Exception:  # noqa: BLE001
        return tuple(float(v) for v in guess_parts(fmt, n_parts, None, None, actual=False))


def family_guess(fid: str, fmt: str, n_parts: int) -> np.ndarray:
    return np.asarray(_family_guess_t(fid, fmt, int(n_parts)), dtype=float)


def _guessing_on() -> bool:
    from app.core.config import get_settings

    return bool(getattr(get_settings(), "assessment_guessing_3pl", False))


def _ext_quota_on() -> bool:
    from app.core.config import get_settings

    return bool(getattr(get_settings(), "assessment_code_quota_ext", False))


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
