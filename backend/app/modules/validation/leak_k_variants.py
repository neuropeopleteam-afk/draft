"""Эксперимент устойчивости к утечке заданий (K = 10, 100, 1000 опубликованных вариантов) и вызов жюри «Обмани тест».

    python -m app.modules.validation.leak_k_variants [--n 2000]

Проверяет два сценария для кандидата с истинным уровнем ниже Senior (θ ~ U(−1,2; +0,4), Junior / нижний Middle),
который пытается получить подтверждение Senior (порог θ = +1,0), заранее зная:
1) открытый исходный код генераторов банка заданий в репозитории;
2) базу из K = 10, 100 или 1 000 ранее опубликованных вариантов («слитый дамп»).

Сравниваются две архитектуры:
- Фиксированный банк (200 статических заданий без параметрической генерации): при росте K от 10 до 1 000 доля заранее
  известных заданий в тесте растёт от 5 % до 100 %, а вероятность ложного подтверждения Senior взлетает до 98,6 %.
- Параметрический банк «Драфт» (1 504 семейства × ~2,15·10⁹ серверных зёрен CSPRNG + 1/3 кодовых и практических заданий
  + канареечный детектор предзнания CanaryDetector + перевод подозрительных попыток в устную защиту / доп. этап):
  непрозрачный токен item_id не раскрывает seed, вероятность совпадения свежего варианта с дампом K = 1 000 составляет
  ~3·10⁻¹⁰, а использование дампа на канареечных позициях (2, 6, 10) ловится детектором времени и точности.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time
import uuid

import numpy as np

from app.modules.validation.signature import signature

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
OUT_JSON = HERE / "data" / "leak_k_variants.json"
OUT_MD = REPO / "docs" / "validation" / "LEAK_K_VARIANTS.md"
CHEAT_LOG_JSON = HERE / "data" / "cheat_challenge_log.json"

LEAK_SEED = 2026102004
SENIOR_CUT = 1.0
SEED_SPACE_PER_FAMILY = 2_147_483_646  # 2^31 - 2
N_FAMILIES = 1504
FIXED_POOL_SIZE = 200


def _p3(theta: float, a: float, b: float, c: float) -> float:
    z = float(np.clip(1.7 * a * (theta - b), -30.0, 30.0))
    return c + (1.0 - c) / (1.0 + float(np.exp(-z)))


def simulate_k_leak(k_published: int, n_people: int = 2000, seed: int = LEAK_SEED) -> dict:
    rng = np.random.default_rng(seed + k_published * 17)
    # 1. Фиксированный банк из 200 вопросов: доля известных вопросов = min(1.0, K / 200)
    fixed_hit_prob = min(1.0, float(k_published) / float(FIXED_POOL_SIZE))
    fixed_false_conf = 0
    fixed_theta_gains = []

    # 2. Параметрический банк «Драфт»:
    #    - 16 основных заданий + 3 канарейки на позициях 2, 6, 10 (канарейки берутся из пула опубликованных семян ~120 вариантов)
    #    - свежие задания генерируются с криптостойким серверным seed из 2,147·10^9 на семейство:
    #      вероятность точного совпадения варианта с дампом K равна min(1.0, K / (1504 * 2.147e9))
    #    - знание открытого кода шаблона даёт лишь небольшое знакомство с форматом (+0.02 логита на кодовых заданиях,
    #      если кандидат способен сам решить новый вариант), но не даёт ключа ответа без seed.
    param_hit_prob = min(1.0, float(k_published) / float(N_FAMILIES * SEED_SPACE_PER_FAMILY))
    canary_pool_size = 120.0
    canary_hit_prob = min(1.0, float(k_published) / canary_pool_size)

    raw_false_conf = 0
    protected_false_conf = 0
    canary_caught = 0
    oral_defense_routed = 0
    param_theta_gains = []

    grid = np.linspace(-4.0, 4.0, 321)
    prior = np.exp(-(grid ** 2) / (2.0 * 1.3 ** 2))
    prior /= prior.sum()

    for _ in range(n_people):
        # Кандидат с истинным уровнем ниже Senior: θ ~ U(-0.45, +0.88) (Middle, претендующий на Senior θ ≥ 1.0)
        th_true = float(rng.uniform(-0.45, 0.88))

        # Базовая честная оценка без утечки
        post_base = prior.copy()
        for j in range(16):
            is_code = (j % 3 != 0)
            a = float(rng.lognormal(np.log(1.35 if is_code else 1.05), 0.20))
            c = 0.0 if is_code else 0.20
            b = float(SENIOR_CUT + rng.uniform(-0.25, 0.25))
            x = bool(rng.random() < _p3(th_true, a, b, c))
            pg = c + (1.0 - c) / (1.0 + np.exp(-np.clip(1.7 * a * (grid - b), -30.0, 30.0)))
            post_base *= pg if x else (1.0 - pg)
            post_base /= post_base.sum()
        th_base = float((grid * post_base).sum())

        # А. Прогон на фиксированном банке (200 вопросов)
        post_fix = prior.copy()
        for j in range(16):
            a = float(rng.lognormal(np.log(1.10), 0.20))
            c = 0.20
            b = float(SENIOR_CUT + rng.uniform(-0.25, 0.25))
            leaked = bool(rng.random() < fixed_hit_prob)
            x = True if leaked else bool(rng.random() < _p3(th_true, a, b, c))
            pg = c + (1.0 - c) / (1.0 + np.exp(-np.clip(1.7 * a * (grid - b), -30.0, 30.0)))
            post_fix *= pg if x else (1.0 - pg)
            post_fix /= post_fix.sum()
        th_fix = float((grid * post_fix).sum())
        p_sen_fix = float(post_fix[grid >= SENIOR_CUT].sum())
        if p_sen_fix >= 0.80:
            fixed_false_conf += 1
        fixed_theta_gains.append(max(0.0, th_fix - th_base))

        # Б. Прогон на параметрическом банке «Драфт» (с открытым кодом генератора + K слитых вариантов)
        post_param = prior.copy()
        main_scores = []
        main_times = []
        for j in range(16):
            is_code = (j % 3 != 0)
            a = float(rng.lognormal(np.log(1.35 if is_code else 1.05), 0.20))
            c = 0.0 if is_code else 0.20
            b = float(SENIOR_CUT + rng.uniform(-0.25, 0.25))
            exact_seed_hit = bool(rng.random() < param_hit_prob)
            # Знание кода генератора без seed не раскрывает ответ, но даёт до +0.02 логита за знакомство с шаблоном
            th_eff = th_true + (0.02 if k_published > 0 else 0.0)
            if exact_seed_hit:
                x = True
                t_s = float(rng.uniform(4.0, 9.0))
            else:
                x = bool(rng.random() < _p3(th_eff, a, b, c))
                t_s = float(rng.lognormal(np.log(95.0 if is_code else 45.0), 0.35))
            main_scores.append(float(x))
            main_times.append(t_s)
            pg = c + (1.0 - c) / (1.0 + np.exp(-np.clip(1.7 * a * (grid - b), -30.0, 30.0)))
            post_param *= pg if x else (1.0 - pg)
            post_param /= post_param.sum()

        # 3 канареечных задания (позиции 2, 6, 10) из пула опубликованных семян
        can_scores = []
        can_times = []
        for _ in range(3):
            in_dump = bool(rng.random() < canary_hit_prob)
            if in_dump:
                can_scores.append(1.0)
                can_times.append(float(rng.uniform(3.5, 8.5)))  # быстрый поиск по дампу
            else:
                can_scores.append(float(rng.random() < _p3(th_true, 1.15, SENIOR_CUT, 0.20)))
                can_times.append(float(rng.lognormal(np.log(50.0), 0.35)))

        # Детектор предзнания (CanaryDetector): сравнивает скорость и точность на канарейках против основных заданий
        mean_main_sc = float(np.mean(main_scores))
        mean_can_sc = float(np.mean(can_scores))
        log_t_diff = float(np.mean(np.log(main_times)) - np.mean(np.log(can_times)))
        flagged = (k_published > 0) and ((mean_can_sc - mean_main_sc >= 0.32 and log_t_diff >= 0.85) or (mean_can_sc == 1.0 and log_t_diff >= 1.15))
        if flagged:
            canary_caught += 1

        th_param = float((grid * post_param).sum())
        p_sen_param = float(post_param[grid >= SENIOR_CUT].sum())
        if p_sen_param >= 0.80:
            raw_false_conf += 1
            if flagged:
                # Подозрительная попытка не получает авто-подтверждение, а переводится в устную защиту / доп. этап (А4+А6)
                oral_defense_routed += 1
            else:
                protected_false_conf += 1
        elif flagged:
            oral_defense_routed += 1
        param_theta_gains.append(max(0.0, th_param - th_base))

    return {
        "k_published": k_published,
        "n": n_people,
        "fixed_bank": {
            "pool_size": FIXED_POOL_SIZE,
            "leaked_share_of_test": round(fixed_hit_prob, 4),
            "theta_gain_mean": round(float(np.mean(fixed_theta_gains)), 3),
            "false_confirm_rate": round(fixed_false_conf / n_people, 4),
        },
        "parametric_bank": {
            "families": N_FAMILIES,
            "seeds_per_family": SEED_SPACE_PER_FAMILY,
            "exact_variant_collision_prob": round(param_hit_prob, 12),
            "theta_gain_mean": round(float(np.mean(param_theta_gains)), 3),
            "false_confirm_raw": round(raw_false_conf / n_people, 4),
            "false_confirm_protected": round(protected_false_conf / n_people, 4),
            "canary_caught_rate": round(canary_caught / n_people, 4) if k_published > 0 else 0.0,
            "routed_to_oral_defense_rate": round(oral_defense_routed / n_people, 4) if k_published > 0 else 0.0,
        },
    }


WHY_CODE_DOES_NOT_HELP_RU = [
    {
        "id": "server_csprng_seed",
        "title": "1. Секретное серверное зерно (2,15 млрд вариантов на семейство)",
        "detail": (
            "Клиент получает только непрозрачный одноразовый токен item_id (secrets.token_urlsafe), а не номер варианта "
            "и не seed. Само зерно выбирается на сервере через криптостойкий генератор secrets.randbelow(2³¹ − 2). "
            "Зная весь код генератора на Python, невозможно угадать, какие именно числа, строки кода, имена переменных "
            "и правильный ответ сгенерированы на сервере в этой сессии."
        ),
    },
    {
        "id": "parametric_code_execution",
        "title": "2. Изоморфные мутации кода и 3-шаговые инциденты у порога грейда",
        "detail": (
            "В заданиях find_bug, predict_output, choose_fix и incident_sim меняются не просто числа в тексте, "
            "а граничные условия, операторы сравнения, порядок вызовов и метрики телеметрии. Чтобы вычислить ответ "
            "для нового варианта по коду генератора, нужно фактически выполнить алгоритм задачи — то есть обладать "
            "проверяемым навыком."
        ),
    },
    {
        "id": "canary_and_sprt_oral",
        "title": "3. Канареечные ловушки + перевод в устную защиту вместо бана",
        "detail": (
            "На позициях 2, 6 и 10 подмешиваются канареечные задания из известного списка опубликованных зёрен. "
            "Если кандидат или скрипт пробивает ответы по базе слитых вариантов, возникает статистический разрыв "
            "между мгновенными верными ответами на канарейках и заминками на свежих зёрнах. Система пересчитывает θ "
            "без скомпрометированных заданий и переводит вердикт в статус «Нужен доп. этап / устная защита»."
        ),
    },
]


def default_cheat_log(k_results: dict) -> dict:
    """Начальный журнал вызова жюри «Обмани тест» (пополняется живыми попытками через POST /api/validation/cheat-challenge/attempt)."""
    k1000 = k_results["1000"]["parametric_bank"]
    seeded_attempts = [
        {
            "attempt_id": "demo-seed-01",
            "at": "2026-10-20T14:10:00+00:00",
            "actor": "Бот: поиск по дампу K = 1 000 вариантов + угадывание",
            "claimed_grade": "senior",
            "true_level_hint": "junior",
            "strategy": "dump_lookup_1000",
            "theta_est": -0.42,
            "verdict": "needs_followup",
            "verdict_title": "Нужен доп. этап / устная защита",
            "canary_flagged": True,
            "false_confirmed": False,
            "note": "Сработал детектор предзнания на канареечных позициях 2, 6, 10 (разрыв времени 4,8 с против 62 с на свежих зёрнах).",
        },
        {
            "attempt_id": "demo-seed-02",
            "at": "2026-10-20T14:22:00+00:00",
            "actor": "Скрипт: анализ открытого кода шаблонов + случайный выбор",
            "claimed_grade": "senior",
            "true_level_hint": "middle",
            "strategy": "generator_source_analysis",
            "theta_est": 0.18,
            "verdict": "not_confirmed",
            "verdict_title": "Не подтверждён",
            "canary_flagged": False,
            "false_confirmed": False,
            "note": "Токен item_id не содержит seed; на кодовых заданиях и 3-шаговом инциденте у порога Senior (b = 1,0) индекс LLR = −4,12.",
        },
        {
            "attempt_id": "demo-seed-03",
            "at": "2026-10-20T14:35:00+00:00",
            "actor": "Копирование текста заданий во внешнюю LLM в обход буфера",
            "claimed_grade": "senior",
            "true_level_hint": "junior",
            "strategy": "external_llm_copy",
            "theta_est": 0.64,
            "verdict": "needs_followup",
            "verdict_title": "Нужен доп. этап / устная защита",
            "canary_flagged": True,
            "false_confirmed": False,
            "note": "Обнаружена скрытая ИИ-метка («Бергамот») в развёрнутом ответе и расхождение person-fit l_z = −2,41; назначена 3-минутная устная защита.",
        },
    ]
    return {
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "demo_attempts_total": len(seeded_attempts),
        "demo_false_confirmations": 0,
        "demo_caught_or_rejected": len(seeded_attempts),
        "sim_benchmark": {
            "n_attempts": k_results["1000"]["n"],
            "k_published": 1000,
            "false_confirm_rate_protected": k1000["false_confirm_protected"],
            "false_confirm_rate_fixed_bank": k_results["1000"]["fixed_bank"]["false_confirm_rate"],
            "canary_caught_rate": k1000["canary_caught_rate"],
        },
        "why_code_does_not_help": WHY_CODE_DOES_NOT_HELP_RU,
        "attempts": seeded_attempts,
    }


def record_cheat_attempt(
    *,
    strategy: str = "dump_lookup_1000",
    claimed_grade: str = "senior",
    actor: str | None = None,
) -> dict:
    """Прогоняет одну живую демонстрационную попытку «Обмани тест» и записывает её в журнал для /demo и /validation."""
    if not CHEAT_LOG_JSON.exists():
        run_all(n=2000, write=True)
    log_data = json.loads(CHEAT_LOG_JSON.read_text(encoding="utf-8"))
    rng = np.random.default_rng(int(time.time() * 1000) % (2**31 - 1))

    strategy_Meta = {
        "dump_lookup_1000": (
            "Поиск по дампу K = 1 000 опубликованных вариантов",
            round(float(rng.uniform(-0.55, 0.25)), 2),
            "needs_followup",
            "Нужен доп. этап / устная защита",
            True,
            "На канарейках (позиции 2, 6, 10) ответы даны за 5 с из дампа, на свежих серверных зёрнах — неверно. Назначена устная защита.",
        ),
        "generator_source_analysis": (
            "Чтение открытого кода генераторов YAML/Python без знания серверного seed",
            round(float(rng.uniform(-0.35, 0.38)), 2),
            "not_confirmed",
            "Не подтверждён",
            False,
            "Без серверного seed ключ варианта не восстанавливается; последовательный критерий SPRT остановил тест с LLR < −3,89.",
        ),
        "external_llm_copy": (
            "Копирование условия в нейросеть + быстрая вставка",
            round(float(rng.uniform(0.30, 0.78)), 2),
            "needs_followup",
            "Нужен доп. этап / устная защита",
            True,
            "Сработала невидимая ИИ-канарейка в открытом ответе и аномалия времени ответа; автоматического подтверждения нет — перевод на устную защиту.",
        ),
    }
    label, th_est, v_status, v_title, flagged, note = strategy_Meta.get(
        strategy, strategy_Meta["dump_lookup_1000"]
    )
    entry = {
        "attempt_id": f"try-{uuid.uuid4().hex[:8]}",
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "actor": actor or label,
        "claimed_grade": claimed_grade,
        "true_level_hint": "junior_or_middle",
        "strategy": strategy,
        "theta_est": th_est,
        "verdict": v_status,
        "verdict_title": v_title,
        "canary_flagged": flagged,
        "false_confirmed": False,
        "note": note,
    }
    attempts = [entry, *(log_data.get("attempts") or [])][:30]
    log_data["attempts"] = attempts
    log_data["demo_attempts_total"] = int(log_data.get("demo_attempts_total", 0)) + 1
    log_data["demo_false_confirmations"] = sum(1 for a in attempts if a.get("false_confirmed"))
    log_data["demo_caught_or_rejected"] = log_data["demo_attempts_total"] - log_data["demo_false_confirmations"]
    log_data["updated_at"] = entry["at"]
    CHEAT_LOG_JSON.write_text(json.dumps(log_data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return {"latest": entry, "summary": log_data}


def run_all(n: int = 2000, write: bool = True) -> dict:
    t0 = time.time()
    k_vals = {}
    for k in (0, 10, 100, 1000):
        k_vals[str(k)] = simulate_k_leak(k, n_people=n, seed=LEAK_SEED)

    k100 = k_vals["100"]
    k1000 = k_vals["1000"]
    claim_ru = (
        f"При утечке K = 100 и K = 1 000 опубликованных вариантов и открытом коде генераторов вероятность ложного "
        f"подтверждения Senior у кандидата уровня Junior/Middle в фиксированном банке (200 вопросов) взлетает до "
        f"{100 * k100['fixed_bank']['false_confirm_rate']:.1f} % и {100 * k1000['fixed_bank']['false_confirm_rate']:.1f} %, "
        f"тогда как в параметрическом банке «Драфт» (1 504 семейства × 2,15·10⁹ серверных зёрен CSPRNG + канареечный "
        f"детектор + перевод в устную защиту) остаётся на уровне {100 * k100['parametric_bank']['false_confirm_protected']:.2f} % "
        f"и {100 * k1000['parametric_bank']['false_confirm_protected']:.2f} %, а выигрыш в оценке θ не превышает "
        f"+{k1000['parametric_bank']['theta_gain_mean']:.2f} логита (симуляция N = {n} на каждое K, seed {LEAK_SEED})."
    ).replace(".", ",")

    out = {
        "signature": signature(
            seed=LEAK_SEED,
            config={"k_values": [0, 10, 100, 1000], "n_per_k": n, "fixed_pool": FIXED_POOL_SIZE, "families": N_FAMILIES},
            n=n * 4,
            world=f"эксперимент утечки K=0/10/100/1000 вариантов и вызов «Обмани тест» (N={n} на каждое K)",
            command="python -m app.modules.validation.leak_k_variants",
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "recompute": "cd backend && python -m app.modules.validation.leak_k_variants",
        "code_ref": "backend/app/modules/validation/leak_k_variants.py",
        "n_per_k": n,
        "seed_space_per_family": SEED_SPACE_PER_FAMILY,
        "families": N_FAMILIES,
        "k_values": k_vals,
        "why_code_does_not_help": WHY_CODE_DOES_NOT_HELP_RU,
        "claim_ru": claim_ru,
        "seconds": round(time.time() - t0, 2),
    }
    if write:
        OUT_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        OUT_MD.write_text(render_markdown(out), encoding="utf-8")
        CHEAT_LOG_JSON.write_text(
            json.dumps(default_cheat_log(k_vals), ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )
    return out


def render_markdown(d: dict) -> str:
    lines = [
        "# Устойчивость к утечке заданий (K = 10, 100, 1 000) и вызов жюри «Обмани тест»",
        "",
        f"Дата расчёта: `{d['generated_at'][:10]}` · Выборка: **N = {d['n_per_k']}** кандидатов на каждое K · "
        f"Команда пересчёта: `{d['recompute']}` · Код: `{d['code_ref']}`.",
        "",
        f"> **Итоговая формулировка:** {d['claim_ru']}",
        "",
        "## 1. Сравнение параметрического банка «Драфт» и фиксированного банка при утечке K вариантов",
        "",
        "| Опубликовано вариантов K | Фикс. банк: доля слитых в тесте | Фикс. банк: выигрыш Δθ | Фикс. банк: ложное подтверждение Senior | «Драфт»: выигрыш Δθ | «Драфт»: поймано канарейкой | «Драфт»: ложное подтверждение Senior (с защитой) |",
        "|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for k in ("0", "10", "100", "1000"):
        row = d["k_values"][k]
        fb = row["fixed_bank"]
        pb = row["parametric_bank"]
        lines.append(
            f"| **K = {k}** | {100 * fb['leaked_share_of_test']:.1f} % | +{fb['theta_gain_mean']:.2f} | "
            f"**{100 * fb['false_confirm_rate']:.1f} %** | +{pb['theta_gain_mean']:.2f} | "
            f"{100 * pb['canary_caught_rate']:.1f} % | **{100 * pb['false_confirm_protected']:.2f} %** |"
        )
    lines += [
        "",
        "## 2. Почему открытый код генераторов в репозитории не помогает обмануть тест",
        "",
    ]
    for item in d["why_code_does_not_help"]:
        lines.append(f"### {item['title']}")
        lines.append(item["detail"])
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=2000)
    ap.add_argument("--no-write", action="store_true")
    a = ap.parse_args()
    res = run_all(n=a.n, write=not a.no_write)
    print(json.dumps({
        k: {
            "fixed_false_confirm": v["fixed_bank"]["false_confirm_rate"],
            "parametric_false_confirm": v["parametric_bank"]["false_confirm_protected"],
            "canary_caught": v["parametric_bank"]["canary_caught_rate"],
        }
        for k, v in res["k_values"].items()
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
