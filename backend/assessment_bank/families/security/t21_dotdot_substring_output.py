"""security.path.t21_dotdot_substring_output — predict_output (набор t21, порог Стажёра): наивный фильтр обхода
каталога `if ".." in name` в цикле по именам файлов со счётчиком заблокированных.

Сервис выдачи файлов перед чтением с диска отсеивает имена, в которых есть подстрока «..»; пропущенные имена
печатаются в цикле, в конце — число заблокированных. Ловушки чтения: `in` по строке ищет ПОДСТРОКУ — безобидное
«report..v2.pdf» (две точки подряд в имени) блокируется так же, как «../etc/passwd»; закодированный обход
«%2e%2e/…» (или «.%2e/…») двух точек подряд не содержит и проходит фильтр; одиночные точки («.env», «a.b.csv»)
не мешают. Ключ — независимая модель (поиск двух соседних точек посимвольно) в генераторе; проверка — исполнение
показанного кода в песочнице Python.
"""
from __future__ import annotations

from assessment_bank.families._t21_kit import output_variant
from assessment_bank.gen_utils import make_rng

FAMILY_ID = "security.path.t21_dotdot_substring_output"

CTX = [("выдача вложений", "Сервис выдачи вложений защищается от обхода каталога: перед чтением файла с диска "
                           "программа проверяет имена из запросов."),
       ("загрузка отчётов", "Портал выгрузки отчётов принимает имя файла в параметре запроса; перед открытием "
                            "файла программа проверяет имена из журнала запросов."),
       ("статика сайта", "Веб-сервер отдаёт статические файлы по имени из адреса; фильтр перед чтением с диска "
                         "проверяет имена из журнала обращений."),
       ("архив документов", "Электронный архив документов открывает файл по имени из формы; перед открытием "
                            "программа проверяет имена из заявок."),
       ("резервные копии", "Панель администратора скачивает резервные копии по имени файла; перед чтением "
                           "программа проверяет имена из запросов.")]
TRAVERSAL = ["../etc/passwd", "../../app/.env", "img/../../config.yml", "docs/../../secret.key",
             "../../../root/.ssh/id_rsa", "..%2f..%2fetc%2fshadow", "files/../db.sqlite"]
DOUBLE_DOT = ["report..v2.pdf", "backup..2026.tar", "notes...txt", "photo..jpg", "draft..final.docx",
              "act..signed.pdf", "price..list.xlsx"]
ENCODED = ["%2e%2e/etc/passwd", "%2e%2e%2fconfig.php", ".%2e/.env", "%2E%2E/admin.db", "%2e%2e/%2e%2e/id_rsa",
           ".%2e/.%2e/web.config"]
NORMAL = ["invoice.pdf", "avatar.png", "logs/app.log", ".htaccess", "report.v2.pdf", "data/2026.10.csv",
          "contract_17.docx", "scan.01.jpg", "readme.md"]
NAMES = [("names", "name", "blocked"), ("files", "f", "denied"), ("paths", "p", "rejected"),
         ("requested", "fn", "blocked")]


def _has_dotdot(s: str) -> bool:
    """Независимая модель `".." in s`: есть ли две точки подряд (посимвольно)."""
    return any(s[i] == "." and s[i + 1] == "." for i in range(len(s) - 1))


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    ctx, stem = rng.choice(CTX)
    k = rng.choice([5, 5, 6])
    n_dd = 2 if k == 6 and rng.random() < 0.3 else 1
    n_enc = 2 if rng.random() < 0.35 else 1
    n_trav = rng.choice([1, 2])
    n_norm = k - n_dd - n_enc - n_trav
    if n_norm < 1:
        n_trav, n_norm = 1, k - n_dd - n_enc - 1
    names = (rng.sample(TRAVERSAL, n_trav) + rng.sample(DOUBLE_DOT, n_dd) + rng.sample(ENCODED, n_enc)
             + rng.sample(NORMAL, n_norm))
    for _ in range(100):
        rng.shuffle(names)
        if not _has_dotdot(names[-1]) or rng.random() < 0.3:
            break
    lv, iv, cv = rng.choice(NAMES)
    show = rng.choice(["plain", "label"])
    label = rng.choice(["ok", "serve", "open"])
    pr_pass = f"print({iv})" if show == "plain" else f'print("{label}", {iv})'
    code = (f"{lv} = [{', '.join(chr(34) + n + chr(34) for n in names)}]\n"
            f"{cv} = 0\n"
            f"for {iv} in {lv}:\n"
            f'    if ".." in {iv}:\n'
            f"        {cv} += 1\n"
            "    else:\n"
            f"        {pr_pass}\n"
            f'print("{cv}:", {cv})')
    passed = [n for n in names if not _has_dotdot(n)]
    blocked = len(names) - len(passed)
    out_lines = [n if show == "plain" else f"{label} {n}" for n in passed] + [f"{cv}: {blocked}"]
    out = "\n".join(out_lines)
    dd = [n for n in names if n in DOUBLE_DOT]
    enc = [n for n in names if n in ENCODED]
    expl = (f"`\"..\" in {iv}` ищет подстроку из двух точек подряд. Заблокированы {blocked}: "
            + ", ".join(f"«{n}»" for n in names if _has_dotdot(n))
            + f"; среди них {'безобидное имя' if len(dd) == 1 else 'безобидные имена'} "
            f"{', '.join('«' + n + '»' for n in dd)} — две точки подряд внутри имени (ложное срабатывание). "
            f"Проходят и печатаются по порядку: {', '.join('«' + n + '»' for n in passed)}; среди них "
            f"{'закодированный обход' if len(enc) == 1 else 'закодированные обходы'} "
            f"{', '.join('«' + n + '»' for n in enc)} — «%2e» станет точкой только после декодирования, а в самой "
            f"строке двух точек подряд нет. Вывод:\n{out}")
    return output_variant(FAMILY_ID, seed, stem=stem, code=code, out=out, explanation=expl, context=ctx,
                          params={"names": names, "show": show}, language="python")
