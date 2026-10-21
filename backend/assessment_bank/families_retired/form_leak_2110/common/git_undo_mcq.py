"""common.git.undo_mcq — mcq_concept: как исправить историю Git под конкретную цель.

Четыре ситуации: перенести коммиты в новую ветку, отменить коммит с сохранением изменений
в индексе, отменить опубликованный коммит без переписывания истории, вернуть один файл к
старой версии. Каждый вариант ответа исполняется настоящим git во временном репозитории;
верный даёт целевое состояние, остальные — другое.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_options, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "common.git.undo_mcq"

FEATURES = [("search", "add search index", "add search filters", "search.py", "filters.py", "поиск"),
            ("billing", "add invoice model", "add invoice pdf", "invoice.py", "pdf.py", "биллинг"),
            ("auth", "add oauth login", "add login captcha", "oauth.py", "captcha.py", "авторизация"),
            ("export", "add csv export", "add xlsx export", "csv_export.py", "xlsx_export.py", "экспорт")]

STATE = """
echo "branch=$(git rev-parse --abbrev-ref HEAD)"
echo "log=$(git log --format=%s HEAD | tr '\\n' ',')"
echo "staged=$(git diff --cached --name-only | tr '\\n' ',')"
echo "unstaged=$(git diff --name-only | tr '\\n' ',')"
"""


def _commit(path, content, msg):
    return f"echo '{content}' > {path}\ngit add {path}\ngit commit -qm '{msg}'"


def _scenario(rng, name):
    feat, s1, s2, f1, f2, ctx = rng.choice(FEATURES)
    br = f"feature/{feat}"
    app = rng.choice(["app.py", "main.py", "server.py", "service.py", "api.py"])
    first = rng.choice(["init", "initial commit", "start project"])
    base = [_commit("README.md", "demo", first), _commit(app, "v1", "add app")]
    if name == "move":
        n = rng.choice([2, 3])
        extra = [_commit("docs.md", "c", f"document {feat}")] if n == 3 else []
        setup = base + [_commit(f1, "a", s1), _commit(f2, "b", s2)] + extra
        state = STATE + f'echo "main=$(git log --format=%s main | tr \'\\n\' \',\')"\n' \
                        f'echo "feature=$(git log --format=%s {br} 2>/dev/null | tr \'\\n\' \',\')"\n'
        good = f"git branch {br}\ngit reset -q --hard HEAD~{n}"
        wrong = {"checkout_b": f"git checkout -q -b {br}\ngit reset -q --hard HEAD~{n}",
                 "reset_first": f"git reset -q --hard HEAD~{n}\ngit branch {br}",
                 "revert": f"git branch {br}\ngit revert --no-edit HEAD~{n}..HEAD",
                 "soft": f"git branch {br}\ngit reset -q --soft HEAD~{n}"}
        listed = f"«{s1}» и «{s2}»" if n == 2 else f"«{s1}», «{s2}» и «document {feat}»"
        ask = (f"Вы на ветке `main` и сделали {'два коммита' if n == 2 else 'три коммита'} "
               f"{listed}, которые должны были "
               f"попасть в новую ветку `{br}`. Ничего ещё не отправлено на сервер. Нужно: `{br}` "
               f"содержит {'оба коммита' if n == 2 else 'все три коммита'}, `main` указывает "
               f"туда же, где была до них, рабочая копия "
               f"чистая. Какая последовательность команд это делает?")
        why = "ветка создаётся на текущем коммите, затем main сдвигается назад с очисткой рабочей копии"
    elif name == "soft":
        setup = base + [_commit(f1, "draft", s1)]
        state = STATE
        good = "git reset -q --soft HEAD~1"
        wrong = {"hard": "git reset -q --hard HEAD~1", "mixed": "git reset -q HEAD~1",
                 "revert": "git revert --no-edit HEAD", "checkout": "git checkout -q HEAD~1",
                 "amend": "git commit -q --amend --no-edit"}
        ask = (f"Последний коммит «{s1}» на ветке `main` сделан преждевременно и ещё не отправлен. "
               f"Нужно убрать этот коммит из истории ветки, но оставить его изменения в индексе "
               f"(staged), чтобы доработать и закоммитить заново. Какая команда это делает?")
        why = "reset --soft сдвигает ветку, не трогая индекс и рабочую копию"
    elif name == "revert":
        setup = base + [_commit(app, "v2", s1), _commit(f2, "b", s2)]
        state = STATE + f'echo "app=$(cat {app})"\n' + f'echo "f2=$(cat {f2} 2>/dev/null)"\n'
        good = "git revert --no-edit HEAD~1"
        wrong = {"revert_head": "git revert --no-edit HEAD", "reset2": "git reset -q --hard HEAD~2",
                 "rebase": "git rebase -q --onto HEAD~2 HEAD~1", "reset1": "git reset -q --hard HEAD~1"}
        ask = (f"На ветке `main` два последних коммита — «{s1}» (изменил {app}) и после него "
               f"«{s2}». Оба уже отправлены на сервер, коллеги их забрали. Выяснилось, что "
               f"изменение из «{s1}» нужно отменить, а «{s2}» оставить. Историю переписывать "
               f"нельзя. Какая команда это делает?")
        why = "revert создаёт новый коммит, обратный указанному, — опубликованная история не меняется"
    else:  # restore
        cfg = rng.choice(["config.yml", "settings.yml", "deploy.yml"])
        setup = base + [_commit(cfg, "port: 8080", "add config"),
                        f"echo 'port: 9090' > {cfg}\necho 'v2' > {app}\ngit add .\n"
                        f"git commit -qm '{s1}'",
                        _commit(cfg, "port: 7070", s2)]
        state = STATE + f'echo "config=$(cat {cfg})"\necho "app=$(cat {app})"\n'
        good = rng.choice([f"git checkout HEAD~2 -- {cfg}",
                           f"git restore --source=HEAD~2 --staged --worktree {cfg}"])
        # Версия 2 (08.10): дистракторы по длине и форме близки к верной команде (короткая форма checkout или
        # длинная форма restore): раньше верная «restore --source=… --staged --worktree» была заметно длиннее остальных.
        if good.startswith("git checkout"):
            wrong = {"checkout_prev": f"git checkout HEAD~1 -- {cfg}",
                     "restore_worktree": f"git restore --source=HEAD~2 {cfg}",
                     "restore_unstage": f"git restore --staged {cfg}",
                     "reset": "git reset -q --hard HEAD~2",
                     "revert_range": "git revert --no-edit HEAD~2..HEAD",
                     "detach": "git checkout -q HEAD~2"}
        else:
            wrong = {"worktree_only": f"git restore --source=HEAD~2 --worktree {cfg}",
                     "staged_only": f"git restore --source=HEAD~2 --staged {cfg}",
                     "prev_commit": f"git restore --source=HEAD~1 --staged --worktree {cfg}",
                     "head_source": f"git restore --source=HEAD --staged --worktree {cfg}"}
        ask = (f"После коммитов «{s1}» и «{s2}» сломалась конфигурация. Нужно вернуть только файл "
               f"{cfg} к версии коммита «add config» (HEAD~2) — в рабочей копии и в индексе; "
               f"ветка `main` остаётся на месте, остальные файлы не меняются, новых коммитов нет. "
               f"Какая команда это делает?")
        why = "checkout <коммит> -- <файл> (или restore --source) берёт версию одного файла, не двигая ветку"
    return "\n".join(setup) + "\n", state, good, wrong, ask, why, ctx


EXPECTED_NOTE = {"checkout_b": "reset выполняется на новой ветке, main не меняется",
                 "reset_first": "коммиты уже сброшены, ветка создаётся на старом месте",
                 "revert": "revert добавляет новые коммиты вместо сдвига ветки",
                 "soft": "--soft оставляет изменения в индексе, рабочая копия не чистая",
                 "hard": "--hard удаляет изменения", "mixed": "--mixed убирает изменения из индекса",
                 "checkout": "checkout коммита переводит в detached HEAD",
                 "amend": "amend переписывает коммит, но не убирает его",
                 "revert_head": "отменяет не тот коммит",
                 "reset2": "сбрасывает оба коммита и переписывает историю",
                 "rebase": "rebase переписывает опубликованную историю",
                 "reset1": "сбрасывает не тот коммит и переписывает историю",
                 "detach": "переводит в detached HEAD и меняет все файлы",
                 "reset": "двигает ветку и меняет все файлы",
                 "revert_range": "создаёт новые коммиты и откатывает остальные файлы",
                 "checkout_prev": "берёт версию файла из HEAD~1, а не из коммита «add config»",
                 "restore_worktree": "восстанавливает только рабочую копию, индекс остаётся прежним",
                 "restore_unstage": "--staged сбрасывает индекс к HEAD, то есть текущей версии, и не трогает рабочую копию",
                 "worktree_only": "без --staged индекс остаётся прежним, изменение не попадает в индекс",
                 "staged_only": "без --worktree рабочая копия остаётся прежней",
                 "prev_commit": "берёт версию из HEAD~1, а не из коммита «add config»",
                 "head_source": "HEAD — текущая версия файла, ничего не меняется"}


# Калибровка 05.10: подтипы move выделены в common.git.move_commits_mcq (варианты были неизоморфны).
SUBTYPES_HERE = ('soft', 'revert', 'restore')


def _generate(seed: int, family_id: str, subtypes):
    rng = make_rng(family_id, seed)
    name = rng.choice(list(subtypes))
    setup, state, good, wrong, ask, why, ctx = _scenario(rng, name)
    chosen = rng.sample(sorted(wrong), 3)
    opts, key = make_options(rng, (good, None), [(wrong[w], None) for w in chosen])
    checks = []
    for o in opts:
        # собственный вывод git (сводки коммитов) не входит в сравнение состояния
        prog = setup + "{\n" + o.text + "\n} > /dev/null 2>&1\n" + state
        checks.append((o, prog))
    exp = _expected(name, setup, good)
    out = []
    for o, prog in checks:
        out.append(Check(name=f"opt:{o.id}", runner="git", program=prog, embeds_display_code=False,
                         expect="stdout_equals" if o.id == key else "stdout_differs",
                         expected_stdout=exp))
    repo = rng.choice(["shop-api", "crm-web", "partner-portal", "admin-panel", "core-service",
                       "b2b-platform", "mobile-bff", "client-app"])
    stem = f"Репозиторий `{repo}` (модуль «{ctx}»). {ask}"
    ak = AnswerKey(kind="option", value=key,
                   explanation=f"Верно: {why}. Остальные: "
                               + "; ".join(EXPECTED_NOTE[w] for w in chosen) + ".")
    return build_variant(family_id, seed, stem=stem, options=opts, answer_key=ak, context=ctx,
                         verification="execution", checks=out, language="text",
                         display_code_note="Каждый вариант исполняется git в одноразовом "
                                           "репозитории после команд подготовки истории.",
                         params={"scenario": name, "distractors": chosen, "expected": exp})


def _expected(name, setup, good):
    """Целевое состояние по модели (без запуска git)."""
    import re
    subjects = re.findall(r"git commit -qm '([^']+)'", setup)
    if name == "move":
        n = int(good.rsplit("~", 1)[1])
        br_state = ",".join(reversed(subjects)) + ","
        main_state = ",".join(reversed(subjects[:-n])) + ","
        return (f"branch=main\nlog={main_state}\nstaged=\nunstaged=\nmain={main_state}\n"
                f"feature={br_state}")
    if name == "soft":
        f1 = re.findall(r"echo 'draft' > (\S+)", setup)[0]
        return f"branch=main\nlog={','.join(reversed(subjects[:-1]))},\nstaged={f1},\nunstaged="
    if name == "revert":
        s1 = subjects[-2]
        log = [f'Revert "{s1}"'] + list(reversed(subjects))
        return f"branch=main\nlog={','.join(log)},\nstaged=\nunstaged=\napp=v1\nf2=b"
    cfg = good.split()[-1]
    return (f"branch=main\nlog={','.join(reversed(subjects))},\nstaged={cfg},\nunstaged=\n"
            f"config=port: 8080\napp=v2")


def generate(seed: int):
    return _generate(seed, FAMILY_ID, SUBTYPES_HERE)
