"""docs/bank/BANK_README.md — сводка банка из JSON-отчётов (А3, 21.10.2026). Числа руками не пишутся.

Запуск из корня: python3 tools/bank_report.py
Источники: backend/assessment_bank/BANK_SYNC.json (tools/bank_manifest.py), docs/bank/audit_2110.json
(tools/bank_audit.py), docs/bank/mutation_report.json (tools/bank_mutation_check.py),
docs/bank/blind_solve_2110.json (tools/bank_blind_solve.py).
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _j(p: str):
    f = ROOT / p
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


def pct(x) -> str:
    return "—" if x is None else f"{x * 100:.1f} %".replace(".", ",")


def n(x) -> str:
    return f"{x:,}".replace(",", " ") if isinstance(x, int) else str(x)


def main() -> None:
    bs = _j("backend/assessment_bank/BANK_SYNC.json")
    au = _j("docs/bank/audit_2110.json")
    mu = _j("docs/bank/mutation_report.json")
    bl = _j("docs/bank/blind_solve_2110.json")
    q = bs["quality"]
    v = bs["validation"]["summary"]
    L = ["# Банк заданий «Драфт» — состояние и проверки", "",
         f"Коммит банка `{bs['commit']}`, хэш содержимого `{bs['content_hash'][:16]}…`, собрано {bs['synced_at']}. "
         "Все числа ниже — из JSON-отчётов (команды пересчёта — в конце).", "",
         "## Состав", "",
         f"- Семейств в выдаче: **{n(bs['n_families'])}**; направлений с полным покрытием уровней Стажёр…Senior: "
         f"{len(bs['directions_verified'])} ({', '.join(bs['directions_verified'])}).",
         f"- Выведены из выдачи до переработки: LP-v2 — {q['retired']['lp_v2_2010']} семейств "
         f"(`{q['retired']['readme']}`: почему).",
         f"- Новая волна LP-3 (старшие грейды, ввод ответа, ключ меняется по вариантам): {len(q['lp3_families'])} семейств.",
         f"- Lead: {q['lead_principal_mcq']['lead']['families']} семейств, из них выбор ответа "
         f"{pct(q['lead_principal_mcq']['lead']['share'])}; Principal: {q['lead_principal_mcq']['principal']['families']}, "
         f"выбор ответа {pct(q['lead_principal_mcq']['principal']['share'])}.",
         f"- Параметры трудности: {q['prior_a_rule']}.", "",
         "## Валидатор (проверка ключей исполнением)", "",
         f"- seed: {bs['validation']['seeds']}; семейств {n(v.get('n_families'))}, вариантов {n(v.get('n_variants_generated'))}, "
         f"уникальных {n(v.get('n_unique_variants'))}; проверок исполнением {n(v.get('n_checks'))}, не прошло "
         f"{n(v.get('n_checks_failed'))}; статусы {v.get('status')}.",
         f"- Где: {bs['validation']['where']}.", ""]
    vb = q.get("vs_base")
    if vb:
        cc = vb["common_changed"]
        L += ["## Отличие от банка, на котором считала методика (`docs/bank/bank_diff_vs_603474f.json`)", "",
              f"- База: `{vb['base']['ref']}` ({vb['base']['ref_commit']}), манифест банка commit "
              f"`{vb['base']['bank_manifest_commit']}`, {n(vb['base']['n_families_loaded'])} семейств. "
              f"Текущий: голова `{vb['head']['commit']}`, {n(vb['head']['n_families_loaded'])} семейств.",
              f"- Добавлено {vb['added']['n']} (LP-3: {vb['added']['groups']['lp3']}), снято {vb['removed']['n']}; "
              "320 семейств LP-v2 в базе не было — они жили только в этой ветке и сняты до слияния.",
              f"- Из общих {n(vb['base']['n_families_loaded'] - vb['removed']['n'])}: изменён a — {n(cc.get('a', 0))}, "
              f"b — {n(cc.get('b', 0))}, грейды — {n(cc.get('grades', 0))}, время — {n(cc.get('time_limit_s', 0))}, "
              f"сам вариант на первых зёрнах — {n(cc.get('variants', 0))}.",
              f"- Переходы a: {', '.join(f'{k}: {v}' for k, v in vb['a_transitions'].items())}.", ""]
    if au:
        g = au["guess_attack"]
        L += ["## Аудит утечек и угадываемости (`docs/bank/audit_2110.json`)", "",
              f"- {au['n_families']} семейств × {au['n_seeds']} seed: ошибок генерации {au['generation_errors']['n_families']}, "
              f"грейд в условии {au['grade_in_stem']['n_families']}, служебные поля в публичном виде "
              f"{au['public_leak']['n_families']}.",
              f"- «Решатель без знаний» на числовом выборе ({n(g['all_numeric_choice']['n_variants'])} вариантов): лучшая "
              f"эвристика «{g['all_numeric_choice']['best_heuristic']}» — {pct(g['all_numeric_choice']['best_accuracy'])} "
              f"при шансе {pct(g['all_numeric_choice']['chance'])}; обратные задачи — "
              f"{pct(g['inverse']['best_accuracy'])} при шансе {pct(g['inverse']['chance'])}; старые 4-вариантные — "
              f"{pct(g['other']['best_accuracy'])} при шансе {pct(g['other']['chance'])} (известный хвост, см. ниже).",
              f"- Постоянство содержания ключа ≥ 0,8 по вариантам: {au['key_constancy']['n_families_at_or_above']} семейств "
              "— помечены `leak_resistance: low` (дефект один на семейство), чтобы движок ограничивал экспозицию.", ""]
    if mu:
        L += ["## Мутационный самоконтроль тестов (`docs/bank/mutation_report.json`)", "",
              f"- Мутанты эталонного решения, тесты задания без изменений: {n(mu['n_mutants'])} мутантов, отвергнуто "
              f"{n(mu['n_killed'])} ({pct(mu['mutation_kill_rate'])}); эквивалентные мутанты не отделяются — оценка "
              "консервативная.",
              f"- Известные дефекты и неверные исправления: {n(mu['n_known_bad'])}, отвергнуто тестами "
              f"{n(mu['n_known_bad_rejected'])} ({pct(mu['known_bad_reject_rate'])}).",
              f"- Семейства на go/java/bash/sqlite/git без мутаций решения: {mu['unsupported_runner_families']}.", ""]
    if bl:
        L += ["## Независимая проверка ключей вслепую (`docs/bank/blind_solve_2110.json`)", "",
              f"- Модель `{bl['model']}` решала вариант, не видя ключа: {bl['n_sampled']} семейств (стратифицированно, "
              f"seed выборки {bl['sample_seed']}, SHA-256 списка `{bl['sample_sha256'][:12]}…`), совпало с ключом "
              f"{bl['n_match']} ({pct(bl['match_rate'])}), без ответа {bl['n_no_answer']}. Расхождения разобраны в "
              "`docs/bank/blind_solve_review.md`.", ""]
    L += ["## Что честно не сделано", "",
          "- Калибровки параметров на людях нет: a и b — априорные (подпись «до калибровки на людях»).",
          "- Хвост угадываемости — старые 4-вариантные расчётные семейства (ловушки симметричны вокруг ключа).",
          "- Мутации решения для go/java/bash/sqlite/git не реализованы.", "",
          "## Пересчёт", "",
          "```", "cd backend && python -m assessment_bank validate --seeds 20 --out <каталог>",
          "PYTHONPATH=. python3 ../tools/bank_audit.py --seeds 20 --out ../docs/bank/audit_2110.json",
          "cd .. && python3 tools/bank_mutation_check.py --seeds 1 --limit 8",
          "cd backend && PYTHONPATH=. python3 ../tools/bank_blind_solve.py --share 0.1 --sample-seed 20261021 "
          "--model openai/gpt-5.6-luna --out ../docs/bank/blind_solve_2110.json",
          "cd .. && python3 tools/bank_manifest.py --validation-report <каталог>/validation_report.json",
          "python3 tools/bank_report.py", "```", ""]
    (ROOT / "docs" / "bank" / "BANK_README.md").write_text("\n".join(L), encoding="utf-8")
    print("docs/bank/BANK_README.md")


if __name__ == "__main__":
    main()
