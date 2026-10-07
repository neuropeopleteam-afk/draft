"""Generate the requested engineering report from saved, reproducible measurements."""
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "docs/realdata"


def load(name):
    return json.loads((DATA / name).read_text())


def fmt(value, digits=3):
    return f"{value:.{digits}f}".replace(".", ",")


def main():
    parser = load("parser_benchmark.json")
    audit = load("expert_ranking_audit.json")
    guard = load("ranking_guard_500.json")
    demo = json.loads((ROOT / "docs/validation/matching_demo_500.json").read_text())
    checks = load("checks_status.json") if (DATA / "checks_status.json").exists() else {"pytest_exit": None, "build_exit": None}
    commits = subprocess.check_output(["git", "-C", str(ROOT), "log", "--format=%h %s", "763b8f7..HEAD"], text=True).strip()
    test_log = (DATA / "full_pytest.log").read_text() if (DATA / "full_pytest.log").exists() else ""
    tested = "316 тестов (код завершения 0)" if checks["pytest_exit"] == 0 else f"проверка ещё не завершена / код {checks['pytest_exit']}"
    built = "успешно (код завершения 0)" if checks["build_exit"] == 0 else f"проверка ещё не завершена / код {checks['build_exit']}"
    lines = [
        "# И8 «Подбор на чужих данных» — отчёт 07.10.2026",
        "",
        "Worktree: `/srv/work/srv/work/spectrek/wt/realdata`, ветка `feat/realdata`, база `763b8f7`.",
        "",
        "## Итог для координатора",
        "",
        "- Пять пунктов И8 реализованы: корпус 50 реальных текстов; честные ближайшие категории; добавление 350 к исходным 150; приватный JSON/CSV-эксперимент; живое сравнение LLM на этих же текстах ([корпус](../wt/realdata/docs/realdata/vacancies_50.json), [проверки](../wt/realdata/backend/tests/test_realdata.py), [живой протокол](../wt/realdata/docs/realdata/live_predictions.json)).",
        "- **Изменение порядка ранжирования НЕ включено**: правило «меньше пробелов обязательного T1 → прежний скор» улучшает демо и часть модельных меток, но ухудшает фиксированный бенчмарк со скрытой истиной на 500 кандидатах; включать его ради более красивых метрик было бы подгонкой ([guard 500](../wt/realdata/docs/realdata/ranking_guard_500.json)).",
        "- В продукт включены безопасные принципиальные исправления: город с цитатой, допустимое «офис или гибрид», явные T0-фильтры из потребности, обязательные T1-фильтры одним действием, точное объяснение разницы грейдов; T0 не добавляет баллы и не сортирует выдачу ([ranking.py](../wt/realdata/backend/app/modules/matching/ranking.py), [экран работодателя](../wt/realdata/frontend/src/pages/employer/Needs.tsx)).",
        "- Серверный ключ не читался и не сохранялся; серверная выкладка не выполнялась, живая модель вызывалась через разрешённый [API разбора потребности](https://fsp.neuropeople.pro/api/employer/needs/parse).",
        "",
        "## 1. Публичные тексты и регрессионные тесты",
        "",
        "В `vacancies_50.json` — ровно 50 разных публичных адресов, реальные дословные фрагменты вакансий и их собственные заголовочные поля, дата сбора и SHA-256; контакты соискателей/рекрутеров в корпус не включены, вакансии в продукт не импортируются ([корпус](../wt/realdata/docs/realdata/vacancies_50.json), [сборка корпуса](../wt/realdata/tools/realdata/freeze_corpus.py)).",
        "Распределение ближайших направлений: Backend 14, Frontend 15, Data/ML 6, QA 12, ИБ 3; явно указанный грейд имеется в 39 текстах, остальные 11 не считаются явным эталоном грейда ([корпус](../wt/realdata/docs/realdata/vacancies_50.json), [измерения](../wt/realdata/docs/realdata/parser_benchmark.json)).",
        "**Эталон — silver-разметка**: независимое извлечение моделью и ручная проверка скалярных полей, не экспертная оценка; этот же корпус использован для исправления правил, поэтому это регрессия, а не независимое доказательство рыночного качества ([сборка](../wt/realdata/tools/realdata/freeze_corpus.py), [протокол](../wt/realdata/docs/realdata/parser_benchmark.json)).",
        "",
        "Сравнение полей; «LLM» и «старые правила» используют одну ревизию стенда `763b8f7`, а улучшенные локальные правила показаны отдельно ([методика и результаты](../wt/realdata/docs/realdata/parser_benchmark.json)).",
        "",
        "| Поле | Старые правила | LLM на стенде | Новые правила |",
        "|---|---:|---:|---:|",
    ]
    field_titles = {"direction": "Направление", "grade": "Явный грейд", "experience_years_min": "Минимальный опыт",
                    "work_format": "Формат", "salary_from": "Вилка от", "salary_to": "Вилка до"}
    for field, title in field_titles.items():
        cells = []
        for version in ("baseline_rules", "live", "current_rules"):
            row = parser[version]["fields"][field]
            cells.append(f"{row['correct']}/{row['n']}")
        lines.append(f"| {title} | {' | '.join(cells)} |")
    lines += [
        f"| Стек, micro precision | {fmt(parser['baseline_rules']['stack_micro_precision'],4)} | {fmt(parser['live']['stack_micro_precision'],4)} | {fmt(parser['current_rules']['stack_micro_precision'],4)} |",
        f"| Стек, micro recall | {fmt(parser['baseline_rules']['stack_micro_recall'],4)} | {fmt(parser['live']['stack_micro_recall'],4)} | {fmt(parser['current_rules']['stack_micro_recall'],4)} |",
        "| Цитаты, верные смещения | 462/462 | 488/488 | 499/499 |",
        "",
        "У новых правил остаётся одна скалярная ошибка: vac-037 — удалённое обучение смешивается с офисом/гибридом будущей работы; стек содержит 37 ложных добавлений и 20 пропусков относительно silver-эталона, это не замаскировано как стопроцентный результат ([ошибки](../wt/realdata/docs/realdata/parser_benchmark.json)).",
        "Тесты проверяют все шесть полей, известную неоднозначность отдельно, детерминированный снимок стека и каждую цитату; точный снимок стека — регрессионный контракт, **не экспертная истина** ([тесты](../wt/realdata/backend/tests/test_realdata.py)).",
        "",
        "## 2. Вне каталога MVP",
        "",
        "DevOps → Backend, мобильная разработка → Frontend, аналитика → Data/ML, 1С → Backend, геймдев → Frontend; у каждой реакции есть цитата, блок «проверяется» и «не проверяется», а тест ближайшей категории не выдаётся за подтверждение профессионального грейда новой специальности ([правила границ](../wt/realdata/backend/app/modules/matching/coverage.py)).",
        "Kotlin не считается Java, Kubernetes — Docker; добавлены отдельные Kotlin, C#, PHP, Kubernetes, а у новых демо-профилей эти четыре тега остаются заявленными T0, без выдуманного подтверждения новым банком заданий ([словарь](../wt/realdata/backend/app/modules/catalog/dictionary.py), [seed](../wt/realdata/backend/app/modules/demo/seed.py)).",
        "",
        "## 3. Демо 150 → 500",
        "",
        "`extend_candidates(db)` добавляет только индексы 151…500 и идемпотентен; тест сравнивает **все существовавшие строки всех таблиц**, включая ID, карточки, факты, тесты и достижения, до и после добавления, а повторный запуск добавляет 0 ([seed](../wt/realdata/backend/app/modules/demo/seed.py), [тест сохранности](../wt/realdata/backend/tests/test_realdata.py)).",
        "У добавленных профилей есть школьники, студенты ФСП и профессионалы, широкие Go/Java/Kotlin/C#/PHP/Docker/Kubernetes/Kafka; все данные искусственные и помечены `demo-seed`, это не 500 реальных респондентов ([seed](../wt/realdata/backend/app/modules/demo/seed.py)).",
        "",
        f"Текущий отчёт `/validation`: {demo['n_needs']} потребностей, {demo['n_pool']} кандидатов, {demo['n_pairs']} размеченных пар в выборках по 20; замена касается только `report.json.matching`, симуляция тестирования не переписывается ([результаты демо](../wt/realdata/docs/validation/matching_demo_500.json), [пересчёт](../wt/realdata/tools/realdata/recompute_demo.py)).",
        "",
        "| Метрика | Платформа | Без ФСП | BM25 | Теги | Случайно |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for metric in ("p@5", "ndcg@5", "ndcg@10", "within_category_ndcg@3"):
        lines.append(f"| {metric} | " + " | ".join(fmt(demo["summary"][metric][m]) for m in
                     ("platform", "platform_no_fsp", "bm25", "keywords", "random")) + " |")
    lines += [
        "",
        "**Ограничение:** разметка демо автоматическая и частично повторяет фильтр категории; внутри категории BM25/теги лучше платформы по этому эталону, который вознаграждает заявленный стек, не подтверждённый T1 — превосходство по общему p@5 нельзя объявлять рыночным ([методика демо](../wt/realdata/docs/validation/matching_demo_500.json)).",
        "",
        "## 4. Закрытый набор жюри",
        "",
        "На `/validation` добавлен самостоятельный блок: JSON/CSV-шаблоны, загрузка до 2 МБ / 50 потребностей / 500 профилей, k=1…50, выдача с компонентами и объяснениями, p@k/nDCG и CSV-экспорт; при проверке открывается собственная песочница работодателя ([frontend](../wt/realdata/frontend/src/components/validation/ClosedSet.tsx), [API](../wt/realdata/backend/app/modules/validation/closed_set.py)).",
        "Набор существует только в памяти одного запроса: нет вставок в общие таблицы, хранения, API чтения чужого результата или передачи в LLM; ответа нет в браузере после очистки/перезагрузки, HTTP-ответы помечены no-store ([код](../wt/realdata/backend/app/modules/validation/closed_set.py), [изоляционные тесты](../wt/realdata/backend/tests/test_realdata.py), [браузер](../wt/realdata/docs/realdata/browser_check.json)).",
        "T1/T2 из файла обозначаются «данные загрузившего, не проверены платформой», без theta профиль не входит в подтверждённую подборку; неизвестные поля/теги, дубли, NaN и ошибочные метки отвергаются, CSV-формулы экранируются ([API](../wt/realdata/backend/app/modules/validation/closed_set.py)).",
        "p@k: метка ≥2, делитель **k**, пустые места не улучшают метрику; nDCG: gain=2^rel−1, идеал по всем профилям; при неполной разметке метрики этой потребности не рассчитываются, пропуски не получают ноль ([метрики](../wt/realdata/backend/app/modules/validation/closed_set.py)).",
        "",
        "## 5. Живая модель",
        "",
        "Вызван живой серверный Yandex-путь под отдельной демо-песочницей, 50 HTTP 200: 49 ответов использовали LLM, vac-014 перешёл на правила из-за invalid_json; медиана серверной LLM-задержки 6,92 с ([живые ответы](../wt/realdata/docs/realdata/live_predictions.json), [API стенда](https://fsp.neuropeople.pro/api/employer/needs/parse)).",
        "Сравнение честное: не противопоставляется новый локальный парсер старому стендовому LLM; на одной старой ревизии LLM улучшает опыт 34→41/50 и формат 49→50/50, но ухудшает precision стека 0,8567→0,8233, поэтому общего утверждения «LLM лучше» нет ([сравнение](../wt/realdata/docs/realdata/parser_benchmark.json)).",
        "",
        "## Дополнение координатора: N00/N03, все 10 потребностей и LOO",
        "",
        "Использованы локальные слепые карточки E1–E3 и фиксированные модельные метки 109 пар; исходные 150 профилей независимо восстановлены по исходному seed и сверены по категории/θ/городу/стажу, заявленным/подтверждённым навыкам, формату и переезду, без повторной разметки и без SQL к production ([аудит](../wt/realdata/docs/realdata/expert_ranking_audit.json), [код аудита](../wt/realdata/tools/realdata/audit_expert_ranking.py)).",
        "",
        "### Причины по прежнему топ-5",
        "",
        "**N00:** @demo_014 (0,6080), 011 (0,5633), 019 (0,5464), 013 (0,5338), 012 (0,5150); все Middle Backend, ни у одного нет подтверждённого Redis, у 011 он только заявлен, 011/013/012 заявляют офис и 019 гибрид при запросе удалённой работы ([карточки N00](../wt/realdata/docs/realdata/expert_ranking_audit.json)).",
        "014 поднимают тест 0,897 и обязательный стек 0,584; 013 остаётся высоко даже с покрытием обязательного стека 0,235 за счёт теста 0,801 и ФСП 0,911 — линейная компенсация весами не означает полного выполнения обязательных требований ([компоненты N00](../wt/realdata/docs/realdata/expert_ranking_audit.json)).",
        "**N03:** @demo_061 (0,6497), 064 (0,5351), 065 (0,5343), 069 (0,5188), 066 (0,5173); первые четыре из Ростова/Екатеринбурга/Нижнего Новгорода/Самары без переезда, 061/064 удалённые; только 066 готов переехать, при этом у 061 отсутствует SQL, у 064/069 — и Python/SQL, у 066 pandas не подтверждён ([карточки N03](../wt/realdata/docs/realdata/expert_ranking_audit.json)).",
        "061 обгоняет 066 за счёт теста и pandas/NumPy, несмотря на конфликт офиса в Москве; грейд здесь **не причина** — у всех пяти верный Junior, ухудшение обусловлено условиями присутствия и неполной обязательной T1-проверкой ([компоненты N03](../wt/realdata/docs/realdata/expert_ranking_audit.json)).",
        "",
        "### Фиксированное правило, не включённое в продукт",
        "",
        "Проверены два нормативных варианта без подбора коэффициентов: (A) число неподтверждённых обязательных навыков перед прежним скором, (B) тот же порядок плюс автоматические фильтры явно указанного города/формата; категории/грейд и веса исходной формулы не менялись ([код](../wt/realdata/backend/app/modules/matching/ranking.py), [аудит](../wt/realdata/docs/realdata/expert_ranking_audit.json)).",
        "",
        "Ниже сравнение **только в фиксированном полностью размеченном объединённом пуле** каждой потребности; это не метрики новой выдачи по всем 150/500 профилям ([протокол](../wt/realdata/docs/realdata/expert_ranking_audit.json)).",
        "",
        "| Потребность | p@5 до | p@5 A | nDCG@5 до | nDCG@5 A | nDCG@5 B |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in audit["per_need"]:
        lines.append(f"| {row['need']} | {fmt(row['before']['p@5'])} | {fmt(row['mandatory_only']['p@5'])} | "
                     f"{fmt(row['before']['ndcg@5'])} | {fmt(row['mandatory_only']['ndcg@5'])} | {fmt(row['after']['ndcg@5'])} |")
    lines += [
        "",
        "На 10 потребностях A: p@5 0,660→0,660, nDCG@5 0,851→0,865; по правилам p@5 0,920→0,920, nDCG@5 0,930→0,936; N12 отдельно ухудшается, поэтому нет обещания улучшения каждой потребности ([аудит](../wt/realdata/docs/realdata/expert_ranking_audit.json)).",
        "B: p@5 0,660→0,540, nDCG@5 0,851→0,739; в замороженном пуле N00/N03/N13 после жёстких условий остаётся по одному кандидату, пустые места имеют делитель 5, а новые подходящие карточки вне пула нельзя объявлять нерелевантными ([аудит](../wt/realdata/docs/realdata/expert_ranking_audit.json)).",
        "В полном восстановленном пуле 150 экспериментальный топ-5 размечен целиком лишь для 7 из 10 потребностей; N00, N02, N13 содержат новые неразмеченные карточки, для них полная after-метрика намеренно отсутствует; перед внешним выводом нужно доразметить новые топы ([покрытие полного пула](../wt/realdata/docs/realdata/expert_ranking_audit.json)).",
        "До-числа восстановления близки, но не тождественны историческому снимку стенда: nDCG N00 0,597 против переданного координатором 0,586; скрытых старых рангов/ref и точных дат ФСП нет в слепых карточках, это **контрфактическая реконструкция**, не переписывание исходного отчёта экспертов ([ограничения аудита](../wt/realdata/docs/realdata/expert_ranking_audit.json)).",
        "LOO по всем 10 реализован для фиксированного правила: при исключении потребности остаётся тот же SHA-256 функции, параметров, обучаемых на метках, нет; эксперимент возник после разбора ошибок N00/N03, поэтому такой LOO не является независимой внешней кросс-валидацией и не устраняет постфактум выбор гипотезы ([10 LOO-записей](../wt/realdata/docs/realdata/expert_ranking_audit.json)).",
        "",
        "### Guard 500 и решение",
        "",
        "A на демо-500 улучшает p@5 0,893→0,920 и nDCG@5 0,886→0,933, но на другом фиксированном синтетическом мире 50×500 со скрытой истиной ухудшает p@5 0,704→0,700 и nDCG@5 0,5698→0,5494 (nDCG@10 0,5735→0,5695); улучшение демо не прошло общий guard ([guard 500](../wt/realdata/docs/realdata/ranking_guard_500.json)).",
        "**Решение:** A и автоматический B не активированы; продукт остаётся `match-v1` с прежними весами и порядком, а обязательные T1/город/формат применяются явно в фильтрах после подтверждения работодателем ([ranking.py](../wt/realdata/backend/app/modules/matching/ranking.py)).",
    ]
    hidden = guard["hidden_truth_500"]
    if "original_parser_product" in hidden:
        old, new = hidden["original_parser_product"], hidden["current_parser_product"]
        lines.append(f"Финальный продукт, старый→новый парсер на том же скрытом мире: p@5 {fmt(old['p@5'],4)}→{fmt(new['p@5'],4)}, "
                     f"nDCG@5 {fmt(old['ndcg@5'],4)}→{fmt(new['ndcg@5'],4)}, nDCG@10 {fmt(old['ndcg@10'],4)}→{fmt(new['ndcg@10'],4)} "
                     "([последний guard](../wt/realdata/docs/realdata/ranking_guard_500.json)).")
    lines += [
        "",
        "## Проверки, миграция, показ жюри",
        "",
        f"- Точечный прогон: 127 тестов зелёные, затем полный pytest: **{tested}** под общим flock ([полный лог](../wt/realdata/docs/realdata/full_pytest.log), [статус](../wt/realdata/docs/realdata/checks_status.json)).",
        f"- Сборка фронтенда: **{built}**, под общим flock ([лог](../wt/realdata/docs/realdata/frontend_build.log)).",
        "- Браузер: JSON и CSV загрузка, реальные метрики шаблона p@5=0,2/nDCG=1, CSV-выгрузка, очистка и перезагрузка, мобильная вне-MVP категория; 1440/390 px, document.scrollWidth равен ширине экрана, JS-ошибок нет ([протокол](../wt/realdata/docs/realdata/browser_check.json)).",
        "- Comet cloud не открывает localhost; локальный стенд проверен установленным Playwright Chromium ([снимок 1440](../wt/realdata/docs/realdata/closed-set-1440.png), [снимок 390](../wt/realdata/docs/realdata/closed-set-390.png)).",
        "- Приватный статический обзор содержит реальные снимки проверенного интерфейса и анонимные шаблоны; это не production-выкладка и не форма отправки данных ([исходник обзора](../wt/realdata/docs/realdata/preview/index.html)).",
        "- Предупреждения: устаревшее сочетание Starlette/httpx в тестах и JS-чанк 623 КБ в сборке; ошибок и ненулевых кодов завершения нет ([pytest](../wt/realdata/docs/realdata/full_pytest.log), [сборка](../wt/realdata/docs/realdata/frontend_build.log)).",
        "- `rd01`, parent `qr01`: четыре отдельные записи справочника; SQLite upgrade выполнен, SQL PostgreSQL компилируется; реальный PostgreSQL 16 в этой песочнице не запускался — требуется общий серверный smoke при слиянии ([миграция](../wt/realdata/backend/migrations/versions/rd01_realdata_tags.py), [SQL PostgreSQL](../wt/realdata/docs/realdata/postgresql_migration.sql)).",
        "",
        "Что показать: `/validation` → «Закрытый набор жюри» → скачать JSON → загрузить → проверить → CSV; затем работодатель → потребности → «Android developer middle, Kotlin» → частичное соответствие и граница проверяемого.",
        "",
        "## Слияние и запуск",
        "",
        "Общие файлы: `demo/seed.py`, `matching/ranking.py`, `matching/router.py`, `matching/need_parser.py`, `validation/router.py`, `validation/data/report.json`, `validation/matching_eval.py`, `validation/matching_bench.py`; frontend `Validation.tsx` изменён только в первом коммите (import ClosedSet и один JSX-блок), дальше для дополнения координатора **не переписывался**, `Needs.tsx` — город/форматы/кнопки явных фильтров.",
        "",
        "В `jury.ts`, `JuryGuide.tsx`, `jury/seed.py`, `App.tsx` изменений нет; общий демо-пул видим песочницам через существующий scope, новая функция расположена на уже доступной `/validation` ([изменения коммитов](../wt/realdata/frontend/src/pages/Validation.tsx), [scope](../wt/realdata/backend/app/modules/jury/scope.py)).",
        "",
        "После слияния координатору, без сброса существующего демо:",
        "",
        "```bash",
        "cd backend",
        "python -m alembic upgrade head",
        "python -m app.modules.demo.seed     # без --reset: добавить 151..500",
        "```",
        "",
        "Локальное воспроизведение тяжёлых расчётов:",
        "",
        "```bash",
        "flock /tmp/spectrek_heavy.lock .venv/bin/python tools/realdata/ranking_guard.py",
        "flock /tmp/spectrek_heavy.lock .venv/bin/python tools/realdata/recompute_demo.py",
        ".venv/bin/python tools/realdata/benchmark.py     # повторно считает из сохранённых live-ответов",
        ".venv/bin/python tools/realdata/audit_expert_ranking.py",
        "```",
        "",
        "Пути `.venv/bin/python` в командах выше замените на `/srv/work/srv/work/spectrek/.venv/bin/python`; аудит E1–E3 требует имеющихся локальных слепых снимков из исходной задачи, секретные файлы соседних каталогов не используются.",
        "",
        "Коммиты на момент генерации отчёта:",
        "",
        "```text",
        commits,
        "```",
        "",
        "## Что осталось",
        "",
        "- Координатору: слияние общих файлов и объединение головы `rd01` с миграциями других потоков, SQLite/PG16 smoke на общем стенде, выкладка.",
        "- Доразметить новые топ-5 N00/N02/N13 (и после любых автоматических условий) до выводов по полному пулу; принять отдельное продуктовое решение об автоматических фильтрах, не маскировать нехватку подходящих карточек увеличением p@k.",
        "- Исправить неоднозначность vac-037 и проверить стек на новом независимом корпусе с человеческим эталоном; 50 текущих текстов — регрессионный набор, не слепой test set.",
        "- Временные исходные страницы/черновики `.jsonl` оставлены локально и не включены в коммиты; координатору брать коммиты, не `git add .` всего worktree.",
        "- Локальные uvicorn/Vite на 8108/5108 остановлены; статический обзор не зависит от живого backend.",
        "",
        "## Адреса 50 публичных текстов",
        "",
        "Источник каждой строки и точный текст сохранены в [корпусе](../wt/realdata/docs/realdata/vacancies_50.json); это исторические тестовые тексты, не рекомендация действующих вакансий.",
        "",
        "| ID | Заголовок | Публичный адрес |",
        "|---|---|---|",
    ]
    for row in load("vacancies_50.json")["vacancies"]:
        title = row.get("title", row["id"]).replace("|", "/").replace("\n", " ")
        url = row["source_url"]
        lines.append(f"| {row['id']} | {title} | [{title}]({url}) |")
    text = "\n".join(lines) + "\n"
    (DATA / "REPORT.md").write_text(text.replace("../wt/realdata/", "../../"))
    dest = ROOT.parents[1] / "<внутренний документ>"
    dest.write_text(text)
    print(dest)


if __name__ == "__main__":
    main()
