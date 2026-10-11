"""FIX7 (P0 «Страница не загрузилась», выкладка 5) — статические проверки устойчивой загрузки (docs/BOOT.md).

Поведение в браузере — e2e/boot/boot.spec.ts (Playwright, собранный фронтенд); здесь — то, что легко сломать слиянием:
повтор загрузки раздела и предзагрузка подключены, экран сбоя называет причину и даёт «Очистить кэш и открыть заново»
и ссылку на /status, страница /status статическая (без файлов сборки и внешних запросов), nginx её отдаёт, service
worker её не перехватывает и отвечает версией сборки, сторож index.html укладывается в бюджет."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FE = ROOT / "frontend"
BANNED = re.compile(r"ФСП|ЛЦТ|спецтрек|хакатон|лидеры цифровой|neuropeople|fsp\.", re.IGNORECASE)


def _read(rel: str) -> str:
    return (FE / rel).read_text(encoding="utf-8")


def test_lazy_routes_retry_and_preload():
    lazy = _read("src/lib/lazyPage.ts")
    assert "export function loadWithRetry" in lazy
    assert re.search(r"RETRY_DELAYS_MS = \[\d+, \d+, \d+\]", lazy), "2–3 повтора с паузой"
    assert "newBuildOnServer" in lazy and "reloadForBuild" in lazy and "fsp_build_reload" in lazy
    assert "await loadWithRetry(load)" in lazy, "lazyNamed — через повтор"
    pre = _read("src/lib/preload.ts")
    assert "requestIdleCallback" in pre and "saveData" in pre
    app = _read("src/App.tsx")
    assert "preloadSections(PRELOAD)" in app
    for key in ("pg.cabinet", "pg.needs", "pg.validation", "pg.criteria", "pg.assessment"):
        assert key in app.split("const PRELOAD = [", 1)[1].split("]", 1)[0], key


def test_error_screens_name_reason_and_offer_clear_cache():
    html = _read("index.html")
    assert "Очистить кэш и открыть заново" in html and 'href="/status"' in html
    assert "BOOT-" in html and "не загрузился файл" in html and "не дождались файла" in html
    assert "caches.delete" in html and "unregister" in html
    boot = _read("src/components/Boot.tsx")
    assert "Очистить кэш и открыть заново" in boot and 'href="/status"' in boot
    assert "chunkName(error)" in boot and "CHUNK-TIMEOUT" in boot
    # экран «дольше обычного» не перезагружает страницу сам — повтор идёт на месте (lazyPage)
    fallback = boot.split("export function RouteFallback", 1)[1].split("\nexport ", 1)[0]
    assert "retry()" not in fallback


def test_boot_html_budget():
    # сторож доходит целиком даже при обрыве ~16 КБ; в сборке index.html ≤ 12 КБ (e2e «бюджет»), запас на теги сборки
    assert len(_read("index.html").encode("utf-8")) <= 11 * 1024


def test_status_page_static_and_served():
    page = _read("public/status.html")
    assert '<html lang="ru">' in page and "<h1" in page and 'id="main"' in page
    assert "/api/health" in page and "Очистить кэш и открыть заново" in page
    # без файлов сборки, шрифтов и внешних запросов
    assert not re.search(r'<(script|link)[^>]+(src|href)=', page)
    assert not re.search(r"https?://", page)
    assert not BANNED.search(page)
    nginx = _read("nginx.conf")
    assert re.search(r"location = /status \{[^}]*try_files /status\.html =404;", nginx)
    sw = _read("public/sw.js")
    assert 'url.pathname === "/status"' in sw, "service worker не перехватывает /status"
    assert '"get-version"' in sw, "service worker отвечает версией сборки (проверка устаревших хешей)"
    pwa = _read("src/integrations/pwa.ts")
    assert "checkStale" in pwa and "fsp_sw_stale" in pwa
