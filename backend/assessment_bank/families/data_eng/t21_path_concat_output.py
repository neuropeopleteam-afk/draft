"""data_eng.etl.t21_path_concat_output — predict_output (набор t21, порог Стажёра): сборка пути к файлу партиции
конкатенацией строк, дополнение нулём только одной части даты.

Программа собирает путь `таблица/ГГГГ-ММ-ДД/part-N.csv` сложением строк; нулём дополняется только одна часть даты
(месяц или день — зависит от варианта), вторая идёт через str() как есть. Ловушка чтения: «дописать» недостающий
ноль у второй части. Ключ — независимая сборка строки в генераторе; проверка — исполнение кода в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "data_eng.etl.t21_path_concat_output"

CTX = [("выгрузка заказов в озеро данных", "orders"), ("архив кликов", "clicks"), ("снимки остатков", "stock"),
       ("логи платёжного шлюза", "payments"), ("события приложения", "app_events"), ("отзывы о товарах", "reviews")]


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, table = rng.choice(CTX)
    year = rng.choice([2025, 2026])
    pad_month = rng.random() < 0.5
    month = rng.randint(1, 12)
    day = rng.randint(1, 28)
    if rng.random() < 0.7:  # чаще всего вторая (недополненная) часть — однозначная
        if pad_month:
            day = rng.randint(1, 9)
        else:
            month = rng.randint(1, 9)
    part = rng.randint(0, 12)
    ext = rng.choice(["csv", "json", "parquet"])
    if pad_month:
        var, val, other, other_val = "mm", "month", "day", day
    else:
        var, val, other, other_val = "dd", "day", "month", month
    m_expr = "mm" if pad_month else "str(month)"
    d_expr = "dd" if not pad_month else "str(day)"
    code = (f"year, month, day = {year}, {month}, {day}\n"
            f"part = {part}\n"
            f"{var} = str({val})\n"
            f"if {val} < 10:\n"
            f"    {var} = \"0\" + {var}\n"
            f"path = \"{table}/\" + str(year) + \"-\" + {m_expr} + \"-\" + {d_expr}"
            f" + \"/part-\" + str(part) + \".{ext}\"\n"
            f"print(path)")
    mm = (f"{month:02d}" if pad_month else str(month))
    dd = (f"{day:02d}" if not pad_month else str(day))
    out = f"{table}/{year}-{mm}-{dd}/part-{part}.{ext}"
    padded_val = month if pad_month else day
    pad_txt = (f"{val} = {padded_val} < 10, поэтому {var} = «0{padded_val}»" if padded_val < 10
               else f"{val} = {padded_val} ≥ 10, дополнять не нужно")
    expl = (f"Нулём дополняется только {'месяц' if pad_month else 'день'}: {pad_txt}; "
            f"{'день' if pad_month else 'месяц'} подставляется через str({other}) как есть — «{other_val}»"
            + (" без ведущего нуля" if other_val < 10 else "") + f"; номер части тоже без дополнения. Путь: «{out}».")
    stem = (f"Задача «{ctx}» пишет файлы по дневным партициям; программа собирает путь к файлу.")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"pad": var, "month": month, "day": day, "part": part}, language="python")
