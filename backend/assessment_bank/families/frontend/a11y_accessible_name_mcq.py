"""frontend.a11y.accessible_name_mcq — mcq_concept: доступное имя элемента (ARIA, accname).

Ключ проверяется исполнением: показанный HTML разбирается html.parser в песочнице Python, а
доступное имя вычисляется по подмножеству алгоритма W3C Accessible Name Computation 1.2:
aria-labelledby (прямо указанные узлы берутся даже скрытыми) → aria-label → <label for> для
поля / содержимое для кнопки (без aria-hidden и hidden, с alt изображений) → title.
Генератор считает ключ отдельно, по таблице приоритетов.
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_options, make_rng
from assessment_bank.schema import AnswerKey, Check

FAMILY_ID = "frontend.a11y.accessible_name_mcq"

PHRASES = {
    "заказы": ["Удалить заказ", "Отменить заказ", "Детали заказа", "Повторить заказ", "Архив заказов",
               "Оплатить заказ", "Список заказов", "Скачать чек", "Связаться с курьером",
               "Изменить адрес"],
    "профиль": ["Сменить аватар", "Изменить профиль", "Выйти из профиля", "Настройки профиля",
                "Сохранить профиль", "Удалить аватар", "Скрыть профиль", "Сменить пароль",
                "Привязать телефон", "Скачать резюме"],
    "корзина": ["Добавить в корзину", "Очистить корзину", "Открыть корзину", "Товар в корзине",
                "Убрать из корзины", "Перейти к оплате", "Сохранить корзину", "Применить промокод",
                "Выбрать доставку", "Отложить товар"],
    "почта": ["Новое письмо", "Удалить письмо", "Ответить всем", "Переслать письмо",
              "Отметить прочитанным", "Архивировать", "Пометить важным", "Переместить в спам",
              "Прикрепить файл", "Открыть вложение"],
}
INPUT_PHRASES = {
    "заказы": ["Номер заказа", "Дата доставки", "Комментарий курьеру", "Адрес доставки",
               "Промокод", "Телефон получателя", "Поиск по заказам", "Имя получателя",
               "Время доставки", "Этаж и квартира"],
    "профиль": ["Электронная почта", "Имя пользователя", "Новый пароль", "Город", "Телефон",
                "Дата рождения", "Ссылка на портфолио", "Фамилия", "Должность", "О себе"],
    "корзина": ["Количество", "Промокод", "Поиск товара", "Индекс", "Комментарий к заказу",
                "Подарочная карта", "Адрес пункта выдачи", "Сумма бонусов", "Телефон для связи",
                "Имя покупателя"],
    "почта": ["Кому", "Тема письма", "Поиск по письмам", "Копия", "Подпись", "Скрытая копия",
              "Имя отправителя", "Адрес для ответа", "Название папки", "Текст письма"],
}

CHECKER = r'''
from html.parser import HTMLParser
VOID = {"img", "input", "br", "meta", "link", "hr"}


class Node:
    def __init__(self, tag, attrs, parent):
        self.tag, self.attrs, self.parent, self.children = tag, dict(attrs), parent, []


class Parser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.root = Node("#root", [], None)
        self.cur = self.root
        self.all = []

    def handle_starttag(self, tag, attrs):
        n = Node(tag, [(k, v if v is not None else "") for k, v in attrs], self.cur)
        self.cur.children.append(n)
        self.all.append(n)
        if tag not in VOID:
            self.cur = n

    def handle_endtag(self, tag):
        node = self.cur
        while node is not self.root and node.tag != tag:
            node = node.parent
        if node is not self.root:
            self.cur = node.parent

    def handle_data(self, data):
        self.cur.children.append(data)


def norm(s):
    return " ".join(s.split())


def hidden(n):
    return n.attrs.get("aria-hidden") == "true" or "hidden" in n.attrs


def content(n):
    parts = []
    for ch in n.children:
        if isinstance(ch, str):
            parts.append(ch)
        elif hidden(ch):
            continue
        elif ch.tag == "img":
            parts.append(" " + ch.attrs.get("alt", "") + " ")
        else:
            parts.append(content(ch))
    return "".join(parts)


def accessible_name(el, p):
    by_id = {n.attrs["id"]: n for n in p.all if "id" in n.attrs}
    ids = el.attrs.get("aria-labelledby", "").split()
    text = " ".join(t for t in (norm(content(by_id[i])) for i in ids if i in by_id) if t)
    if text:
        return text
    if el.attrs.get("aria-label", "").strip():
        return norm(el.attrs["aria-label"])
    if el.tag == "input":
        labels = [n for n in p.all if n.tag == "label" and n.attrs.get("for") == el.attrs.get("id")]
        text = " ".join(t for t in (norm(content(l)) for l in labels) if t)
        if text:
            return text
    if el.tag == "button":
        text = norm(content(el))
        if text:
            return text
    return norm(el.attrs.get("title", "")) or "(пусто)"


p = Parser()
p.feed(HTML)
target = [n for n in p.all if n.tag in ("button", "input")][0]
print(accessible_name(target, p))
'''


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    area = rng.choice(sorted(PHRASES))
    kind = rng.choice(["button", "button", "input"])
    pool = list((PHRASES if kind == "button" else INPUT_PHRASES)[area])
    rng.shuffle(pool)
    take = iter(pool)
    for _ in range(200):
        rng.shuffle(pool)
        take = iter(pool)
        uid = rng.choice(["del", "edit", "main", "card", "row", "form"]) + str(rng.randint(2, 9))
        f = {"lb": rng.random() < 0.45, "lb_missing": rng.random() < 0.25,
             "lb_hidden": rng.random() < 0.3, "al": rng.random() < 0.6,
             "al_empty": rng.random() < 0.2, "title": rng.random() < 0.5}
        if kind == "button":
            f.update(text=rng.random() < 0.6, sr=rng.random() < 0.45, ah=rng.random() < 0.45,
                     img=rng.random() < 0.3)
        else:
            f.update(label=rng.random() < 0.75)
        # целевое правило выбирается равномерно, флаги подгоняются под него
        want = rng.choice(["lb", "al", "native", "title"])
        if want == "lb":
            f.update(lb=True, lb_missing=False)
        else:
            if f["lb"]:
                f["lb_missing"] = True
            if want == "al":
                f.update(al=True, al_empty=False)
            elif f["al"]:
                f["al_empty"] = True
            if want == "native":
                if kind == "button":
                    if not (f["text"] or f["sr"] or f["img"]):
                        f["text"] = True
                else:
                    f.update(label=True, title=True, lb=True, lb_missing=True)
            if want == "title":
                f.update(title=True, lb=True, lb_missing=True)
                if kind == "button":
                    f.update(text=False, sr=False, img=False, ah=True)
                else:
                    f.update(label=False, ph=True)
        t = {k: next(take) for k in ("lb", "al", "title", "text", "sr", "ah", "img", "label")}
        lines, attrs = [], []
        if f["lb"]:
            hid = " hidden" if f["lb_hidden"] else ""
            lines.append(f'<span id="title-{uid}"{hid}>{t["lb"]}</span>')
            ref = f"title-{uid}x" if f["lb_missing"] else f"title-{uid}"
            attrs.append(f'aria-labelledby="{ref}"')
        if kind == "input" and f["label"]:
            lines.append(f'<label for="f-{uid}">{t["label"]}</label>')
        if f["al"]:
            attrs.append('aria-label=""' if f["al_empty"] else f'aria-label="{t["al"]}"')
        if f["title"]:
            attrs.append(f'title="{t["title"]}"')
        if f.get("ph"):
            attrs.append(f'placeholder="{t["text"]}"')
        rng.shuffle(attrs)
        a = (" " + " ".join(attrs)) if attrs else ""
        if kind == "input":
            lines.append(f'<input id="f-{uid}" type="text"{a}>')
        else:
            lines.append(f'<button type="button" class="btn"{a}>')
            inner = ['  <svg class="icon" aria-hidden="true" viewBox="0 0 24 24"></svg>']
            if f["img"]:
                inner.append(f'  <img src="/icons/{uid}.png" alt="{t["img"]}">')
            if f["sr"]:
                inner.append(f'  <span class="visually-hidden">{t["sr"]}</span>')
            if f["ah"]:
                inner.append(f'  <span aria-hidden="true">{t["ah"]}</span>')
            if f["text"]:
                inner.append(f"  {t['text']}")
            rng.shuffle(inner)
            lines += inner + ["</button>"]
        # ключ по таблице приоритетов
        lb_ok = f["lb"] and not f["lb_missing"]
        al_ok = f["al"] and not f["al_empty"]
        content = []
        if kind == "button":
            for ln in lines:
                s = ln.strip()
                if 'aria-hidden="true"' in s or s.startswith("<button") or s == "</button>":
                    continue
                if s.startswith("<img"):
                    content.append(t["img"])
                elif s.startswith('<span class="visually-hidden">'):
                    content.append(t["sr"])
                elif not s.startswith("<span id=") and not s.startswith("<"):
                    content.append(t["text"])
        native = " ".join(content) if kind == "button" else (t["label"] if f["label"] else "")
        if lb_ok:
            correct, rule = t["lb"], "aria-labelledby"
        elif al_ok:
            correct, rule = t["al"], "aria-label"
        elif native:
            correct, rule = native, ("содержимое кнопки" if kind == "button" else "label for")
        elif f["title"]:
            correct, rule = t["title"], "title"
        else:
            continue
        cands = []
        if f["lb"]:
            cands.append(t["lb"])
        if f["al"] and not f["al_empty"]:
            cands.append(t["al"])
        if f["title"]:
            cands.append(t["title"])
        if native:
            cands.append(native)
        if kind == "button":
            vis = [t["text"]] if f["text"] else []
            if f["ah"]:
                cands.append(" ".join([t["ah"]] + vis))
                cands.append(t["ah"])
            if f["sr"] and vis:
                cands.append(" ".join(vis))
            if f["img"]:
                cands.append(f"{uid}.png")
            if f["text"] and native != t["text"]:
                cands.append(t["text"])
        else:
            if f["label"]:
                cands.append(t["label"])
            if f.get("ph"):
                cands.append(t["text"])
        cands.append("(пусто)")
        distr = []
        for c in cands:
            if c != correct and c not in distr:
                distr.append(c)
        if len(distr) >= 3 and rule in ("aria-labelledby", "aria-label", "содержимое кнопки",
                                        "label for", "title"):
            break
    else:
        raise RuntimeError("не собрался вариант")
    weak = {"(пусто)", f"{uid}.png"}
    strong = [d for d in distr if d not in weak]
    rng.shuffle(strong)
    distr = strong + [d for d in distr if d in weak]
    code = "\n".join(lines)
    opts, key = make_options(rng, (correct, None), [(d, None) for d in distr[:3]])
    what = "кнопка" if kind == "button" else "текстовое поле"
    stem = (f"Фрагмент разметки (раздел «{area}»). Какое доступное имя (accessible name) получит "
            f"{what} — что объявит экранный диктор при фокусе? Класс `visually-hidden` скрывает "
            f"элемент только визуально (стандартный приём «только для экранных дикторов»).")
    lb_note = ("; прямо указанный элемент используется, даже если он скрыт атрибутом hidden"
               if f["lb_hidden"] else "")
    notes = {"aria-labelledby": "aria-labelledby имеет наивысший приоритет" + lb_note,
             "aria-label": "aria-label используется, если aria-labelledby отсутствует или "
                           "ссылается на несуществующий id",
             "содержимое кнопки": "имя кнопки берётся из содержимого: текст, alt изображений "
                                  "и visually-hidden-текст входят, aria-hidden — нет",
             "label for": "поле получает имя из связанного <label for>",
             "title": "title — запасной источник имени, когда других нет (для поля он "
                      "приоритетнее placeholder)"}
    traps = []
    if f["al"] and f["al_empty"]:
        traps.append("пустой aria-label пропускается")
    if f["lb"] and f["lb_missing"]:
        traps.append("ссылка aria-labelledby на несуществующий id игнорируется")
    if kind == "button" and f.get("ah"):
        traps.append("текст с aria-hidden=\"true\" не входит в имя")
    tail = (" Кроме того: " + "; ".join(traps) + ".") if traps else ""
    ak = AnswerKey(kind="option", value=key,
                   explanation=f"Сработало правило «{rule}»: {notes[rule]}.{tail}")
    program = "HTML = r'''" + code + "'''\n" + CHECKER
    checks = [Check(name="accname", runner="python", program=program, expect="stdout_equals",
                    expected_stdout=correct)]
    return build_variant(FAMILY_ID, seed, stem=stem, code=code, options=opts, answer_key=ak,
                         context=area + ":" + kind, verification="execution", checks=checks,
                         params={"rule": rule, "flags": f, "kind": kind})
