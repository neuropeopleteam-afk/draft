#!/usr/bin/env python3
"""match-v2: миры S-M и «жёсткий», порядок продукта (ranking.order_bundles), базовые линии, метрики с ДИ.

Общая библиотека для tools/realdata/ltr_train.py (миры разработки), tools/realdata/bench2_diag.py (потолок мира)
и tools/realdata/bench_holdout2.py (один прогон на отложенных). Параметры миров — docs/realdata/bench_holdout2_PROTOCOL.md.

Миры:
  sm        — «стандартные условия, принятые в аналогичных решениях» (А15): 9 направлений (каталог-расширение включён,
              как на стенде), 70 потребностей × 900 кандидатов; тест у 100 %, только выборочная ошибка σ = SE = 0,413;
              угадывание 0,25; шум резюме: 35 % — по 4 ложных навыка, 10 % настоящих не указаны, грейд +1 у 25 %,
              −1 у 10 %; метка 0–3 по А15; формата и города у потребностей нет.
  sm_ideal  — то же, θ̂ = θ* (σ = 0) — опорная строка «идеальный тест».
  hard      — наш строгий мир (BenchConfig по умолчанию: 5 направлений, 200 × 2000, σθ 0,48, 20 % раздутых резюме,
              ФСП, «предварительные»), метка bench_world.true_relevance («capable»); формат из текста потребности убран
              (метка его не учитывает — иначе фильтр условий продукта прятал бы релевантных).
Порядок продукта — тот же код, что в подборке: need_parser.parse_need → пул как build_selection (категории потребности,
добор ступенью выше при < 30 подтверждённых, ярус «не подтверждён» по направлению) → ranking.order_bundles.

Процесс работает в одном условии: перед импортом приложения задаётся CATALOG_EXT_ENABLED (init(cond)).
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import sys
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
BACKEND = REPO / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

CONDS = ("sm", "sm_ideal", "hard")
_STATE: dict = {}

# --------------------------------------------------------------------------- 4 направления каталога-расширения (S-M)
# Навыки — из каталога-расширения (catalog/ext.py) и покрытия банка (skill_map.to_stack_tags), популярность — доля
# вакансий, где навык встречается (порядок величин как у 5 базовых направлений bench_world.POPULARITY).
EXTRA_POP = {
    "devops": {"docker": 0.9, "linux": 0.85, "kubernetes": 0.75, "ci-cd": 0.75, "monitoring": 0.55, "terraform": 0.5,
               "cloud": 0.5, "python": 0.45, "nginx": 0.45, "networking": 0.4, "ansible": 0.35, "postgresql": 0.3,
               "sre": 0.3, "helm": 0.3, "kafka": 0.2},
    "mobile": {"kotlin": 0.7, "android": 0.7, "swift": 0.55, "ios": 0.55, "git": 0.6, "rest-api": 0.5,
               "mobile-architecture": 0.5, "jetpack-compose": 0.4, "swiftui": 0.35, "react-native": 0.3,
               "flutter": 0.25, "typescript": 0.25, "sql": 0.25},
    "analyst": {"sql": 0.85, "requirements": 0.85, "bpmn": 0.6, "uml": 0.6, "user-stories": 0.55,
                "integrations": 0.45, "er-modeling": 0.4, "rest-api": 0.35, "statistics": 0.3, "test-design": 0.2,
                "kafka": 0.15},
    "data_eng": {"sql": 0.95, "python": 0.85, "etl": 0.7, "airflow": 0.65, "spark": 0.6, "postgresql": 0.55,
                 "dwh": 0.55, "clickhouse": 0.45, "kafka": 0.45, "data-quality": 0.35, "streaming": 0.3, "dbt": 0.3,
                 "greenplum": 0.2},
}
EXTRA_PHRASE = {"terraform": "Terraform", "ansible": "Ansible", "helm": "Helm", "monitoring": "мониторинг (Prometheus, Grafana)",
                "nginx": "Nginx", "sre": "SRE-практики", "networking": "сети (DNS, маршрутизация)", "cloud": "облачные платформы",
                "etl": "ETL-конвейеры", "dwh": "DWH", "dbt": "dbt", "greenplum": "Greenplum", "streaming": "потоковая обработка",
                "data-quality": "качество данных", "android": "Android SDK", "ios": "iOS SDK", "swift": "Swift",
                "jetpack-compose": "Jetpack Compose", "swiftui": "SwiftUI", "flutter": "Flutter", "react-native": "React Native",
                "mobile-architecture": "архитектура мобильных приложений", "requirements": "сбор требований", "bpmn": "BPMN",
                "uml": "UML", "user-stories": "user stories", "integrations": "интеграции и контракты API",
                "er-modeling": "ER-диаграммы"}
# Роли без двусмысленности в каталоге из 9 направлений («аналитик данных» — и data_ml, и analyst — не используется)
ROLE_SM = {
    "backend": ["бэкенд-разработчик", "backend-разработчик", "разработчик серверной части"],
    "frontend": ["фронтенд-разработчик", "frontend-разработчик", "разработчик клиентской части"],
    "data_ml": ["Data Scientist", "ML-инженер", "специалист по машинному обучению"],
    "qa": ["QA-инженер", "тестировщик", "инженер по автотестам"],
    "security": ["специалист по информационной безопасности", "инженер по кибербезопасности", "AppSec-инженер"],
    "devops": ["DevOps-инженер", "SRE-инженер", "инженер инфраструктуры"],
    "mobile": ["мобильный разработчик", "Android-разработчик", "iOS-разработчик"],
    "analyst": ["системный аналитик", "бизнес-аналитик", "аналитик требований"],
    "data_eng": ["инженер данных", "Data Engineer", "разработчик DWH"],
}
EXTRA_PROJECT = {
    "devops": ["Перевёл деплой на Kubernetes и описал инфраструктуру кодом.", "Настроил мониторинг и дежурства."],
    "mobile": ["Выпустил мобильное приложение в сторы.", "Переписал экран оплаты в мобильном банке."],
    "analyst": ["Описал процессы в BPMN и написал ТЗ на интеграцию.", "Собрал требования к личному кабинету."],
    "data_eng": ["Построил ETL-конвейер на Airflow.", "Собрал витрины данных для отчётности."],
}
EXTRA_DISC = {"devops": (("product", 0.7), ("algorithmic", 0.3)), "mobile": (("product", 0.8), ("algorithmic", 0.2)),
              "analyst": (("product", 0.8), ("algorithmic", 0.2)), "data_eng": (("algorithmic", 0.5), ("product", 0.5))}
DIRS9 = ("backend", "frontend", "data_ml", "qa", "security", "devops", "mobile", "analyst", "data_eng")

SM_PARAMS = dict(n_needs=70, n_candidates=900, theta_sigma=0.413, se_reported=0.413, guess=0.25, t0_model="claims",
                 claim_over=0.25, claim_under=0.10, claim_stuff=0.35, claim_stuff_n=(4, 4), claim_omit=0.10)


def init(cond: str) -> dict:
    """Окружение и импорт приложения для условия cond (один раз на процесс)."""
    assert cond in CONDS, cond
    if _STATE:
        assert _STATE["cond"] == cond, f"процесс уже в условии {_STATE['cond']}"
        return _STATE
    for k, v in {"DATABASE_URL": "sqlite:////tmp/a5_bench2.db", "LLM_DISABLED": "true", "DEV_MODE": "true"}.items():
        os.environ.setdefault(k, v)
    os.environ["CATALOG_EXT_ENABLED"] = "1" if cond.startswith("sm") else "0"
    os.environ.setdefault("MATCH_V2", "1")
    from app.modules.validation import bench_world as bw
    from app.modules.catalog import ext

    if cond.startswith("sm"):
        bw.POPULARITY.update(EXTRA_POP)
        bw.PROJECT.update(EXTRA_PROJECT)
        bw.DISCIPLINE_BY_DIR.update(EXTRA_DISC)
        bw.ROLE.clear()
        bw.ROLE.update(ROLE_SM)
        for t in {t for d in EXTRA_POP.values() for t in d}:
            if t not in bw.STACK and t not in bw.NEED_PHRASE:
                bw.NEED_PHRASE[t] = EXTRA_PHRASE[t]
        base_rp = bw._resume_phrase

        def _rp(tag, rng):  # навыки расширения пишутся названием или синонимом из ext.EXT_ALIASES
            if tag in bw.STACK:
                return base_rp(tag, rng)
            aliases = [a.strip() for a in ext.EXT_ALIASES.get(tag, []) if len(a.strip()) > 2]
            if aliases and rng.random() < 0.3:
                return str(aliases[int(rng.integers(len(aliases)))])
            return ext.EXT_STACK[tag][0] if tag in ext.EXT_STACK else EXTRA_PHRASE.get(tag, tag)

        bw._resume_phrase = _rp
    _STATE.update(cond=cond, bw=bw)
    return _STATE


def config(cond: str, seed: int):
    bw = init(cond)["bw"]
    if cond == "hard":
        return bw.BenchConfig(seed=seed)
    p = dict(SM_PARAMS, seed=seed, dirs=DIRS9)
    if cond == "sm_ideal":
        p["theta_sigma"] = 0.0
    return bw.BenchConfig(**p)


# --------------------------------------------------------------------------- истина
def truth_sm(need, lat) -> int:
    """Метка S-M (А15): 0 — другое направление; 1 — направление, но грейд ниже или выше больше чем на ступень,
    либо покрытие обязательных < 0,5; 2 — грейд равен или на ступень выше и покрытие ≥ 0,5; 3 — грейд равен и
    покрытие ≥ 0,75. Формат, город и вилка в метку не входят."""
    from app.modules.catalog.seed_data import GRADE_LEVEL

    if lat.direction != need.direction:
        return 0
    req = set(need.required)
    cov = len(req & set(lat.known)) / len(req) if req else 1.0
    if lat.true_grade is None:
        return 1
    diff = GRADE_LEVEL[lat.true_grade] - GRADE_LEVEL[need.grade]
    if diff == 0 and cov >= 0.75:
        return 3
    if diff in (0, 1) and cov >= 0.5:
        return 2
    return 1


def label2(need, lat) -> int:
    """Шкала 0–2 «как у соперника с nDCG 0,83» (только для сверки определений): 2 — направление, истинный грейд равен
    и знает хотя бы один обязательный навык; 1 — соседний грейд с навыком или точный без навыка; 0 — иначе."""
    from app.modules.catalog.seed_data import GRADE_LEVEL

    if lat.direction != need.direction or lat.true_grade is None:
        return 0
    has = bool(set(need.required) & set(lat.known))
    diff = abs(GRADE_LEVEL[lat.true_grade] - GRADE_LEVEL[need.grade])
    if diff == 0 and has:
        return 2
    if (diff == 1 and has) or (diff == 0 and not has):
        return 1
    return 0


@dataclass
class W2:
    cond: str
    seed: int
    cfg: object
    cands: list
    needs: list
    rel: np.ndarray       # (n, m) метка условия
    rel_l2: np.ndarray    # (n, m) шкала 0–2 (сверка определений)
    resampled: int

    def digest(self) -> str:
        h = hashlib.sha256()
        for n in self.needs:
            h.update(n.text.encode())
        for c in self.cands:
            o = c.obs
            h.update(f"{o.public_ref}|{o.grade_declared}|{o.category_grade}|{','.join(o.stack_declared)}".encode())
        h.update(self.rel.tobytes())
        return h.hexdigest()


_FMT = (" Удалённо.", " Гибрид, Москва.", " Офис в Казани.")


def _strip_format(need):
    t = need.text
    for s in _FMT:
        if t.endswith(s):
            t = t[: -len(s)]
    return replace(need, text=t, work_format=None)


def make_world(cond: str, seed: int) -> W2:
    """Детерминированно по (cond, seed). Пересэмплирование потребности — как bench_world.generate: меньше 3
    релевантных (метка ≥ 2) во всём мире — новая потребность из того же потока."""
    bw = init(cond)["bw"]
    cfg = config(cond, seed)
    blocks = bw.bank_blocks()
    cands = [bw._make_candidate(i, cfg, blocks) for i in range(cfg.n_candidates)]
    tf = truth_sm if cond.startswith("sm") else (lambda n, lat: bw.true_relevance(n, lat, cfg))
    needs, rows, rows2, resampled = [], [], [], 0
    for i in range(cfg.n_needs):
        rn = np.random.default_rng(np.random.SeedSequence([cfg.seed, 2, i]))
        for _ in range(50):
            n = _strip_format(bw._make_need(i, rn, cfg))
            row = [tf(n, c.latent) for c in cands]
            if sum(1 for r in row if r >= 2) >= cfg.min_relevant_per_need:
                break
            resampled += 1
        needs.append(n)
        rows.append(row)
        rows2.append([label2(n, c.latent) for c in cands])
    return W2(cond=cond, seed=seed, cfg=cfg, cands=cands, needs=needs, rel=np.asarray(rows, dtype=np.int8),
              rel_l2=np.asarray(rows2, dtype=np.int8), resampled=resampled)


def bundles_of(w: W2) -> list:
    bw = init(w.cond)["bw"]
    out = []
    for c in w.cands:
        b = bw.build_bundle(c.obs, "platform")
        if not b.profile.current_category_id:  # ярус «не подтверждён»: направление из опроса (как load_bundles)
            b.profile.current_direction_id = c.obs.direction_declared
        out.append(b)
    return out


# --------------------------------------------------------------------------- порядок продукта
def parse(w: W2) -> list[dict]:
    from app.modules.matching.need_parser import parse_need

    return [parse_need(n.text, use_llm=False) for n in w.needs]


def pool_for(bundles: list, req: dict) -> tuple[list[int], str | None]:
    """Индексы кандидатов пула подборки (как build_selection) и категория добора ступенью выше."""
    from app.modules.matching import grade_above
    from app.modules.catalog.seed_data import GRADES

    d, g = req.get("direction"), req.get("grade")
    if not d:
        cats = None  # направление не распознано — все категории (relation «all»)
    elif not g:
        cats = {f"{d}.{x}" for x in GRADES}
    else:
        cats = {f"{d}.{g}"}
    dirs = {c.split(".", 1)[0] for c in cats} if cats else None
    exact, unc = [], []
    for k, b in enumerate(bundles):
        cid = b.profile.current_category_id
        if cid:
            if cats is None or cid in cats:
                exact.append(k)
        elif dirs is None or b.profile.current_direction_id in dirs:
            unc.append(k)
    above_id = None
    if g and d and grade_above.enabled():
        n_exact = sum(1 for k in exact if not bundles[k].provisional)
        aid = grade_above.above_category(req)
        above = [k for k, b in enumerate(bundles) if aid and b.profile.current_category_id == aid]
        if n_exact < grade_above.MIN_EXACT and above:
            above_id = aid
            exact = exact + above
    return exact + unc, above_id


def order_v2(bundles: list, idx: list[int], req: dict, above_id: str | None, weights: dict | None = None) -> tuple[list[int], dict, list]:
    from app.modules.matching import ranking

    os.environ["MATCH_V2"] = "1"
    pos = {id(bundles[k]): k for k in idx}
    scored, info = ranking.order_bundles([bundles[k] for k in idx], req, {}, above_id=above_id, weights=weights)
    return [pos[id(x[1])] for x in scored], info, scored


def order_v13(bundles: list, idx: list[int], req: dict, above_id: str | None) -> list[int]:
    """Прежний порядок match-v1.3 (ветка else в build_selection) — строка «было»."""
    from app.modules.matching import core_skill, grade_above, must_have, ranking

    os.environ["MATCH_V2"] = "0"
    try:
        pos = {id(bundles[k]): k for k in idx}
        eff = ranking.condition_filters(req, {})
        bs = ranking.apply_filters([bundles[k] for k in idx], eff)
        scored = []
        for b in bs:
            s, comps, reasons = ranking.score_candidate(b, req, ranking.WEIGHTS)
            scored.append((s, b, comps, reasons))
        must = must_have.tiers_for([b for _, b, _, _ in scored], req, {})
        core = core_skill.assess_pool([b for _, b, _, _ in scored], req)
        if above_id:
            exact = [x for x in scored if x[1].category_id != above_id]
            must_e = must_have.tiers_for([b for _, b, _, _ in exact], req, {})
            head = [x for x in ranking.selection_order(exact, must_e, core)[:grade_above.KEEP] if ranking.tier(x[1]) == 0]
            scored = grade_above.merge(head, ranking.selection_order(scored, must, core, above_id=above_id))
        else:
            scored = ranking.selection_order(scored, must, core)
        return [pos[id(x[1])] for x in scored]
    finally:
        os.environ["MATCH_V2"] = "1"


# --------------------------------------------------------------------------- базовые линии (по всем кандидатам мира)
def _tok(text: str) -> list[str]:
    from app.modules.validation.matching_eval import _tokens

    return _tokens(text)


def baselines(w: W2, reqs: list[dict], seed: int = 7702113) -> dict[str, list[list[int]]]:
    """BM25 (k1 1,2, b 0,75) по тексту резюме; «слова + грейд» 0,6/0,4 по заявленному; TF-IDF с фильтром по
    заявленному направлению и грейду; случайный порядок. Ничьи — случайно (зерно фиксировано)."""
    from app.modules.validation.matching_bench import BM25Matrix
    from sklearn.feature_extraction.text import TfidfVectorizer

    rng = np.random.default_rng(seed + w.seed)
    m = len(w.cands)
    docs = [c.obs.resume_text for c in w.cands]
    bm = BM25Matrix(docs)
    tfv = TfidfVectorizer(analyzer=_tok, sublinear_tf=True)
    D = tfv.fit_transform(docs)
    decl_dir = np.array([c.obs.direction_declared for c in w.cands])
    decl_grade = np.array([c.obs.grade_declared for c in w.cands])
    stacks = [set(c.obs.stack_declared) for c in w.cands]
    out = {"bm25": [], "words_grade": [], "tfidf_filter": [], "random": []}
    for n, req in zip(w.needs, reqs, strict=True):
        tie = rng.random(m) * 1e-9
        s = bm.scores(n.text)
        out["bm25"].append(list(np.lexsort((tie, -s))))
        tags = [i["tag"] for i in (req.get("stack_required") or []) if i.get("tag")]
        kw = np.array([len(set(tags) & st) / len(tags) if tags else 0.0 for st in stacks])
        gr = (decl_grade == (req.get("grade") or n.grade)).astype(float)
        s2 = 0.6 * kw + 0.4 * gr
        out["words_grade"].append(list(np.lexsort((tie, -s2))))
        q = tfv.transform([n.text])
        cos = (D @ q.T).toarray().ravel()
        d = req.get("direction") or n.direction
        g = req.get("grade") or n.grade
        tier = np.where((decl_dir == d) & (decl_grade == g), 0, np.where(decl_dir == d, 1, 2))
        out["tfidf_filter"].append(list(np.lexsort((tie, -cos, tier))))
        out["random"].append(list(rng.permutation(m)))
    return out


# --------------------------------------------------------------------------- метрики
def need_metrics(rel_row: np.ndarray, ranked: list[int], over_row: np.ndarray | None = None) -> dict:
    """Метрики одной потребности по списку мест (может быть короче мира: кого нет в подборке — не показан).
    nDCG@10: выигрыш 2^метка − 1, идеал — по всем кандидатам мира (не только по выданным)."""
    r = np.asarray(ranked[:30], dtype=int)
    g = rel_row[r].astype(float) if len(r) else np.zeros(0)
    disc = 1 / np.log2(np.arange(2, 12))
    ideal = np.sort(rel_row.astype(float))[::-1][:10]
    g10 = np.zeros(10)
    g10[: min(10, len(g))] = g[:10]

    def _ndcg(gain):
        idcg = float((gain(ideal) * disc[: len(ideal)]).sum())
        return float((gain(g10) * disc).sum()) / idcg if idcg > 0 else 0.0

    hit = np.nonzero(g >= 2)[0]
    n_rel = int((rel_row >= 2).sum())
    out = {"p5": float((g[:5] >= 2).sum()) / 5, "p10": float((g[:10] >= 2).sum()) / 10,
           "ndcg10": _ndcg(lambda x: 2 ** x - 1), "ndcg10_lin": _ndcg(lambda x: x),
           "mrr": 1.0 / (hit[0] + 1) if len(hit) else 0.0, "top5_any": float(bool(len(hit) and hit[0] < 5)),
           "r30": float((g[:30] >= 2).sum()) / min(30, n_rel) if n_rel else 0.0, "shown": int(min(len(ranked), 10))}
    if over_row is not None:
        top = r[:10]
        out["over10"] = float(over_row[top].mean()) if len(top) else 0.0
    return out


def overrated(w: W2) -> np.ndarray:
    """1 — заявленный грейд выше истинного (переоценённый кандидат)."""
    from app.modules.catalog.seed_data import GRADE_LEVEL

    o = []
    for c in w.cands:
        tg = c.latent.true_grade
        o.append(1 if (tg is None or GRADE_LEVEL[c.obs.grade_declared] > GRADE_LEVEL[tg]) else 0)
    return np.asarray(o, dtype=float)


METRICS = ("p5", "p10", "ndcg10", "ndcg10_lin", "mrr", "top5_any", "r30", "over10")


def summarize(rows: list[dict]) -> dict:
    return {k: round(float(np.mean([r[k] for r in rows])), 4) for k in METRICS if rows and k in rows[0]}


def bootstrap(per_need: dict[str, list[dict]], methods: list[str], base: str = "match_v2", reps: int = 2000,
              seed: int = 7702113) -> dict:
    """Перцентильные 95 % ДИ по потребностям (выборка с возвращением) и парные разности base − метод."""
    rng = np.random.default_rng(seed)
    n = len(per_need[base])
    idx = rng.integers(0, n, size=(reps, n))
    out = {}
    for meth in methods:
        rows = per_need[meth]
        o = {}
        for k in METRICS:
            if k not in rows[0]:
                continue
            v = np.array([r[k] for r in rows])
            bs = v[idx].mean(axis=1)
            o[k] = {"mean": round(float(v.mean()), 4), "lo": round(float(np.percentile(bs, 2.5)), 4),
                    "hi": round(float(np.percentile(bs, 97.5)), 4)}
            if meth != base:
                vb = np.array([r[k] for r in per_need[base]])
                dd = (vb - v)[idx].mean(axis=1)
                o[k]["diff_vs_" + base] = {"mean": round(float((vb - v).mean()), 4),
                                           "lo": round(float(np.percentile(dd, 2.5)), 4),
                                           "hi": round(float(np.percentile(dd, 97.5)), 4)}
        out[meth] = o
    return out


def sha256_file(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def evaluate_world(w: W2, *, weights: dict | None = None, with_v13: bool = True, with_baselines: bool = True,
                   label: str = "rel") -> dict:
    """Все методы на одном мире: {метод: [метрики по потребностям]} + сведения о подборке."""
    bundles = bundles_of(w)
    reqs = parse(w)
    rel = w.rel if label == "rel" else w.rel_l2
    over = overrated(w)
    per = {"match_v2": [], "oracle_pool": []}
    if with_v13:
        per["match_v13"] = []
    info_rows = []
    for i, (n, req) in enumerate(zip(w.needs, reqs, strict=True)):
        idx, above_id = pool_for(bundles, req)
        order, info, _ = order_v2(bundles, idx, req, above_id, weights=weights)
        per["match_v2"].append(need_metrics(rel[i], order, over))
        # оракул пула: та же подборка (после фильтров), но по истинной метке — потолок порядка внутри подборки
        orc = sorted(order, key=lambda k: -int(rel[i][k]))
        per["oracle_pool"].append(need_metrics(rel[i], orc, over))
        if with_v13:
            per["match_v13"].append(need_metrics(rel[i], order_v13(bundles, idx, req, above_id), over))
        info_rows.append({"pool": len(idx), "shown": len(order), "above": bool(above_id),
                          "dir_ok": req.get("direction") == n.direction, "grade_ok": req.get("grade") == n.grade,
                          "stack_thr": (info.get("stack_filter") or {}).get("threshold"),
                          "rel_world": int((rel[i] >= 2).sum()), "rel_pool": int(sum(1 for k in idx if rel[i][k] >= 2)),
                          "rel_shown": int(sum(1 for k in order if rel[i][k] >= 2))})
    if with_baselines:
        for meth, orders in baselines(w, reqs).items():
            per[meth] = [need_metrics(rel[i], o, over) for i, o in enumerate(orders)]
    return {"per_need": per, "info": info_rows, "digest": w.digest(), "resampled": w.resampled,
            "n": len(w.needs), "m": len(w.cands)}


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--cond", required=True, choices=CONDS)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--label", default="rel", choices=("rel", "l2"))
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    init(a.cond)
    w = make_world(a.cond, a.seed)
    res = evaluate_world(w, label=a.label)
    res["summary"] = {k: summarize(v) for k, v in res["per_need"].items()}
    Path(a.out).write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"cond": a.cond, "seed": a.seed, "digest": res["digest"][:16], **{k: v for k, v in res["summary"].items()}},
                     ensure_ascii=False, indent=1))
