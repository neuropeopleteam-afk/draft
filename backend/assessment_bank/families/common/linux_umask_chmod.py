"""common.linux.umask_chmod — mcq_concept (канарейка): права после umask и chmod.

Правильный ответ проверяется исполнением в песочнице (`stat -c %a`).
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_options, make_rng, pick_ranked
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "common.linux.umask_chmod"

UMASKS = [0o027, 0o033, 0o077, 0o007, 0o037, 0o017, 0o013, 0o023]
FILES = [("report.txt", "logs", "отчёты"), ("backup.tar", "archive", "резервные копии"),
         ("deploy.sh", "releases", "деплой"), ("config.yml", "conf.d", "конфигурация"),
         ("data.csv", "exports", "выгрузки"), ("notes.md", "drafts", "черновики"),
         ("dump.sql", "dumps", "дампы БД"), ("cert.pem", "certs", "сертификаты"),
         ("app.log", "logrotate", "журналы"), ("photo.jpg", "uploads", "загрузки")]
START_MODES = [0o640, 0o755, 0o600, 0o664, 0o750, 0o644, 0o700]
SYMBOLIC = ["g-w,o+r", "u+x,go-r", "o=r", "g+w,o-rwx", "a-x,u+w", "go-w", "g=r,o=", "u-w,g+x"]
CLS = {"u": 6, "g": 3, "o": 0}
BITS = {"r": 4, "w": 2, "x": 1}


def _apply(mode: int, expr: str) -> int:
    for clause in expr.split(","):
        i = 0
        while clause[i] in "ugoa":
            i += 1
        who = clause[:i].replace("a", "ugo")
        op, perms = clause[i], clause[i + 1:]
        val = sum(BITS[p] for p in perms)
        for w in who:
            sh = CLS[w]
            if op == "+":
                mode |= val << sh
            elif op == "-":
                mode &= ~(val << sh)
            else:
                mode = (mode & ~(7 << sh)) | (val << sh)
    return mode


def _wrong_apply(mode: int, expr: str) -> int:
    """Типичная ошибка: «=» понимается как «+»."""
    return _apply(mode, expr.replace("=", "+"))


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    fname, dname, ctx = rng.choice(FILES)
    kind = rng.choice(["file", "dir", "chmod"])
    o = lambda m: format(m, "o")
    if kind in ("file", "dir"):
        u = rng.choice(UMASKS)
        code = f"umask {u:03o}\ntouch {fname}\nmkdir {dname}\nstat -c '%a' " + \
               (fname if kind == "file" else dname)
        correct = (0o666 if kind == "file" else 0o777) & ~u
        cands = [0o777 & ~u, 0o666 - u, u, 0o755, 0o644, 0o777, 0o666 & ~u, 0o600]
        target = f"файл {fname}" if kind == "file" else f"каталог {dname}"
        ask = f"Какие права в восьмеричной записи получит {target}?"
    else:
        start = rng.choice(START_MODES)
        expr = rng.choice(SYMBOLIC)
        correct = _apply(start, expr)
        code = f"touch {fname}\nchmod {start:o} {fname}\nchmod {expr} {fname}\nstat -c '%a' {fname}"
        cands = [_wrong_apply(start, expr), start, _apply(start, expr.replace("-", "+")),
                 correct ^ 0o011, correct ^ 0o100, correct | 0o004, correct & ~0o040]
        ask = f"Какие права в восьмеричной записи будут у {fname} после выполнения?"
    valid = []
    for c in cands:
        if c != correct and c not in valid and 0o400 <= c <= 0o777 and o(c) not in {o(d) for d in valid}:
            valid.append(c)
    if len(valid) < 3:
        raise RuntimeError("мало дистракторов")
    # ранг ключа среди вариантов (как их читает кандидат) — равномерный, если пул позволяет (аудит 21.10)
    pool = {str(i): int(o(c)) for i, c in enumerate(valid)}
    ranked = None
    for nb in sorted(range(4), key=lambda _: rng.random()):
        ranked = pick_ranked(rng, int(o(correct)), pool, nb)
        if ranked:
            break
    distr = [valid[int(i)] for i in ranked] if ranked else valid[:3]
    # однородность вариантов (аудит 21.10): ключ не должен единственным оканчиваться нулями («самый круглый»)
    zeros = lambda m: len(o(m)) - len(o(m).rstrip("0"))  # noqa: E731
    if all(zeros(d) < zeros(correct) for d in distr):
        alt = [c for c in valid if c not in distr and zeros(c) >= zeros(correct)
               and (int(o(c)) > int(o(correct))) == (int(o(distr[2])) > int(o(correct)))]
        if alt:
            distr[2] = alt[0]
    opts, key = make_options(rng, (o(correct), None), [(o(d), None) for d in distr])
    stem = (f"Команды выполняются в bash от обычного пользователя в пустом каталоге "
            f"({ctx}):\n\n{ask}")
    expl = ("Файлы создаются с базовыми правами 666, каталоги — 777; umask снимает биты "
            "(побитовое И с инверсией), а не вычитается арифметически." if kind != "chmod" else
            "Символьный chmod: «+» добавляет, «-» снимает, «=» задаёт права класса целиком.")
    checks = [Check(name="stat", runner="bash", program=code, expect="stdout_equals",
                    expected_stdout=o(correct))]
    ak = AnswerKey(kind="option", value=key, explanation=expl)
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, options=opts, answer_key=ak,
                         context=ctx, verification="execution", checks=checks,
                         language="bash", params={"kind": kind})
