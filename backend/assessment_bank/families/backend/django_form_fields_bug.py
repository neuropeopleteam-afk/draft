"""backend.django.form_fields_bug — find_bug: ModelForm с fields = "__all__" (массовое присвоение).

Форма редактирования профиля принимает все поля модели, включая служебные (роль, баланс, флаг
проверки): злоумышленник добавляет их в POST и повышает себе права. Один подтип дефекта; варьируются
контекст, имена, порядок опций Meta (labels, widgets, help_texts), служебные строки; строка дефекта
не постоянна. Исправление — явный список полей в той же строке (или exclude служебных).
Проверка исполнением настоящего Django (SQLite в памяти): POST со служебными полями не меняет их,
а обычное редактирование проходит и не сбрасывает флаги.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, changed_lines, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "backend.django.form_fields_bug"

# (контекст, модель, форма, функция, редактируемые поля, служебное bool, служебное int)
CONTEXTS = [("профиль пользователя", "Profile", "ProfileForm", "update_profile", ["display_name", "bio"],
             "is_moderator", "balance"),
            ("карточка продавца", "Seller", "SellerForm", "edit_seller", ["shop_name", "about"],
             "is_verified", "commission"),
            ("аккаунт игрока", "Player", "PlayerForm", "save_player", ["nickname", "motto"],
             "is_admin", "coins"),
            ("резюме кандидата", "Resume", "ResumeForm", "update_resume", ["headline", "summary"],
             "is_featured", "boost_level"),
            ("страница автора", "Writer", "WriterForm", "edit_writer", ["pen_name", "bio"],
             "is_editor", "royalty")]


# подписи первого поля формы — по смыслу поля (всегда четыре, чтобы не менять выбор по seed)
LABELS = {"display_name": ["Имя", "Как вас показывать", "Публичное имя", "Отображаемое имя"],
          "shop_name": ["Название", "Название магазина", "Как называется магазин", "Название витрины"],
          "nickname": ["Имя", "Игровое имя", "Ник", "Псевдоним"],
          "headline": ["Должность", "Заголовок", "Желаемая должность", "Заголовок резюме"],
          "pen_name": ["Имя", "Псевдоним", "Литературный псевдоним", "Как вас подписывать"]}


def _code(c, buggy: bool, meta_extra: list[str], meta_first: bool, doc: bool, sizes: tuple[int, int, int],
          clean: bool) -> tuple[str, int]:
    _ctx, model, form, fn, edit, flag, num = c
    fields_line = ('        fields = "__all__"' if buggy else
                   "        fields = [" + ", ".join(f'"{f}"' for f in edit) + "]")
    meta = ["    class Meta:"]
    opts = [f"        model = {model}", fields_line] + meta_extra
    meta += opts if meta_first else ([opts[0]] + meta_extra + [fields_line])
    lines = ["from django import forms", "from django.db import models", "", "",
             f"class {model}(models.Model):",
             f"    {edit[0]} = models.CharField(max_length={sizes[0]})",
             f"    {edit[1]} = models.CharField(max_length={sizes[1]}, blank=True)",
             f"    {flag} = models.BooleanField(default=False)",
             f"    {num} = models.IntegerField(default={sizes[2]})", "", "",
             f"class {form}(forms.ModelForm):"]
    if doc:
        lines.append(f'    """Форма редактирования: {_ctx}."""')
    if clean:
        meta += ["", f"    def clean_{edit[0]}(self):", f'        return self.cleaned_data["{edit[0]}"].strip()']
    lines += meta + ["", "",
                     f"def {fn}(obj, post_data):",
                     f"    form = {form}(post_data, instance=obj)",
                     "    if form.is_valid():",
                     "        form.save()",
                     "        return True",
                     "    return False"]
    key = next(i for i, l in enumerate(lines, 1) if l.strip().startswith("fields = "))
    return "\n".join(lines) + "\n", key


def _harness(code: str, c) -> str:
    _ctx, model, form, fn, edit, flag, num = c
    return code + "\n\n" + "\n".join([
        "def __bank_test():",
        "    from django.db import connection as _c",
        "    with _c.schema_editor() as se:",
        f"        se.create_model({model})",
        f"    user = {model}.objects.create({edit[0]}='alice', {edit[1]}='', {flag}=False, {num}=10)",
        f"    ok = {fn}(user, {{'{edit[0]}': 'alice2', '{edit[1]}': 'hi', '{flag}': 'on', '{num}': '999999'}})",
        "    user.refresh_from_db()",
        f"    attack_blocked = ok and user.{edit[0]} == 'alice2' and user.{flag} is False and user.{num} == 10",
        f"    staff = {model}.objects.create({edit[0]}='bob', {edit[1]}='', {flag}=True, {num}=5)",
        f"    ok2 = {fn}(staff, {{'{edit[0]}': 'bob', '{edit[1]}': 'new bio'}})",
        "    staff.refresh_from_db()",
        f"    normal_ok = ok2 and staff.{edit[1]} == 'new bio' and staff.{flag} is True and staff.{num} == 5",
        "    return attack_blocked and normal_ok",
        "",
        "",
        "print('RESULT: PASS' if __bank_test() else 'RESULT: FAIL')",
    ]) + "\n"


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    c = rng.choice(CONTEXTS)
    ctx, model, form, fn, edit, flag, num = c
    sizes = (rng.choice([30, 40, 50, 64, 80]), rng.choice([200, 300, 500, 1000]), rng.choice([0, 1, 10]))
    label = rng.choice(LABELS[edit[0]])
    extra_pool = [f'        labels = {{"{edit[0]}": "{label}"}}',
                  f'        help_texts = {{"{edit[1]}": "До {sizes[1]} символов"}}',
                  f'        widgets = {{"{edit[1]}": forms.Textarea(attrs={{"rows": 3}})}}']
    meta_extra = rng.sample(extra_pool, rng.randint(0, 2))
    meta_first = rng.random() < 0.5
    doc = rng.random() < 0.5
    clean = rng.random() < 0.5
    buggy, key = _code(c, True, meta_extra, meta_first, doc, sizes, clean)
    fixed, _ = _code(c, False, meta_extra, meta_first, doc, sizes, clean)
    assert changed_lines(buggy, fixed) == {key}
    checks = [Check(name="buggy_fails", runner="django", program=_harness(buggy, c), expect="fail"),
              Check(name="fixed_passes", runner="django", program=_harness(fixed, c), expect="pass",
                    embeds_display_code=False)]
    stem = (f"Django, {ctx}: пользователь редактирует только `{edit[0]}` и `{edit[1]}`. После релиза "
            f"в журнале нашли запросы, где обычные пользователи меняли себе `{flag}` и `{num}`, добавив "
            f"эти поля в POST-запрос к `{fn}`. Укажите номер строки, которую достаточно исправить одной правкой, чтобы ошибка ушла.")
    why = (f"Строка {key}: fields = \"__all__\" делает редактируемыми все поля модели, включая {flag} и {num}; "
           f"ModelForm сохранит всё, что пришло в POST. Нужен явный список: fields = "
           f"[\"{edit[0]}\", \"{edit[1]}\"] (или exclude служебных полей).")
    ak = AnswerKey(kind="line", value=key, explanation=why)
    return build_variant(FAMILY_ID, seed, stem=stem, code=buggy, answer_key=ak, context=ctx,
                         verification="execution", checks=checks, defect_type="mass_assignment",
                         params={"fixed_code": fixed, "meta_first": meta_first})
