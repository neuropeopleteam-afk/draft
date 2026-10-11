"""data_eng.orch.catchup_runs_mcq — mcq_concept: запуски DAG Airflow по прошедшим интервалам после включения.

Семантика Airflow 2 (документация «DAG Runs → Data Interval, Catchup»; CronDataIntervalTimetable): запуск создаётся
по интервалу данных [начало, конец) после того, как интервал завершился; logical_date запуска — НАЧАЛО интервала.
Первый интервал начинается с первого тика расписания не раньше start_date. catchup=True — после включения
создаются запуски по всем завершённым интервалам; catchup=False — только по последнему завершённому.
Подтипы: catchup_true, catchup_false. Дистракторы — фиксированный состав по подтипу: посчитан текущий
незавершённый интервал (N + 1 и logical_date = начало текущего), logical_date = момент запуска (конец интервала),
catchup проигнорирован (1 вместо N или N вместо 1). Время — UTC. Ключ — исполнение показанного кода DAG с
заглушкой airflow и моделью тиков расписания в песочнице Python.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from assessment_bank.gen_utils import build_variant, make_options, make_rng, plural
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "data_eng.orch.catchup_runs_mcq"

CTX = [("ежедневная витрина продаж", "sales_mart"), ("выгрузка логов в хранилище", "logs_to_dwh"),
       ("сверка остатков склада", "stock_recon"), ("пересчёт признаков клиентов", "client_features"),
       ("загрузка курсов валют", "fx_rates"), ("отчёт по обращениям в поддержку", "support_report")]
# расписание → (период в часах, смещение тика от полуночи в часах)
SCHED = {"@daily": (24, 0), "@hourly": (1, 0), "0 */6 * * *": (6, 0), "0 3 * * *": (24, 3)}

STUB = '''import sys
import types
from datetime import datetime, timedelta

CFG = {}


class DAG:
    def __init__(self, dag_id, start_date, schedule, catchup, **kw):
        CFG.update(start=start_date, schedule=schedule, catchup=catchup)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class EmptyOperator:
    def __init__(self, task_id, **kw):
        self.task_id = task_id

    def __rshift__(self, other):
        return other


m_air = types.ModuleType("airflow")
m_air.DAG = DAG
m_ops = types.ModuleType("airflow.operators")
m_empty = types.ModuleType("airflow.operators.empty")
m_empty.EmptyOperator = EmptyOperator
sys.modules.update({"airflow": m_air, "airflow.operators": m_ops, "airflow.operators.empty": m_empty})
'''

MODEL = '''

PERIOD, OFFSET = {"@daily": (24, 0), "@hourly": (1, 0), "0 */6 * * *": (6, 0), "0 3 * * *": (24, 3)}[CFG["schedule"]]


def is_tick(t):
    h = (t - t.replace(hour=0)).total_seconds() / 3600
    return t.minute == 0 and t.second == 0 and (h - OFFSET) % PERIOD == 0


t = CFG["start"]
while not is_tick(t):                       # первый тик не раньше start_date
    t += timedelta(minutes=60 - t.minute) if t.minute else timedelta(hours=1)
intervals = []
while t + timedelta(hours=PERIOD) <= NOW:   # только завершённые интервалы
    intervals.append(t)                     # logical_date = начало интервала
    t += timedelta(hours=PERIOD)
runs = intervals if CFG["catchup"] else intervals[-1:]
print(len(runs), runs[-1].strftime("%Y-%m-%d %H:%M"))
'''


def _ans(n: int, ld: datetime) -> str:
    return f"{n} {plural(n, 'запуск', 'запуска', 'запусков')}; logical_date самого позднего — {ld:%Y-%m-%d %H:%M}"


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, dag_id = rng.choice(CTX)
    sched = rng.choice(sorted(SCHED))
    period, offset = SCHED[sched]
    catchup = rng.random() < 0.5
    day = rng.randint(1, 6)
    start = datetime(2026, 10, day)
    first = start + timedelta(hours=offset)
    n = {24: rng.randint(3, 8), 6: rng.randint(3, 12), 1: rng.randint(4, 15)}[period]
    cur_start = first + timedelta(hours=period * n)            # начало текущего (незавершённого) интервала
    into = rng.randint(1, max(1, period * 60 - 1)) if period > 1 else rng.randint(1, 59)
    now = cur_start + timedelta(minutes=into)
    last = cur_start - timedelta(hours=period)                 # начало последнего завершённого
    if catchup:
        right = (n, last)
        wrong = [(n + 1, cur_start), (n, cur_start), (1, last)]
    else:
        right = (1, last)
        wrong = [(1, cur_start), (n, last), (2, cur_start)]
    texts = [_ans(*right)] + [_ans(*w) for w in wrong]
    assert len(set(texts)) == 4, texts
    code = "\n".join([
        "from datetime import datetime",
        "",
        "from airflow import DAG",
        "from airflow.operators.empty import EmptyOperator",
        "",
        f'with DAG("{dag_id}", start_date=datetime({start.year}, {start.month}, {start.day}),',
        f'         schedule="{sched}", catchup={catchup}):',
        '    extract = EmptyOperator(task_id="extract")',
        '    load = EmptyOperator(task_id="load")',
        "    extract >> load",
    ])
    opts, key = make_options(rng, (texts[0], None), [(t, None) for t in texts[1:]])
    stem = (f"DAG Airflow 2 «{ctx}» (код ниже, время — UTC) выложили и включили (unpause) {now:%Y-%m-%d} в "
            f"{now:%H:%M}. Раньше этот DAG не запускался. Сколько запусков планировщик создаст по уже прошедшим "
            "интервалам расписания (будущие тики не считаем) и какая logical_date у самого позднего из них?")
    expl = (f"Интервалы данных начинаются с первого тика не раньше start_date ({first:%Y-%m-%d %H:%M}) и длятся "
            f"{period} ч; запуск создаётся, когда интервал завершился, а logical_date — его начало. Текущий интервал "
            f"с {cur_start:%Y-%m-%d %H:%M} ещё не закончился. "
            + (f"catchup=True: запуски по всем {n} завершённым интервалам, последний — {last:%Y-%m-%d %H:%M}."
               if catchup else
               f"catchup=False: только последний завершённый интервал, logical_date {last:%Y-%m-%d %H:%M} "
               "(хотя запуск стартует сразу после включения)."))
    prog = (STUB + "\n" + code + f"\n\nNOW = datetime({now.year}, {now.month}, {now.day}, {now.hour}, {now.minute})"
            + MODEL)
    exp = f"{right[0]} {right[1]:%Y-%m-%d %H:%M}"
    checks = [Check(name="schedule_model", runner="python", program=prog, expect="stdout_equals",
                    expected_stdout=exp)]
    ak = AnswerKey(kind="option", value=key, explanation=expl)
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, options=opts, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, language="python",
                         display_code_note="Показанный код DAG исполняется дословно с заглушкой airflow; запуски "
                                           "считает модель интервалов данных",
                         params={"schedule": sched, "catchup": catchup, "n": n})
