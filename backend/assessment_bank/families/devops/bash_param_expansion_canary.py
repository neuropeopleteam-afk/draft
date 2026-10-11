"""devops.bash.param_expansion_canary — predict_output (канарейка): раскрытие параметров bash.

Канареечное семейство: seed 1..30 опубликованы, служат детектору предзнания (время + правильность), в грейд
не входят. Скрипт из пяти `echo` с раскрытиями `${v:-x}`, `${v-x}` (пустая и незаданная переменная
различаются), `${#v}`, `${v##*/}`, `${v%.*}`, `${v%%.*}`. Ключ — исполнение показанного скрипта в bash.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "devops.bash.param_expansion_canary"

PATHS = {"backup/db_2026.tar.gz": "резервные копии", "/var/log/nginx/access.log.1": "журналы веб-сервера",
         "releases/app-1.4.2.zip": "архивы релизов", "data/export.final.csv": "выгрузки данных",
         "/opt/bin/run.sh": "скрипты запуска", "img/logo.v2.png": "статические файлы"}
NAMES = [("user_name", "гость"), ("region", "eu-west"), ("tier", "free"), ("lang", "ru")]
EXPR = ["{p}##*/", "{p}%.*", "{p}%%.*", "#{p}", "{p}#*/"]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    path = rng.choice(sorted(PATHS))
    (v1, d1), (v2, d2) = rng.sample(NAMES, 2)
    lines = [f'{v1}=""', f"unset {v2}", f'file="{path}"']
    outs = rng.sample([f'echo "${{{v1}:-{d1}}}"', f'echo "[${{{v1}-{d1}}}]"', f'echo "${{{v2}-{d2}}}"',
                       f'echo "${{{v2}:-{d2}}}"'], 2)
    exprs = rng.sample(EXPR, 3)
    outs += [f'echo "${{{e.format(p="file")}}}"' for e in exprs]
    rng.shuffle(outs)
    code = "\n".join(lines + outs)

    def ev(o):
        body = o[len('echo "'):-1]
        if body.startswith("[") and body.endswith("]"):
            return "[" + ev('echo "' + body[1:-1] + '"') + "]"
        inner = body[2:-1]
        if inner.startswith("#"):
            return str(len(path))
        for op in (":-", "-"):
            if op in inner and inner.split(op)[0] in (v1, v2):
                name, dflt = inner.split(op, 1)
                is_set = name == v1  # v1 задана пустой строкой, v2 не задана
                if op == ":-":
                    return dflt
                return "" if is_set else dflt
        name, rest = inner[:4], inner[4:]
        assert name == "file"
        if rest == "##*/":
            return path.rsplit("/", 1)[-1]
        if rest == "#*/":
            return path.split("/", 1)[1] if "/" in path else path
        if rest == "%.*":
            return path.rsplit(".", 1)[0]
        if rest == "%%.*":
            return path.split(".", 1)[0]
        raise AssertionError(rest)

    expected = "\n".join(ev(o) for o in outs)
    stem = "Что выведет скрипт bash? Ответ — строки вывода по порядку."
    checks = [Check(name="stdout", runner="bash", program=code, expect="stdout_equals", expected_stdout=expected)]
    ak = AnswerKey(kind="output", value=expected,
                   explanation=f"`:-` подставляет значение и для пустой, и для незаданной переменной, `-` — только "
                               f"для незаданной ({v1} задана пустой строкой, {v2} не задана); `#`/`##` срезают "
                               "кратчайший/длиннейший префикс, `%`/`%%` — суффикс, `${#v}` — длина.")
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, answer_key=ak, context=PATHS[path],
                         verification="execution", checks=checks, params={"path": path})
