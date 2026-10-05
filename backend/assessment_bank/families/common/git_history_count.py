"""common.git.history_count — predict_output: история после merge/reset/revert/cherry-pick.

Ключ считается независимой моделью DAG коммитов и проверяется исполнением настоящего git
в песочнице (временный репозиторий, фиксированные даты и автор).
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "common.git.history_count"

FEATURES = [
    ("login", ["form", "validation", "oauth", "captcha"], "авторизация"),
    ("payments", ["cart", "invoice", "refund", "receipt"], "платежи"),
    ("search", ["index", "filters", "ranking", "suggest"], "поиск"),
    ("export", ["csv", "pdf", "xlsx", "mailer"], "экспорт"),
    ("profile", ["avatar", "bio", "privacy", "badges"], "профиль"),
]
MAIN_NAMES = ["readme", "ci", "docs", "license", "hotfix", "deps", "lint", "config"]


class Repo:
    def __init__(self):
        self.commits: dict[int, tuple[tuple[int, ...], frozenset[str]]] = {}
        self.branches: dict[str, int | None] = {"main": None}
        self.head = "main"
        self.n = 0

    def tip(self, br=None):
        return self.branches[br or self.head]

    def anc(self, c):
        seen, stack = set(), [c]
        while stack:
            x = stack.pop()
            if x is None or x in seen:
                continue
            seen.add(x)
            stack.extend(self.commits[x][0])
        return seen

    def tree(self, c):
        return self.commits[c][1] if c is not None else frozenset()

    def new(self, parents, tree):
        self.n += 1
        self.commits[self.n] = (tuple(parents), frozenset(tree))
        self.branches[self.head] = self.n
        return self.n

    def merge_base(self, a, b):
        common = self.anc(a) & self.anc(b)
        bases = [c for c in common if not any(c != d and c in self.anc(d) for d in common)]
        return bases


def _sequence(rng):
    feat, fnames, ctx = rng.choice(FEATURES)
    br = f"feature/{feat}"
    mains = rng.sample(MAIN_NAMES, 4)
    fnames = list(fnames)
    rng.shuffle(fnames)
    repo = Repo()
    lines = ['c() { echo "$1" > "$1.txt"; git add "$1.txt"; git commit -qm "$1"; }', ""]

    def commit(name):
        t = repo.tip()
        repo.new([t] if t else [], repo.tree(t) | {f"{name}.txt"})
        lines.append(f"c {name}")

    commit(mains.pop())
    lines.append(f"git switch -q -c {br}")
    repo.branches[br] = repo.tip()
    repo.head = br
    for _ in range(rng.randint(1, 3)):
        commit(fnames.pop())
    lines.append("git switch -q main")
    repo.head = "main"
    if rng.random() < 0.6:
        commit(mains.pop())
    ops = rng.sample(["merge", "reset", "revert", "cherry", "commit"], rng.randint(2, 3))
    if "merge" not in ops and rng.random() < 0.7:
        ops.insert(0, "merge")
    for op in ops:
        t = repo.tip()
        if op == "merge":
            ft = repo.tip(br)
            if ft in repo.anc(t):
                continue
            no_ff = rng.random() < 0.4
            if t in repo.anc(ft) and not no_ff:
                repo.branches["main"] = ft
                lines.append(f"git merge -q {br}")
            else:
                bases = repo.merge_base(t, ft)
                if len(bases) != 1:
                    continue
                base = repo.tree(bases[0])
                ours, theirs = repo.tree(t), repo.tree(ft)
                files = set(base) | set(ours) | set(theirs)
                res = set()
                for f in files:
                    o, th, b = f in ours, f in theirs, f in base
                    keep = o if o == th else (th if o == b else o)
                    if keep:
                        res.add(f)
                repo.new([t, ft], res)
                lines.append(f"git merge -q --no-ff --no-edit {br}" if no_ff and t in repo.anc(ft)
                             else f"git merge -q --no-edit {br}")
        elif op == "reset":
            parents = repo.commits[t][0]
            if not parents:
                continue
            repo.branches["main"] = parents[0]
            lines.append("git reset -q --hard HEAD~1")
        elif op == "revert":
            parents = repo.commits[t][0]
            if len(parents) != 1:
                continue
            added = repo.tree(t) - repo.tree(parents[0])
            removed = repo.tree(parents[0]) - repo.tree(t)
            repo.new([t], (repo.tree(t) - added) | removed)
            lines.append("git revert --no-edit HEAD > /dev/null")
        elif op == "cherry":
            ft = repo.tip(br)
            fp = repo.commits[ft][0]
            # cherry-pick на собственного родителя git может выполнить как fast-forward
            if ft in repo.anc(t) or len(fp) != 1 or fp[0] == t:
                continue
            added = repo.tree(ft) - repo.tree(fp[0])
            if added & repo.tree(t) or not added:
                continue
            repo.new([t], repo.tree(t) | added)
            lines.append(f"git cherry-pick {br} > /dev/null")
        else:
            if mains:
                commit(mains.pop())
    q = rng.choice(["count", "files", "ahead"])
    if q == "ahead" and (repo.anc(repo.tip(br)) - repo.anc(repo.tip())) == set():
        q = "count"
    if q == "count":
        lines.append("git log --oneline | wc -l")
        out = str(len(repo.anc(repo.tip())))
        ask = "Сколько строк выведет последняя команда (число)?"
    elif q == "files":
        lines.append("ls *.txt | xargs")
        out = " ".join(sorted(repo.tree(repo.tip())))
        ask = "Что выведет последняя команда (список файлов в рабочей копии)?"
    else:
        lines.append(f"git log --oneline main..{br} | wc -l")
        out = str(len(repo.anc(repo.tip(br)) - repo.anc(repo.tip())))
        ask = f"Сколько коммитов ветки {br} ещё не попали в main (что выведет последняя команда)?"
    return "\n".join(lines), out, ask, ctx, ops, q


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    code, out, ask, ctx, ops, q = _sequence(rng)
    stem = ("Скрипт выполняется в новом пустом репозитории: `git init -b main` уже сделан, "
            "коммитов нет. Функция `c` создаёт файл `<имя>.txt` и коммитит его с сообщением "
            f"«<имя>». Конфликтов слияния не возникает. {ask}")
    ak = AnswerKey(kind="output", value=out,
                   explanation="Fast-forward не создаёт коммит слияния, --no-ff и расходящиеся "
                               "ветки — создают; reset --hard HEAD~1 переносит ветку на первого "
                               "родителя; revert и cherry-pick добавляют новые коммиты.")
    checks = [Check(name="stdout", runner="git", program=code, expect="stdout_equals",
                    expected_stdout=out)]
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, answer_key=ak, context=ctx,
                         verification="execution", checks=checks,
                         params={"ops": ops, "question": q})
