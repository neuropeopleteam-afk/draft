"""backend.django.migration_default_bug — find_bug: `default=timezone.now()` вместо `default=timezone.now`.

Значение по умолчанию вычислено один раз при импорте модели: makemigrations запекает в миграцию константу
`datetime.datetime(...)`, при каждом следующем запуске makemigrations появляется новая миграция (константа
изменилась), а у всех записей, созданных в одном запуске приложения, одинаковое время (версия 2: условие
и разбор говорят именно об этом, а не о «записях за день»). Исправление — передать вызываемый объект
(`timezone.now`), который Django вызывает при создании каждой записи и сериализует в миграции по имени.
Один подтип; варьируются контекст, набор и порядок полей, строки-ловушки (`auto_now_add`, `default=date.today`,
`default=list`, `default="new"`), позиция дефектной строки. Проверка исполнением настоящего Django:
две записи с паузой между ними должны получить разные значения, а default поля — быть вызываемым.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, changed_lines, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "backend.django.migration_default_bug"

# (контекст, модель, поле с дефектом, прочие поля-кандидаты)
CONTEXTS = [("интернет-магазин", "Order", "created_at",
             ['number = models.CharField(max_length=20, unique=True)', 'total = models.DecimalField(max_digits=10, decimal_places=2)',
              'status = models.CharField(max_length=10, default="new")']),
            ("поддержка", "Ticket", "opened_at",
             ['subject = models.CharField(max_length=200)', 'priority = models.IntegerField(default=3)',
              'tags = models.JSONField(default=list)']),
            ("бронирование", "Booking", "requested_at",
             ['guest = models.CharField(max_length=100)', 'nights = models.PositiveIntegerField(default=1)',
              'paid = models.BooleanField(default=False)']),
            ("склад", "Shipment", "registered_at",
             ['track = models.CharField(max_length=32)', 'weight_kg = models.FloatField(default=0.0)',
              'notes = models.TextField(blank=True, default="")']),
            ("клиника", "Visit", "scheduled_at",
             ['patient = models.CharField(max_length=100)', 'room = models.CharField(max_length=5, default="A1")',
              'confirmed = models.BooleanField(default=False)'])]
TRAPS = ["updated_at = models.DateTimeField(auto_now=True)",
         "added = models.DateTimeField(auto_now_add=True)",
         "due_date = models.DateField(default=date.today)",
         "expires_at = models.DateTimeField(null=True, blank=True)"]

TEST = '''

import time as _t
from django.db import connection as _c
with _c.schema_editor() as se:
    se.create_model({M})
_field = {M}._meta.get_field("{fld}")
_a = {M}.objects.create({first})
_t.sleep(0.02)
_b = {M}.objects.create({second})
ok = callable(_field.default) and getattr(_a, "{fld}") != getattr(_b, "{fld}")
print("RESULT: PASS" if ok else "RESULT: FAIL")
'''


def _model(M, fields: list[str]) -> str:
    lines = ["from datetime import date", "", "from django.db import models", "from django.utils import timezone",
             "", "", f"class {M}(models.Model):"] + [f"    {f}" for f in fields]
    return "\n".join(lines) + "\n"


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, M, fld, extra = rng.choice(CONTEXTS)
    fields = list(extra[: rng.randint(2, 3)]) + rng.sample(TRAPS, rng.randint(1, 2))
    rng.shuffle(fields)
    pos = rng.randint(1, len(fields))  # дефектная строка не первая: первой пусть идёт обычное поле
    buggy_f = fields[:pos] + [f"{fld} = models.DateTimeField(default=timezone.now())"] + fields[pos:]
    fixed_f = fields[:pos] + [f"{fld} = models.DateTimeField(default=timezone.now)"] + fields[pos:]
    buggy, fixed = _model(M, buggy_f), _model(M, fixed_f)
    ch = changed_lines(buggy, fixed)
    assert len(ch) == 1
    key = next(iter(ch))
    # значения для обязательных полей без default
    first_parts, second_parts = [], []
    for f in fields:
        name = f.split(" =")[0]
        if "default=" in f or "auto_now" in f or "null=True" in f:
            continue
        if "CharField" in f or "TextField" in f:
            first_parts.append(f'{name}="x1"')
            second_parts.append(f'{name}="x2"')
        elif "DecimalField" in f:
            first_parts.append(f'{name}="1.00"')
            second_parts.append(f'{name}="2.00"')
        else:
            first_parts.append(f"{name}=1")
            second_parts.append(f"{name}=2")
    test = TEST.format(M=M, fld=fld, first=", ".join(first_parts), second=", ".join(second_parts))
    checks = [Check(name="buggy_fails", runner="django", program=buggy + test, expect="fail"),
              Check(name="fixed_passes", runner="django", program=fixed + test, expect="pass",
                    embeds_display_code=False)]
    day = rng.randint(1, 28)
    hh, mm = rng.randint(8, 19), rng.randint(0, 59)
    stem = (f"Django ({ctx}). После `makemigrations` в миграции оказалась константа "
            f"`default=datetime.datetime(2026, 10, {day}, {hh}, {mm}, 41, 338211, tzinfo=datetime.timezone.utc)`. "
            f"При каждом повторном `makemigrations` без правок модели создаётся новая миграция, а все записи, "
            f"созданные после запуска приложения, получают одно и то же значение `{fld}` — момент запуска. "
            f"В модели одна строка задаёт значение по умолчанию неверно. Укажите её номер.")
    why = (f"Строка {key}: `timezone.now()` со скобками вызывается один раз, при импорте модуля моделей "
           f"(запуск приложения), и в `default` попадает готовая дата, а не функция. Поэтому `makemigrations` "
           f"записывает в миграцию эту константу; при следующем запуске значение другое, Django считает поле "
           f"изменённым и создаёт новую миграцию. Все записи, созданные в этом запуске, получают одно и то же время. "
           f"Нужно передать вызываемый объект `timezone.now` без скобок: Django вызывает его при создании "
           f"каждой записи, а в миграции сохраняет ссылку `django.utils.timezone.now`.")
    ak = AnswerKey(kind="line", value=key, explanation=why)
    return build_variant(FAMILY_ID, seed, stem=stem, code=buggy, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, defect_type="default_called_at_import",
                         display_code_note="После показанного кода исполняется проверка: таблица создаётся, "
                                           "две записи с паузой должны получить разные значения поля.",
                         params={"fixed_code": fixed, "field": fld})
