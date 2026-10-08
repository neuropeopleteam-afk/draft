# Проверки безопасности: журнал локального прогона (07.10.2026, ветка feat/security)

Те же три проверки выполняет задание `security` в `.github/workflows/ci.yml`. Инструменты локально:
`~/.local/bin/gitleaks` 8.28.0 (архив `gitleaks_8.28.0_linux_x64.tar.gz`, sha256
`a65b5253807a68ac0cafa4414031fd740aeb55f54fb7e55f386acb52e6a840eb` — совпадает с официальным
`gitleaks_8.28.0_checksums.txt`), `~/.local/pipaudit-venv/bin/pip-audit` 2.9.0, npm из общего `node_modules`.

## 1. gitleaks — секреты в истории и рабочем дереве

```bash
cd <корень репозитория>
~/.local/bin/gitleaks git --no-banner --redact=100 --config .gitleaks.toml .   # 184 коммита, 12.8 МБ, 4 с
~/.local/bin/gitleaks dir --no-banner --redact=100 --config .gitleaks.toml .   # рабочее дерево, 11.7 МБ, 2 с
```

Без `.gitleaks.toml` (стандартные правила): 1 находка в истории и 1 в дереве — одна и та же, `generic-api-key`,
`.env.example:11`, коммит 7aff1ac6. Разбор: строка `JWT_SECRET=` в шаблоне пустая, регулярное выражение правила
допускает перевод строки после `=` и захватывает следующую строку `JWT_TTL_MINUTES=720` как «секрет». Настоящих
секретов нет. В `.gitleaks.toml` добавлено исключение именно на пару «пустая переменная + следующая переменная»
(`regexTarget = "match"`), а не на файл: контрольная проверка с непустым значением `JWT_SECRET=<hex64>` в таком же
шаблоне даёт `leaks found: 1`, то есть реальный секрет в шаблоне по-прежнему ловится.

Прочие исключения в `.gitleaks.toml`: вендорные файлы Swagger UI / ReDoc (`backend/app/static/apidocs/*.js|css`),
lock-файлы npm, строка `test-secret-not-for-prod` из `backend/tests/conftest.py`. Демо-пароли в
`backend/app/modules/jury/seed.py` стандартными правилами не задеваются, исключений для них нет.

Итог с конфигурацией: `no leaks found` и для истории, и для дерева.

## 2. pip-audit — зависимости Python

```bash
cd backend
PA=~/.local/pipaudit-venv/bin/pip-audit
$PA --progress-spinner off -r requirements.txt -r requirements-dev.txt --no-deps --disable-pip   # пины
$PA --progress-spinner off -r assessment_bank/BANK_requirements.txt --no-deps --disable-pip       # пины банка
$PA --progress-spinner off --path /srv/work/srv/work/spectrek/.venv/lib/python3.12/site-packages # окружение
```

| Проверка | Пакетов | Уязвимостей | Детали |
|---|---|---|---|
| `requirements.txt` + `requirements-dev.txt` (пины) | 23 | 0 | — |
| `assessment_bank/BANK_requirements.txt` (пины) | 5 | 1 | `pytest 8.3.3`: PYSEC-2026-1845 (CVE-2025-71176, GHSA-6w46-j5rx-g56g), исправлено в 9.0.3 |
| установленное окружение `.venv` (с транзитивными) | 84 | 6, все в `pip 25.0.1` | PYSEC-2026-196, -1795, -1796, -2875, -2876, -3721; исправлены в pip 25.3…26.2 |

Выводы:
- Рантайм API и dev-зависимости вместе с транзитивными — чисто. `pip` — инструмент окружения, не зависимость
  приложения; в образе и в CI он обновляется (`python -m pip install --upgrade pip` в задании `security`), в общем
  локальном `.venv` его стоит обновить тем же способом.
- Банк заданий: `pytest==8.3.3` в `BANK_requirements.txt` уязвим (разбор архива тестов, не рантайм). Файл — копия
  `requirements.txt` из репозитория банка (`tools/sync_bank.py` переписывает его при синхронизации), поэтому поднимать
  версию нужно в источнике банка (`bank/requirements.txt`, коммит 8683dc4) до `pytest==9.1.1` (как в
  `requirements-dev.txt`), прогнав тесты банка, и затем выполнить синхронизацию. В этой ветке версия не менялась —
  тесты банка под pytest 9 не прогонялись; до этого задание `security` в CI на пине банка будет падать.
  **Закрыто 08.10:** pytest поднят до 9.1.1, тесты банка 363 passed — см. [security_run_0810.md](security_run_0810.md).

Замечание: в CI окружение приложения ставится в отдельный venv и проверяется через `--path`, чтобы в результат не
попали зависимости самого pip-audit. Локально воспроизвести этот шаг в чистом venv не удалось — установка колёс
numpy/scipy/natasha в песочнице шла дольше 10 минут; проверено на общем `.venv` проекта (таблица выше).

## 3. npm audit — фронтенд

```bash
cd frontend
npm audit --omit=dev --audit-level=high   # порог CI
npm audit                                  # полная картина, включая dev
```

- Production (`--omit=dev`, 187 пакетов): 0 high/critical, 2 moderate — `react-router` / `react-router-dom` 6.30.6
  (GHSA-wrjc-x8rr-h8h6 открытый редирект через обратную косую черту в `<Link>`/`useNavigate`; GHSA-337j-9hxr-rhxg
  внедрение конструктора при SSR-гидрации `deserializeErrors()`). Исправление — только мажор `react-router-dom 7.18.4`
  (`npm audit fix --force`), новые пакеты в этом потоке не ставим. Предложение: отдельной задачей перейти на 7.x
  (API совместим с 6.4 data-router, нужна проверка `Link`/`navigate` по проекту). Принято до тех пор: SSR не
  используется, а `navigate()`/`<Link>` получают только пути из кода, не из пользовательского ввода, так что оба
  вектора на приложение не действуют. Порог CI (`high`) проходит: код выхода 0.
- Все зависимости (включая dev): 11 (6 high, 5 moderate) — цепочка `tailwindcss 3.4.19` → `micromatch`/`braces`/
  `chokidar`/`postcss-selector-parser`/`fast-glob` и `vite 5.4.21` (`esbuild 0.21.5`, путь-траверсал `.map`, обход
  `server.fs.deny` на Windows). Это инструменты сборки и dev-сервера, в поставку не попадают; исправление — мажоры
  `tailwindcss 4.3.3` и `vite 8.3.3`, что требует переписывания конфигурации Tailwind и проверки сборки. В CI
  они не блокируют (`--omit=dev`), но выводятся в сводку задания (`npm audit` целиком в `GITHUB_STEP_SUMMARY`).

## Итог

| Проверка | Результат локально | Блокирует CI |
|---|---|---|
| gitleaks (история + дерево) | чисто с `.gitleaks.toml` | да, при любой находке |
| pip-audit: бэкенд + dev (пины и окружение) | чисто (кроме `pip` самого venv) | да |
| pip-audit: банк заданий (пины) | `pytest 8.3.3` — 1 уязвимость | да, пока не поднята версия в источнике банка |
| npm audit production, порог high | 0 high, 2 moderate | нет (moderate ниже порога) |
