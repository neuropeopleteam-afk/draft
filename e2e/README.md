# Сквозные сценарии жюри (Playwright)

Отдельный пакет: свои зависимости, фронтенд не затрагивает. Подробно — [docs/testing.md](../docs/testing.md).

```bash
npm ci && npx playwright install chromium            # браузер ставится в ~/.cache/ms-playwright
E2E_BASE_URL=http://127.0.0.1:8140 npx playwright test   # локальный стек (tools/ci/stack.sh up && seed)
E2E_BASE_URL=https://fsp.neuropeople.pro E2E_BASIC_USER=demo E2E_BASIC_PASSWORD=… npx playwright test
npm run report                                        # HTML-отчёт последнего прогона
```

До и после прогона демо жюри сбрасывается (`POST /api/jury/reset`), созданные тестами данные не остаются.
`E2E_KEEP_STATE=1` — не сбрасывать после прогона.
