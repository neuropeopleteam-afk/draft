"""devops.linux.permissions_output — predict_output: права доступа к файлу по ls -l и id.

Правило POSIX (man 7 inode / path_resolution; суперпользователь не рассматривается): если uid процесса совпадает
с владельцем — действуют ТОЛЬКО биты владельца; иначе, если среди групп пользователя есть группа файла, — только
биты группы; иначе — биты остальных. Классы не объединяются: у владельца с `r` только в правах группы чтения нет
(ловушка примерно в половине вариантов). Вопросы — чтение (r), изменение (w), запуск (x). Ответ — строки
«пользователь действие файл: да/нет». Ключ — исполнение модели проверки прав над показанными строками ls -l и id
в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_rng
from assessment_bank.schema import AnswerKey, Check

from ._yaml_model import program

FAMILY_ID = "devops.linux.permissions_output"

CTX = [("сервер сборки", "ci", ["build.sh", "release.env", "cache.db"]),
       ("сервер базы данных", "dba", ["backup.sh", "pg_hba.conf", "dump.sql"]),
       ("веб-сервер", "web", ["deploy.sh", "site.conf", "access.log"]),
       ("сервер мониторинга", "mon", ["collect.sh", "alerts.yml", "metrics.db"]),
       ("файловый сервер", "share", ["sync.sh", "quota.txt", "report.csv"]),
       ("сервер очередей", "mq", ["rotate.sh", "broker.conf", "queue.dat"])]
NORMAL = [0o750, 0o640, 0o755, 0o700, 0o664, 0o644, 0o770, 0o754]
TRAP = [0o460, 0o604, 0o570, 0o407, 0o470, 0o046, 0o574]
USERS = ["anna", "boris", "vera", "gleb", "dina", "egor"]
ACTS = {"r": "прочитать", "w": "изменить", "x": "запустить"}

MODEL = '''
import re

files = {}
for line in LS.splitlines():
    p = line.split()
    files[p[-1]] = (p[0][1:], p[2], p[3])
users = {}
for line in IDS.splitlines():
    name = re.search(r"uid=\\d+\\((\\w+)\\)", line).group(1)
    users[name] = set(re.findall(r"\\d+\\((\\w[\\w-]*)\\)", line.split("groups=")[1]))
BIT = {"прочитать": 0, "изменить": 1, "запустить": 2}
for q in QUESTIONS.splitlines():
    user, act, fname = q.split()
    mode, owner, group = files[fname]
    cls = mode[0:3] if user == owner else (mode[3:6] if group in users[user] else mode[6:9])
    print(f"{user} {act} {fname}: " + ("да" if cls[BIT[act]] != "-" else "нет"))
'''


def _rwx(mode: int) -> str:
    out = ""
    for shift in (6, 3, 0):
        b = (mode >> shift) & 7
        out += ("r" if b & 4 else "-") + ("w" if b & 2 else "-") + ("x" if b & 1 else "-")
    return out


def _can(mode, owner, group, user, groups, act):
    shift = 6 if user == owner else (3 if group in groups else 0)
    bit = {"r": 4, "w": 2, "x": 1}[act]
    return bool((mode >> shift) & bit)


def _union(mode, owner, group, user, groups, act):
    bit = {"r": 4, "w": 2, "x": 1}[act]
    m = mode & 7
    if group in groups:
        m |= (mode >> 3) & 7
    if user == owner:
        m |= (mode >> 6) & 7
    return bool(m & bit)


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, grp, fnames = rng.choice(CTX)
    trap = rng.random() < 0.5
    for _ in range(3000):
        u = rng.sample(USERS, 3)
        f = rng.sample(fnames, 2)
        modes = [rng.choice(TRAP if (trap and i == 0) else NORMAL) for i in range(2)]
        owners = [u[0], rng.choice([u[0], u[1]])]
        groups = {u[0]: {u[0]} | ({grp} if rng.random() < 0.5 else set()), u[1]: {u[1], grp}, u[2]: {u[2]}}
        qs = []
        for _ in range(4):
            i = rng.randrange(2)
            qs.append((rng.choice(u), rng.choice("rwx"), i))
        if len(set(qs)) < 4:
            continue
        ans = [_can(modes[i], owners[i], grp, us, groups[us], a) for us, a, i in qs]
        diff = any(_can(modes[i], owners[i], grp, us, groups[us], a) != _union(modes[i], owners[i], grp, us,
                                                                           groups[us], a) for us, a, i in qs)
        if (diff if trap else True) and any(ans) and not all(ans) and len({q[0] for q in qs}) >= 2:
            break
    sizes = [rng.randint(200, 90000) for _ in f]
    ls = "\n".join(f"-{_rwx(modes[i])} 1 {owners[i]} {grp} {sizes[i]} Oct 11 0{i + 7}:1{i} {f[i]}" for i in range(2))
    gid = {name: 1001 + j for j, name in enumerate(USERS)}
    gid[grp] = 2000
    ids = "\n".join(f"uid={gid[us]}({us}) gid={gid[us]}({us}) groups=" + ",".join(
        f"{gid[g]}({g})" for g in sorted(groups[us], key=lambda g: gid[g])) for us in u)
    code = ls + "\n\n" + ids
    questions = "\n".join(f"{us} {ACTS[a]} {f[i]}" for us, a, i in qs)
    expected = "\n".join(f"{us} {ACTS[a]} {f[i]}: " + ("да" if ok else "нет") for (us, a, i), ok in zip(qs, ans))
    qtxt = "; ".join(f"сможет ли {us} {ACTS[a]} `{f[i]}`" for us, a, i in qs)
    stem = (f"{ctx.capitalize()}: ниже вывод `ls -l` в рабочем каталоге и `id` трёх пользователей (каталог "
            f"доступен всем, root не рассматриваем). Ответьте по порядку: {qtxt}? Ответ — строки вида "
            "`пользователь действие файл: да` или `…: нет`.")
    expl = ("Применяется ровно один класс прав: владелец — только первая тройка rwx, иначе член группы файла — "
            "только вторая, иначе — третья. Классы не складываются: владелец без r в первой тройке файл не "
            "прочитает, даже если r есть у группы и остальных.")
    prog = program(MODEL, LS=ls, IDS=ids, QUESTIONS=questions)
    checks = [Check(name="perm_model", runner="python", program=prog, expect="stdout_equals",
                    expected_stdout=expected, embeds_display_code=False)]
    ak = AnswerKey(kind="output", value=expected, explanation=expl)
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, language="text",
                         display_code_note="Показан вывод ls -l и id; исполняется модель проверки прав POSIX над "
                                           "этими строками",
                         params={"trap": trap, "modes": [oct(m) for m in modes]})
