# Материалы сдачи «Драфт» (ТЗ п. 5.2)

| Что сдаётся (ТЗ 5.2) | Файл |
|---|---|
| Описание решения и инструкция по запуску | [`/README.md`](../../README.md) |
| Техническая документация (п. 3.4), doc / pdf | [`DOCUMENTATION.pdf`](DOCUMENTATION.pdf), [`DOCUMENTATION.docx`](DOCUMENTATION.docx), исходный текст [`DOCUMENTATION.md`](DOCUMENTATION.md) |
| Презентация | [`docs/presentation/Draft_presentation.pdf`](../presentation/Draft_presentation.pdf), [`.pptx`](../presentation/Draft_presentation.pptx) |
| Сценарий видео | [`docs/video/SCRIPT.md`](../video/SCRIPT.md) |
| Описание API | [`docs/api/openapi.json`](../api/openapi.json), на сайте — `/api/docs` |

## Как пересобрать

```bash
python3 docs/submission/build.py          # тексты + PDF/DOCX документации + презентация PPTX/PDF
python3 docs/submission/build.py --text   # только тексты (README, DOCUMENTATION.md, SCRIPT.md)
```

Нужны: Python 3.11+, pandoc, LibreOffice (`soffice`), Node.js 20+ и Chromium из Playwright
(`npm ci --prefix docs/presentation` ставит `pptxgenjs` и `playwright`).

## Правило цифр

В материалах нет чисел, вписанных руками. Исходники — `docs/submission/src/*.md`, `docs/video/src/SCRIPT.md`,
`docs/presentation/build.mjs`; цифры подставляет `numfacts.py` только из [`docs/NUMBERS.json`](../NUMBERS.json) —
по ключу и вместе с условием измерения (на ком: симуляция / модель / люди / реальные документы, N, дата, команда
пересчёта). Если ключа нет, текст, который от него зависит, в материалы не попадает; ссылка на отсутствующий ключ вне
условного блока — ошибка сборки. Список всех подставленных цифр с ключами — приложение Б документации и
`out/facts.json`.

Кроме NUMBERS.json сборка читает из репозитория только описательные сведения: правила продукта
(`backend/app/core/config.py`), число операций API (`docs/api/openapi.json`), версии библиотек
(`backend/requirements.txt`, `frontend/package-lock.json`, Dockerfile и `docker-compose.yml`).
