"""Доступность и нейтральные публичные тексты — статические проверки исходников (docs/ACCESSIBILITY.md, Р36).

Браузерный аудит (axe-core, клавиатура) — tools/a11y/; здесь — то, что легко сломать слиянием: язык страницы,
ссылка «Перейти к содержимому», один <main id="main"> на экран, ловушка фокуса в окне, нейтральный манифест."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FE = ROOT / "frontend"
# Публично без пароля стенда: манифест, service worker, страница-оболочка — без соревнования, домена и команды
BANNED = re.compile(r"ФСП|ЛЦТ|спецтрек|хакатон|лидеры цифровой|neuropeople|fsp\.", re.IGNORECASE)


def _read(rel: str) -> str:
    return (FE / rel).read_text(encoding="utf-8")


def test_manifest_neutral_and_russian():
    raw = _read("public/manifest.webmanifest")
    m = json.loads(raw)
    assert m["lang"] == "ru"
    assert m["name"].startswith("Драфт") and m["short_name"] == "Драфт"
    assert m["description"] and len(m["description"]) <= 300
    assert not BANNED.search(raw), "в манифесте — название соревнования, домен или команда"


def test_public_shell_neutral():
    html = _read("index.html")
    assert '<html lang="ru">' in html
    title = re.search(r"<title>(.*?)</title>", html).group(1)
    desc = re.search(r'<meta name="description" content="([^"]+)"', html).group(1)
    assert title and desc
    for text, where in ((title, "title"), (desc, "description"), (_read("public/sw.js"), "sw.js")):
        assert not BANNED.search(text), f"{where}: название соревнования, домен или команда"
    default_title = re.search(r"const defaultTitle = .*", _read("src/lib/meta.tsx")).group(0)
    assert not BANNED.search(default_title)


def test_skip_link_and_single_main():
    app = _read("src/App.tsx")
    assert "<SkipLink />" in app and "<RouteAnnouncer />" in app
    a11y = _read("src/components/A11y.tsx")
    assert "Перейти к содержимому" in a11y and 'href="#main"' in a11y
    # каждая оболочка экрана — ровно один <main id="main">; цель ссылки пропуска существует
    for rel in ("src/pages/Landing.tsx", "src/components/AuthShell.tsx", "src/components/CabinetLayout.tsx",
                "src/pages/Validation.tsx", "src/integrations/Sus.tsx"):
        src = _read(rel)
        assert len(re.findall(r"<main\b", src)) == 1, rel
        assert '<main id="main"' in src, rel


def test_modal_keeps_focus_and_has_name():
    ui = _read("src/components/ui.tsx")
    modal = ui[ui.index("export function Modal"):]
    assert 'role="dialog"' in modal and 'aria-modal="true"' in modal and "aria-labelledby={titleId}" in modal
    assert "trapTab(e, box.current)" in modal and '"Escape"' in modal


def test_test_run_announces_item_and_timer():
    src = _read("src/pages/candidate/Assessment.tsx")
    assert 'role="timer"' in src
    assert "ref={itemHead}" in src and "itemHead.current?.focus" in src
    assert 'role={isLine ? "listbox" : undefined}' in src and "pickLine(" in src



def test_ats_block_is_named_group_not_repeated_region():
    """Карточек приглашений на экране много: одинаковые <section aria-label> — повтор области (axe landmark-unique)."""
    src = _read("src/integrations/Ats.tsx")
    block = src[src.index("export function AtsInvitationActions"):]
    head = re.search(r"<section[^>]*>", block).group(0)
    assert 'role="group"' in head and "candidateRef" in head
