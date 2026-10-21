"""analyst.sql.t21_referral_levels_output — predict_output (набор t21, порог Senior): рекурсивный CTE по дереву
«кто кого пригласил» и подсчёт по уровням.

Таблица-дерево (рефералы, оргструктура, категории каталога, задачи и подзадачи): у корней родитель NULL, у одной
«потерянной» ветки родитель указывает на несуществующий id. Рекурсивный CTE стартует с корней и спускается по
JOIN, иногда с ограничением глубины `WHERE t.lvl < L`. Ловушки: ветка с несуществующим родителем (и её потомки) не
достижима и не считается; при ограничении глубины узлы глубже L не попадают; корни — уровень 0. Ключ — независимый
обход дерева в генераторе; проверка — исполнение запроса в sqlite.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng, sql_inserts, text_table

FAMILY_ID = "analyst.sql.t21_referral_levels_output"

# (таблица, сюжет, колонка родителя, алиас таблицы, что считаем)
CTX = [
    ("users", "Реферальная программа: кто кого пригласил", "invited_by", "u", "users_cnt"),
    ("employees", "Оргструктура для отчёта по уровням управления", "manager_id", "e", "staff_cnt"),
    ("categories", "Дерево категорий каталога", "parent_id", "c", "categories_cnt"),
    ("tasks", "Задачи и подзадачи проекта в трекере", "parent_id", "k", "tasks_cnt"),
]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    T, plot, par, al, cnt_alias = rng.choice(CTX)
    limit = rng.choice([1, 2]) if rng.random() < 0.5 else None
    for _ in range(1000):
        n = rng.randint(8, 10)
        base = rng.choice([1, 10, 100])
        ids = [base + i for i in range(n)]
        n_roots = rng.choice([1, 2])
        parent = {}
        level = {}
        for k, i in enumerate(ids):
            if k < n_roots:
                parent[i] = None
                level[i] = 0
            else:
                p = rng.choice(ids[:k])
                parent[i] = p
                level[i] = None if level.get(p) is None else level[p] + 1
        # одна потерянная ветка: родитель — несуществующий (удалённый) id
        cand = [i for i in ids[n_roots:] if level[i] is not None and level[i] >= 1]
        if not cand:
            continue
        lost = rng.choice(cand)
        missing = max(ids) + rng.randint(3, 9)
        parent[lost] = missing
        # пересчитать уровни от корней
        level = {i: None for i in ids}
        frontier = [i for i in ids if parent[i] is None]
        for i in frontier:
            level[i] = 0
        while frontier:
            nxt = []
            for i in frontier:
                for j in ids:
                    if parent[j] == i and level[j] is None:
                        level[j] = level[i] + 1
                        nxt.append(j)
            frontier = nxt
        unreachable = [i for i in ids if level[i] is None]
        reach = [i for i in ids if level[i] is not None]
        maxlvl = max(level[i] for i in reach)
        if maxlvl < 2 or maxlvl > 4 or len(unreachable) > 3:
            continue
        if limit is not None and maxlvl <= limit:
            continue
        break
    else:
        raise RuntimeError("t21_referral_levels: не собралось дерево")
    rows = [(i, parent[i]) for i in ids]
    if rng.random() < 0.5:
        rng.shuffle(rows)
    where = f"\n  WHERE t.lvl < {limit}" if limit is not None else ""
    code = (f"WITH RECURSIVE tree(id, lvl) AS (\n"
            f"  SELECT id, 0\n"
            f"  FROM {T}\n"
            f"  WHERE {par} IS NULL\n"
            f"  UNION ALL\n"
            f"  SELECT {al}.id, t.lvl + 1\n"
            f"  FROM {T} {al}\n"
            f"  JOIN tree t ON {al}.{par} = t.id{where}\n"
            f")\n"
            f"SELECT lvl, COUNT(*) AS {cnt_alias}\n"
            f"FROM tree\n"
            f"GROUP BY lvl\n"
            f"ORDER BY lvl;")
    top = maxlvl if limit is None else min(maxlvl, limit)
    counts = [(lv, sum(1 for i in reach if level[i] == lv)) for lv in range(top + 1)]
    out = "\n".join(f"{lv}|{c}" for lv, c in counts)
    setup = (f"CREATE TABLE {T} (id INTEGER PRIMARY KEY, {par} INTEGER);\n"
             + sql_inserts(T, ["id", par], rows) + "\n")
    stem = (f"{plot}: рекурсивный запрос раскладывает записи по уровням от корня (у корня {par} — NULL).\n\n"
            f"{T}\n{text_table(['id', par], rows)}")
    lv_txt = "; ".join(f"уровень {lv}: " + ", ".join(str(i) for i in ids if level[i] == lv)
                       for lv in range(maxlvl + 1))
    lim_txt = (f" Условие WHERE t.lvl < {limit} не даёт спуститься ниже уровня {limit}, поэтому уровни глубже "
               f"{limit} не попадают в результат." if limit is not None and maxlvl > limit else "")
    expl = (f"Старт — строки с {par} IS NULL (уровень 0), дальше JOIN по {par} = id. По уровням: {lv_txt}. "
            f"У id {lost} родитель {missing} — такой записи нет, поэтому id {', '.join(str(i) for i in unreachable)} "
            f"не достижимы от корня и не считаются.{lim_txt} Ответ: " + "; ".join(out.splitlines()) + ".")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=plot,
                          params={"rows": rows, "limit": limit}, language="sql", files={"setup.sql": setup})
