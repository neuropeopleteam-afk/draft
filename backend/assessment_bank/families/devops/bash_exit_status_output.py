"""devops.bash.exit_status_output — predict_output: коды возврата в списках && / || и $?.

Скрипт из 3–4 строк проверяет файлы окружения развёртывания (`test -f`, `test -d`, `grep -qsF`, сравнение
переменной) и печатает метки. Один подтип: как статус условия управляет `&&`/`||` и что лежит в `$?`
(ловушки — `grep` по отсутствующему файлу даёт 2, а не 1; `C && echo X; echo $?` после ложного C даёт 1;
`!` инвертирует только статус). Ключ считает независимая модель на Python, проверка — исполнение показанного
скрипта в bash-песочнице с теми же файлами.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "devops.bash.exit_status_output"

CTX = [("выкладка интернет-магазина", "shop"), ("обновление CRM", "crm"), ("релиз платёжного шлюза", "pay"),
       ("развёртывание каталога", "catalog"), ("перезапуск биллинга", "billing"), ("выкладка личного кабинета", "lk")]
CONF_KEYS = [("mode", ["prod", "stage"]), ("region", ["msk", "spb"]), ("tls", ["on", "off"]),
             ("cache", ["redis", "none"])]
LABELS = ["OK", "FAIL", "READY", "SKIP", "DONE", "WARN", "NEW", "MISS"]


def _conditions(rng, files, conf, env_mode):
    """Список (текст условия, статус) по фактическому окружению."""
    out = []
    for name in ("app.conf", "release.lock", "deploy.env"):
        out.append((f"test -f {name}", 0 if name in files else 1))
    for d in ("backup", "logs"):
        out.append((f"test -d {d}", 0 if f"{d}/.keep" in files else 1))
    key, vals = rng.choice(CONF_KEYS)
    val = rng.choice(vals)
    present = "app.conf" in files
    text = files.get("app.conf", "")
    st = 2 if not present else (0 if f"{key}={val}" in text else 1)
    out.append((f"grep -qsF '{key}={val}' app.conf", st))
    st2 = 2 if "deploy.env" not in files else (0 if "MODE=" in files["deploy.env"] else 1)
    out.append(("grep -qsF 'MODE=' deploy.env", st2))
    for m in ("prod", "stage"):
        out.append((f'[ "$MODE" = "{m}" ]', 0 if env_mode == m else 1))
    rng.shuffle(out)
    return out


def _line(rng, form, cond, labels):
    """Строка скрипта и функция модели: (вывод, статус последней команды)."""
    c, st = cond
    a, b = labels
    if form == "and_or":
        return f"{c} && echo {a} || echo {b}", ([a] if st == 0 else [b]), 0
    if form == "or_only":
        return f"{c} || echo {a}", ([] if st == 0 else [a]), 0
    if form == "status":
        return f'{c}; echo "код $?"', [f"код {st}"], 0
    if form == "and_then_status":
        out = [a] if st == 0 else []
        return f'{c} && echo {a}; echo "после $?"', out + [f"после {0 if st == 0 else st}"], 0
    if form == "not_and":
        return f"! {c} && echo {a}", ([a] if st != 0 else []), 0
    raise ValueError(form)


FORMS = ["and_or", "or_only", "status", "and_then_status", "not_and"]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, app = rng.choice(CTX)
    for _ in range(200):
        files = {}
        conf_lines = [f"{k}={rng.choice(v)}" for k, v in rng.sample(CONF_KEYS, rng.randint(2, 3))]
        if rng.random() < 0.7:
            files["app.conf"] = "\n".join([f"app={app}"] + conf_lines) + "\n"
        if rng.random() < 0.4:
            files["release.lock"] = f"{app} 2026-10-{rng.randint(10, 28)}\n"
        if rng.random() < 0.5:
            files["deploy.env"] = (f"MODE={rng.choice(['prod', 'stage'])}\n" if rng.random() < 0.6
                                   else f"APP={app}\n")
        for d in ("backup", "logs"):
            if rng.random() < 0.5:
                files[f"{d}/.keep"] = ""
        env_mode = rng.choice(["prod", "stage"])
        conds = _conditions(rng, files, conf_lines, env_mode)
        n = rng.randint(3, 4)
        forms = rng.sample(FORMS, n)
        if "status" not in forms and "and_then_status" not in forms:
            forms[0] = rng.choice(["status", "and_then_status"])
        if forms[-1] == "not_and":  # `! C && echo` при истинном C завершает скрипт кодом 1 — не последней строкой
            forms[-1], forms[0] = forms[0], forms[-1]
        labels = rng.sample(LABELS, 2 * n)
        lines, out = [f"MODE={env_mode}"], []
        used = conds[:n]
        for i, form in enumerate(forms):
            text, o, _ = _line(rng, form, used[i], labels[2 * i:2 * i + 2])
            lines.append(text)
            out += o
        # хотя бы одна ловушка: grep по отсутствующему файлу (статус 2) или ложное условие перед &&
        tricky = any(st == 2 for _, st in used) or any(f == "and_then_status" and used[i][1] != 0
                                                       for i, f in enumerate(forms))
        if out and tricky:
            break
    code = "\n".join(lines)
    expected = "\n".join(out)
    listing = []
    for name in sorted(files):
        if name.endswith("/.keep"):
            listing.append(f"- каталог `{name.split('/')[0]}/`")
        else:
            body = files[name].strip().replace("\n", "; ")
            listing.append(f"- файл `{name}`: `{body}`")
    missing = [x for x in ("app.conf", "release.lock", "deploy.env") if x not in files]
    missing += [d + "/" for d in ("backup", "logs") if f"{d}/.keep" not in files]
    env = "\n".join(listing) if listing else "- (пусто)"
    stem = (f"Скрипт проверки перед развёртыванием ({ctx}) запускают в каталоге, где есть:\n{env}\n"
            f"Нет: {', '.join('`' + m + '`' for m in missing) or '—'}.\n\n"
            "Что выведет скрипт (bash)? Каждую строку вывода — с новой строки.")
    expl = ("`&&` выполняет правую часть только при статусе 0, `||` — при ненулевом; `$?` — статус последней "
            "команды списка. `grep -s` по отсутствующему файлу завершается с кодом 2, а не 1; после ложного "
            "условия в `C && echo X` статус списка — статус C.")
    ak = AnswerKey(kind="output", value=expected, explanation=expl)
    checks = [Check(name="stdout", runner="bash", program=code, files=files, expect="stdout_equals",
                    expected_stdout=expected)]
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, params={"forms": forms})
