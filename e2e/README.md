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
