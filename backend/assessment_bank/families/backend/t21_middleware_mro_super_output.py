"""backend.http.t21_middleware_mro_super_output — predict_output (набор t21, порог Senior): MRO (C3) и super()
в ромбовидном наследовании.

Обработчик API собран из классов-«прослоек» (auth, cache, log …), каждая добавляет свою метку и вызывает
super().handle(). Ловушки: super() идёт к следующему классу в MRO экземпляра, а не к родителю из объявления класса
(в ромбе прослойка вызывает «соседа»); прослойка без вызова super обрывает цепочку (ответ из кэша); тот же метод
у экземпляра другого класса идёт по другой цепочке. Ключ — независимая линеаризация C3 и обход цепочки в
генераторе; проверка — исполнение показанного кода в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "backend.http.t21_middleware_mro_super_output"

CTX = ["API заказов", "API профилей", "API каталога", "API платежей", "API доставки"]
POOL = ["Auth", "Cache", "Log", "Retry", "Gzip", "Metrics", "Trace", "Quota"]


def _c3(cls: str, bases: dict[str, list[str]]) -> list[str]:
    if not bases[cls]:
        return [cls]
    seqs = [_c3(b, bases) for b in bases[cls]] + [list(bases[cls])]
    res = [cls]
    while True:
        seqs = [s for s in seqs if s]
        if not seqs:
            return res
        for s in seqs:
            head = s[0]
            if not any(head in t[1:] for t in seqs):
                break
        else:
            raise ValueError("C3: нет линеаризации")
        res.append(head)
        seqs = [s[1:] if s[0] == head else s for s in seqs]


def _chain(start: str, bases: dict[str, list[str]], defines: dict[str, bool], calls_super: dict[str, bool]) -> list[str]:
    out = []
    for cls in _c3(start, bases):
        if not defines[cls]:
            continue
        out.append(cls.lower())
        if not calls_super[cls]:
            break
    return out


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx = rng.choice(CTX)
    m1, m2, m3 = rng.sample(POOL, 3)
    base_name = rng.choice(["Base", "Handler", "Core", "Endpoint"])
    top = rng.choice(["Api", "View", "Route", "Service"])
    meth = rng.choice(["handle", "process", "dispatch", "run"])
    template = rng.choice(["flat", "deep", "side"])
    if template == "flat":      # три прослойки от Base, Api наследует от всех трёх в случайном порядке
        decl = [(m1, [base_name]), (m2, [base_name]), (m3, [base_name])]
        api_bases = rng.sample([m1, m2, m3], 3)
        probe = api_bases[0]
    elif template == "deep":    # m2 наследует m1, Api(m2, m3)
        decl = [(m1, [base_name]), (m2, [m1]), (m3, [base_name])]
        api_bases = [m2, m3]
        probe = m2
    else:                       # m3 наследует m2, Api(m1, m3)
        decl = [(m1, [base_name]), (m2, [base_name]), (m3, [m2])]
        api_bases = [m1, m3]
        probe = rng.choice([m1, m3])
    bases = {base_name: [], top: api_bases}
    bases.update({n: b for n, b in decl})
    api_defines = rng.random() < 0.6
    defines = {base_name: True, top: api_defines, m1: True, m2: True, m3: True}
    calls_super = {base_name: False, top: True, m1: True, m2: True, m3: True}
    mro_api = _c3(top, bases)
    # иногда одна прослойка (не первая в MRO) отвечает сама, без super — «ответ из кэша»
    if rng.random() < 0.5:
        stopper = rng.choice([c for c in mro_api[2:] if c not in (base_name, top)] or [mro_api[1]])
        calls_super[stopper] = False
    lines = [f"class {base_name}:", f"    def {meth}(self):", f'        return ["{base_name.lower()}"]']
    for name, bs in decl:
        ret = (f'        return ["{name.lower()}"] + super().{meth}()' if calls_super[name]
               else f'        return ["{name.lower()}"]')
        lines += [f"class {name}({', '.join(bs)}):", f"    def {meth}(self):", ret]
    if api_defines:
        lines += [f"class {top}({', '.join(api_bases)}):", f"    def {meth}(self):",
                  f'        return ["{top.lower()}"] + super().{meth}()']
    else:
        lines += [f"class {top}({', '.join(api_bases)}):", "    pass"]
    lines += [f'print(" > ".join({top}().{meth}()))', f'print(" > ".join({probe}().{meth}()))']
    code = "\n".join(lines)
    c1 = _chain(top, bases, defines, calls_super)
    c2 = _chain(probe, bases, defines, calls_super)
    out = f"{' > '.join(c1)}\n{' > '.join(c2)}"
    stop_note = [c for c in decl if not calls_super[c[0]]]
    expl = (f"MRO {top} (C3): {', '.join(mro_api)}, object. super() в каждой прослойке ведёт к следующему классу в "
            f"MRO экземпляра, поэтому цепочка {top}: {' > '.join(c1)}"
            + (f" — {stop_note[0][0]} не вызывает super и обрывает её" if stop_note and stop_note[0][0].lower() in c1
               else "")
            + f". У экземпляра {probe} свой MRO: {', '.join(_c3(probe, bases))}, object — цепочка {' > '.join(c2)}.")
    stem = (f"«{ctx}»: обработчик запроса собран из классов-прослоек, каждая добавляет свою метку в ответ; программа "
            "печатает, через какие прослойки прошёл запрос.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"template": template, "bases": api_bases, "probe": probe, "method": meth}, language="python")
