"""backend.config.t21_config_shallow_copy_output — predict_output (набор t21, порог Middle): псевдонимы и копии
словаря конфигурации — присваивание, поверхностная и глубокая копия.

Два клиента собирают свою конфигурацию из общего DEFAULTS разными способами (присваивание-псевдоним, dict(...),
.copy(), {**...}, copy.deepcopy) и меняют её: перезаписывают число, дописывают в вложенный список кодов для повтора
или заменяют список новым. Ловушка (одна неочевидная семантика): поверхностная копия копирует только верхний
уровень — вложенный список общий с DEFAULTS, и append через копию виден в DEFAULTS; псевдоним меняет сам DEFAULTS;
замена списка новым объектом связь разрывает. Ключ — независимая модель ссылок (номера объектов) в генераторе;
проверка — исполнение показанного кода в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "backend.config.t21_config_shallow_copy_output"

CTX = [("клиент платёжного шлюза", "payments"), ("клиент сервиса доставки", "delivery"),
       ("клиент поиска", "search"), ("клиент CRM", "crm"), ("клиент геокодера", "geo")]
COPIES = {"alias": "{src}", "dict": "dict({src})", "copy": "{src}.copy()", "unpack": "{{**{src}}}",
          "deep": "copy.deepcopy({src})"}


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, svc = rng.choice(CTX)
    timeout = rng.choice([3, 5, 10])
    codes = rng.sample([429, 500, 502, 503, 504], 2)
    for _ in range(100):
        ka = rng.choice(["dict", "copy", "unpack", "alias"])
        kb = rng.choice(["deep", "dict", "copy", "unpack"])
        if ka != kb:
            break
    a, b = rng.sample(["fast", "slow", "bulk", "main", "backup"], 2)
    new_t = rng.choice([t for t in (1, 2, 15, 30) if t != timeout])
    extra = rng.sample([c for c in (408, 425, 429, 500, 502, 503, 504) if c not in codes], 2)
    op_b = rng.choice(["append", "append", "rebind"])
    # модель ссылок: объекты-словари и объекты-списки по номерам
    dicts = {"D": {"timeout": timeout, "retry_on": "L0"}}
    lists = {"L0": list(codes)}

    def make_copy(kind: str, src: str, new_name: str) -> str:
        if kind == "alias":
            return src
        d = dict(dicts[src])
        if kind == "deep":
            nl = f"L{len(lists)}"
            lists[nl] = list(lists[d["retry_on"]])
            d["retry_on"] = nl
        dicts[new_name] = d
        return new_name

    ra = make_copy(ka, "D", "A")
    rb = make_copy(kb, "D", "B")
    lines = []
    if "deep" in (ka, kb):
        lines.append("import copy")
    lines.append(f"DEFAULTS = {{\"timeout\": {timeout}, \"retry_on\": {codes}}}")
    lines.append(f"{a} = " + COPIES[ka].format(src="DEFAULTS"))
    lines.append(f"{b} = " + COPIES[kb].format(src="DEFAULTS"))
    lines.append(f'{a}["timeout"] = {new_t}')
    lines.append(f'{a}["retry_on"].append({extra[0]})')
    dicts[ra]["timeout"] = new_t
    lists[dicts[ra]["retry_on"]].append(extra[0])
    if op_b == "append":
        lines.append(f'{b}["retry_on"].append({extra[1]})')
        lists[dicts[rb]["retry_on"]].append(extra[1])
    else:
        lines.append(f'{b}["retry_on"] = {b}["retry_on"] + [{extra[1]}]')
        nl = f"L{len(lists)}"
        lists[nl] = lists[dicts[rb]["retry_on"]] + [extra[1]]
        dicts[rb]["retry_on"] = nl
    lines.append('print(DEFAULTS["timeout"], DEFAULTS["retry_on"])')
    lines.append(f'print({b}["timeout"], len({b}["retry_on"]))')
    code = "\n".join(lines)
    dd = dicts["D"]
    l_def = lists[dd["retry_on"]]
    db = dicts[rb]
    out = (f"{dd['timeout']} [{', '.join(str(x) for x in l_def)}]\n"
           f"{db['timeout']} {len(lists[db['retry_on']])}")
    kind_ru = {"alias": "присваивание — тот же объект, что DEFAULTS", "dict": "dict(...) — поверхностная копия",
               "copy": ".copy() — поверхностная копия", "unpack": "{**...} — поверхностная копия",
               "deep": "deepcopy — полная копия со своим списком"}
    expl = (f"{a}: {kind_ru[ka]}; {b}: {kind_ru[kb]}. Поверхностная копия копирует только верхний уровень: число "
            f"timeout у копии своё, а список retry_on — общий с DEFAULTS, поэтому append через копию виден в DEFAULTS"
            + ("; запись через псевдоним меняет сам DEFAULTS" if ka == "alias" else "")
            + ("; присваивание нового списка (+ [...]) создаёт новый объект и связь разрывает" if op_b == "rebind"
               else "")
            + f". Итог: DEFAULTS = timeout {dd['timeout']}, retry_on {l_def}; у {b} timeout {db['timeout']}, "
              f"в retry_on {len(lists[db['retry_on']])} кода.")
    stem = (f"«{ctx}» ({svc}): два профиля настроек собираются из общего словаря DEFAULTS и меняются под свои "
            "нужды.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"a": ka, "b": kb, "op_b": op_b}, language="python")
