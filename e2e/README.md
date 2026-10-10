# Сквозные сценарии жюри (Playwright)

Отдельный пакет: свои зависимости, фронтенд не затрагивает. Подробно — [docs/testing.md](../docs/testing.md).

```bash
npm ci && npx playwright install chromium            # браузер ставится в ~/.cache/ms-playwright
E2E_BASE_URL=http://127.0.0.1:8140 npx playwright test   # локальный стек (tools/ci/stack.sh up && seed)
E2E_BASE_URL=https://fsp.neuropeople.pro E2E_BASIC_USER=demo E2E_BASIC_PASSWORD=… npx playwright test
npm run report                                        # HTML-отчёт последнего прогона
```

Один прогон = своя песочница жюри (вход с `scenario: "new"`); браузер входит в неё же (id в localStorage
`jury_scenario`). После прогона удаляется только она (`DELETE /api/jury/sandbox`; `E2E_RESET=1` — прежний сброс
`POST /api/jury/reset`), общее демо и чужие песочницы не трогаются. `E2E_SCENARIO=<id>` — продолжить свою песочницу,
`E2E_KEEP_STATE=1` — не трогать после прогона,
`E2E_STRICT=1` — известные ошибки продукта валят тест. Снимки 390 px — `reports/mobile`.
`E2E_PROXY=socks5://127.0.0.1:1080` — браузер и запросы к API идут через прокси (из песочницы до стенда: прямые
соединения из-за рубежа с сервером в Москве обрываются на ~16 КБ).

Устойчивая загрузка (Я16, без стенда и backend): `cd ../frontend && npm run build`, затем
`npx playwright test -c playwright.boot.config.ts` — собранный фронтенд в `vite preview`, сеть до файлов сборки и
`/api` ломается в тесте (зависание, обрыв, обрезанный файл, 500/503); `AXE_JS=<путь к axe.min.js>` — ещё и axe.
