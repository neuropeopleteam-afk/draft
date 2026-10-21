"""backend.db.t21_sql_recursive_deps_output — predict_output (набор t21, порог Senior): рекурсивный CTE по графу
зависимостей сервисов с UNION ALL (SQLite).

Запрос обходит зависимости от корневого сервиса: якорь — корень с глубиной 0, рекурсивная часть добавляет
зависимости с depth + 1; затем по каждому сервису считается число путей (COUNT(*)) и наибольшая глубина. Ловушки:
UNION ALL не убирает дубликаты — общий сервис, достижимый несколькими путями, встречается несколько раз и на разной
глубине; сервис, от которого корень не зависит, в результат не попадает, хотя у него есть рёбра. Ключ —
независимый перебор всех путей (DFS) в генераторе; проверка — исполнение запроса в SQLite.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng, sql_inserts, text_table

FAMILY_ID = "backend.db.t21_sql_recursive_deps_output"

CTX = [("платформа магазина", "api", ["auth", "users", "cart", "billing", "db", "cache", "search", "queue"]),
       ("сервис доставки", "gateway", ["routing", "couriers", "geo", "tariffs", "db", "cache", "notify", "maps"]),
       ("банковское приложение", "bff", ["accounts", "cards", "limits", "ledger", "db", "audit", "fraud", "kyc"])]


def _paths(root: str, edges: list[tuple[str, str]]) -> dict[str, list[int]]:
    """Все пути от корня: для каждого сервиса — список глубин, на которых он встречается."""
    seen: dict[str, list[int]] = {}

    def dfs(node: str, depth: int) -> None:
        seen.setdefault(node, []).append(depth)
        for a, b in edges:
            if a == node:
                dfs(b, depth + 1)

    dfs(root, 0)
    return seen


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, root, pool = rng.choice(CTX)
    for _ in range(500):
        nodes = [root] + rng.sample(pool, 4)
        orphan = rng.choice([p for p in pool if p not in nodes])
        edges = []
        for j in range(1, len(nodes)):  # у каждого некорневого — хотя бы один «родитель» раньше в порядке
            edges.append((nodes[rng.randrange(0, j)], nodes[j]))
        extra = rng.randint(2, 3)
        cand = [(nodes[i], nodes[j]) for i in range(len(nodes)) for j in range(i + 1, len(nodes))
                if (nodes[i], nodes[j]) not in edges]
        edges += rng.sample(cand, extra)
        edges.append((orphan, rng.choice(nodes[1:])))
        paths = _paths(root, [e for e in edges])
        multi = [n for n, d in paths.items() if len(d) >= 2]
        spread = [n for n, d in paths.items() if max(d) != min(d)]
        if multi and spread and max(len(d) for d in paths.values()) <= 4 and len(edges) <= 8:
            break
    else:
        raise RuntimeError("t21_sql_recursive: не собран граф")
    rng.shuffle(edges)
    rows = [(i + 1, a, b) for i, (a, b) in enumerate(edges)]
    cte = rng.choice(["chain", "walk", "tree", "reach"])
    tbl = rng.choice(["deps", "service_deps", "edges"])
    a_paths = rng.choice(["paths", "n_paths", "hits"])
    a_deep = rng.choice(["deepest", "max_depth", "far"])
    query = (f"WITH RECURSIVE {cte}(name, depth) AS (\n"
             f"  SELECT '{root}', 0\n"
             "  UNION ALL\n"
             "  SELECT d.depends_on, c.depth + 1\n"
             f"  FROM {tbl} d\n"
             f"  JOIN {cte} c ON d.service = c.name\n"
             ")\n"
             f"SELECT name, COUNT(*) AS {a_paths}, MAX(depth) AS {a_deep}\n"
             f"FROM {cte}\n"
             "GROUP BY name\n"
             f"ORDER BY {a_deep}, name;")
    cols = ["id", "service", "depends_on"]
    setup = (f"CREATE TABLE {tbl} (id INTEGER PRIMARY KEY, service TEXT NOT NULL, depends_on TEXT NOT NULL);\n"
             + sql_inserts(tbl, cols, rows) + "\n")
    res = sorted(paths.items(), key=lambda kv: (max(kv[1]), kv[0]))
    out = "\n".join(f"{n}|{len(d)}|{max(d)}" for n, d in res)
    expl = (f"Якорь — {root} с глубиной 0; рекурсивная часть добавляет каждую зависимость с depth + 1, а UNION ALL "
            f"не убирает повторы: сервис попадает в {cte} столько раз, сколько путей ведёт к нему от {root}. Глубины "
            "по путям: " + "; ".join(f"{n} — {', '.join(str(x) for x in sorted(d))}" for n, d in res)
            + f". {orphan} зависит от других сервисов, но от {root} к нему пути нет — в результат не попадает. "
              "Сортировка по наибольшей глубине, затем по имени.")
    stem = (f"«{ctx}»: перед релизом строится список всех сервисов, от которых зависит {root}, с числом путей и "
            f"наибольшей глубиной. Таблица `{tbl}` (service зависит от depends_on):\n\n{tbl}\n{text_table(cols, rows)}")
    return output_variant(FAMILY_ID, seed, stem=stem, code=query, out=out, explanation=expl, context=ctx,
                          params={"root": root, "edges": edges}, language="sql", files={"setup.sql": setup})
