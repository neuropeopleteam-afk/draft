"""Таблицы отчёта из external_evectio.json (без чисел руками): python tools/realdata/djinni/evectio/report_evectio.py > таблицы."""
import json, os

HERE = os.path.dirname(os.path.abspath(__file__))
d = json.load(open(os.path.join(HERE, "../../../../docs/realdata/djinni/evectio/external_evectio.json"), encoding="utf-8"))
m = d["matching"]
f = lambda x: f"{x:.3f}".replace(".", ",")  # noqa: E731
ci = lambda c: f"[{f(c[0])}; {f(c[1])}]"  # noqa: E731
print(f"Подбор: {m['vacancies_evaluated']} отложенных вакансий (из {m['vacancies']}; без релевантных пропущена {m['vacancies'] - m['vacancies_evaluated']}), "
      f"{m['candidates']} кандидатов, {m['labels']} пар, релевантно при оценке ≥ {m['threshold']}.\n")
for proto, title in (("pool", "по всей базе (ЗАГОЛОВОК)"), ("pairs", "только размеченные пары")):
    print(f"Протокол «{title}»\n")
    print("| Метрика | Наш продукт, B «перевод полей» [ДИ 95 %] | Наш продукт, A «как есть» | Их ранжировщик | Их базовая линия «поиск по резюме» | B − их ранжировщик [ДИ 95 %] |")
    print("|---|---|---|---|---|---|")
    for k in ("ndcg@10", "p@10", "mrr", "recall@30"):
        b, a = m["configs"]["B_mapped"][proto][k], m["configs"]["A_as_is"][proto][k]
        print(f"| {k} | {f(b['ours'])} {ci(b['ours_ci95'])} | {f(a['ours'])} | {f(b['their'])} | {f(b['their_keyword'])} | {f(b['ours_minus_their'])} {ci(b['ours_minus_their_ci95'])} |")
    print()
sh = m["configs"]["B_mapped"]["shared_directions"]
print(f"Срез «5 общих направлений» (B, по всей базе, N = {sh['n']} вакансий)\n")
print("| Метрика | Наш продукт [ДИ 95 %] | Их ранжировщик | Их базовая линия | Разность [ДИ 95 %] |\n|---|---|---|---|---|")
for k, v in sh["pool"].items():
    print(f"| {k} | {f(v['ours'])} {ci(v['ours_ci95'])} | {f(v['their'])} | {f(v['their_keyword'])} | {ci(v['ours_minus_their_ci95'])} |")
w = m["configs"]["B_mapped"]["wins_ndcg10_pool_vs_their"]
print(f"\nnDCG@10 выше их ранжировщика: {w['wins']} из {w['n']} вакансий (равно {w['ties']}).\n")
ro, rt = d["resume"]["ours"], d["resume"]["their"]
print(f"Разбор резюме: их отложенный набор, {ro['resumes']} резюме, {ro['skills_labeled']} навыков в эталоне.\n")
print("| Показатель | Наш продукт | Их разбор (текущий) | Их разбор «до правок» (их замер) |\n|---|---|---|---|")
for k in ("name", "email", "phone", "telegram", "github", "city", "specialization", "experience_years"):
    note = " (нет в продукте)" if k in ro["fields_not_in_product"] else ""
    print(f"| поле {k}{note} | {f(ro['field_accuracy'][k])} | {f(rt['holdout']['field_accuracy'][k])} | {f(rt['holdout_first_run']['field_accuracy'][k])} |")
for k in ("precision", "recall", "f1"):
    print(f"| навыки {k} (строго, их онтология) | {f(ro['skills'][k])} | {f(rt['holdout']['skills'][k])} | {f(rt['holdout_first_run']['skills'][k])} |")
s2 = ro["skills_shared_ontology"]
print(f"| навыки recall на общей части онтологий ({s2['gold_skills']} навыков) | {f(s2['recall'])} | — | — |")
print(f"| навыки F1 на общей части онтологий | {f(s2['f1'])} | — | — |")
sp = ro["specialization_on_shared_directions"]
print(f"| направление на общих направлениях ({sp['n']} резюме) | {f(sp['accuracy'])} | — | — |")
print(f"| средняя ошибка стажа, лет | {f(ro['experience_mae'])} | {f(rt['holdout']['experience_mae'])} | {f(rt['holdout_first_run']['experience_mae'])} |")
