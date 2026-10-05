"""frontend.js.array_sort_canary — predict_output (канарейка): sort без компаратора."""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "frontend.js.array_sort_canary"


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    nums = rng.sample([1, 2, 5, 9, 10, 12, 21, 25, 100, 110, 200, 3, 30], rng.randint(4, 5))
    name = rng.choice(["prices", "scores", "durations", "sizes"])
    second = rng.choice(["desc_first", "asc_last", "copy_check"])
    lines = [f"const {name} = [{', '.join(map(str, nums))}];",
             f"const sorted = {name}.sort();",
             "console.log(sorted.join(','));"]
    lex = sorted(nums, key=str)
    if second == "desc_first":
        lines.append(f"console.log([...{name}].sort((a, b) => b - a)[0]);")
        out2 = str(max(nums))
    elif second == "asc_last":
        lines.append(f"console.log({name}.sort((a, b) => a - b).at(-1));")
        out2 = str(max(nums))
    else:
        lines.append(f"console.log(sorted === {name});")
        out2 = "true"
    code = "\n".join(lines)
    out = ",".join(map(str, lex)) + "\n" + out2
    stem = "Что выведет код в консоль (Node.js 20)? Запишите обе строки вывода."
    ak = AnswerKey(kind="output", value=out,
                   explanation="sort() без компаратора сравнивает строковые представления; sort "
                               "сортирует массив на месте и возвращает тот же массив.")
    checks = [Check(name="stdout", runner="node", program=code, expect="stdout_equals",
                    expected_stdout=out)]
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, answer_key=ak, context=name,
                         verification="execution", checks=checks, params={"second": second})
