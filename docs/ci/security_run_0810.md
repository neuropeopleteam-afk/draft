# Проверки безопасности: журнал локального прогона (08.10.2026, ветка feat/security)

Те же три проверки выполняет задание `security` в `.github/workflows/ci.yml` (команды ниже — из него). Дополняет журнал
[security_run_0710.md](security_run_0710.md): после него закрыта находка по банку заданий (pytest), прогон повторён с
чистым окружением приложения вместо общего `.venv`.

Инструменты (скачаны заново, версии и контрольные суммы — как в CI): gitleaks 8.28.0 (архив
`gitleaks_8.28.0_linux_x64.tar.gz`, sha256 `a65b5253807a68ac0cafa4414031fd740aeb55f54fb7e55f386acb52e6a840eb` — проверен
командой `sha256sum -c`), pip-audit 2.9.0 в отдельном окружении, `actionlint` 1.7.12, Python 3.12, npm из общего
`node_modules`. Чистые окружения создавались утилитой `uv` (установка всех зависимостей приложения заняла 9 с).

## 1. gitleaks — секреты в истории и рабочем дереве

```bash
gitleaks git --no-banner --redact=100 --config .gitleaks.toml .   # 207 коммитов (все ссылки репозитория), 13,5 МБ, 1,4 с
gitleaks dir --no-banner --redact=100 --config .gitleaks.toml .   # рабочее дерево, 5,6 МБ, 0,4 с
```

Итог: `no leaks found` и для истории, и для дерева. Исключения — в `.gitleaks.toml` (разбор — в журнале 07.10, раздел 1):
шаблон `.env.example` (пустая `JWT_SECRET=` и следующая строка), вендорные файлы Swagger UI / ReDoc, lock-файлы npm,
тестовая строка `test-secret-not-for-prod`.

## 2. pip-audit — зависимости Python

```bash
cd backend
python -m venv "$TMP/app" && "$TMP/app/bin/pip" install --upgrade pip && "$TMP/app/bin/pip" install -r requirements.txt -r requirements-dev.txt
pip-audit --strict --progress-spinner off --path "$TMP/app/lib/python3.12/site-packages"
pip-audit --strict --progress-spinner off --no-deps --disable-pip -r requirements.txt -r requirements-dev.txt
pip-audit --strict --progress-spinner off --no-deps --disable-pip -r assessment_bank/BANK_requirements.txt
```

| Проверка | Пакетов | Уязвимостей |
|---|---:|---|
| окружение приложения (requirements + dev, с транзитивными, `pip` 26.2.1) | 84 | 0 |
| пины `requirements.txt` + `requirements-dev.txt` | 23 | 0 |
| пины банка `assessment_bank/BANK_requirements.txt` (pytest 9.1.1) | 5 | 0 |
| контроль: пины банка до правки (pytest 8.3.3) | 5 | 1 — PYSEC-2026-1845, исправлено в 9.0.3 |
| дополнительно: окружение банка по `requirements.txt` источника (с Django 5.2.17 и транзитивными) | 16 | 0 |

Что изменилось с 07.10:

- Находка по банку закрыта: `pytest` поднят с 8.3.3 до 9.1.1 в источнике банка (репозиторий банка, ветка
  `chore/pytest-9`, коммит `9c28a52`: `requirements.txt`, `pyproject.toml`, строка в `README.md`) и в копии банка в
  платформе (`backend/assessment_bank/BANK_requirements.txt`, `BANK_README.md`). Версия 9.1.1 совпадает с
  `requirements-dev.txt` платформы.
- Тесты банка под pytest 9.1.1 (сервер проверок, `remote-bank … pytest`, Python 3.12.13): 363 passed за 480 с.
- Предупреждение при подготовке окружения на сервере проверок (общий файл ограничений ещё содержит `pytest==8.3.3`)
  не помешало: прогон шёл на pytest 9.1.1 (в заголовке pytest: `pytest-9.1.1`).
- Прошлая находка по `pip 25.0.1` относилась к общему локальному `.venv`, а не к зависимостям приложения; в чистом
  окружении (как в CI, где выполняется `pip install --upgrade pip`) уязвимостей нет.

Важно при следующей синхронизации банка (`tools/sync_bank.py` переписывает `BANK_requirements.txt` из источника): сначала
влить `chore/pytest-9` в основную ветку банка, иначе копия вернётся к pytest 8.3.3 и шаг pip-audit в CI снова упадёт.

## 3. npm audit — фронтенд

```bash
cd frontend
npm audit --omit=dev --audit-level=high   # порог CI: код выхода 0
npm audit                                  # полная картина, включая dev-инструменты сборки
```

Результат тот же, что 07.10 (`package-lock.json` не менялся):

- Production (`--omit=dev`): 0 high / critical, 2 moderate — `react-router` и `react-router-dom` 6.30.6
  (GHSA-wrjc-x8rr-h8h6 — открытый редирект через обратную косую черту в `<Link>` и `useNavigate`; GHSA-337j-9hxr-rhxg —
  внедрение конструктора при SSR-гидрации `deserializeErrors()`). Исправление — только мажор `react-router-dom` 7.18.4.
  Принято до отдельной задачи: SSR не используется, в `navigate()` и `<Link>` попадают только пути из кода, а не из
  пользовательского ввода. Порог CI (`high`) проходит.
- Все зависимости (включая dev): 11 — 6 high, 5 moderate (цепочки `tailwindcss` 3.4.19 и `vite` 5.4.21: `micromatch`,
  `braces`, `esbuild` и др.). Это инструменты сборки и dev-сервера, в поставку не попадают; исправление — мажоры
  `tailwindcss` 4 и `vite` 8, нужна переделка конфигурации и проверка сборки. В CI не блокируют (`--omit=dev`), выводятся
  в сводку запуска.

## 4. Линтер workflow

`actionlint` 1.7.12 на `.github/workflows/ci.yml` — без замечаний. `shellcheck` локально не установлен, поэтому
`run`-блоки задания `security` им не проверялись (в CI его запускает задание проверки workflow).

## Итог

| Проверка | Результат локально | Блокирует CI |
|---|---|---|
| gitleaks (история + дерево) | чисто с `.gitleaks.toml` | да, при любой находке |
| pip-audit: окружение приложения, пины бэкенда и dev | чисто | да |
| pip-audit: банк заданий (пины, pytest 9.1.1) | чисто | да |
| npm audit production, порог high | 0 high, 2 moderate (react-router, принято до отдельной задачи) | нет (moderate ниже порога) |

Не проверялось: фактический запуск задания в GitHub Actions (репозиторий не опубликован); выкладка на сервер этих
проверок не касается.
