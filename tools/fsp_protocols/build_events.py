"""Сборка реестра соревнований ``events.json`` (без ПДн) из справок ФСП и разметки страниц.

Источники:
* справки ФСП о составе субъектов РФ и о составе судейской коллегии (отдельные PDF и страницы внутри
  протоколов) — число субъектов и участников, судейские категории (без ФИО);
* разметка страниц ``page_headers.py`` (``headers/h_<файл>.json``) — для многосоревновательных файлов
  чемпионатов и первенств федеральных округов;
* ручная сверка (агент А8, по изображениям страниц) — для всех всероссийских соревнований: значения ниже
  в ``MANUAL`` помечены ``check: "visual"``.

Результат: ``backend/app/modules/fsp/evsk_data/events.json`` и копия в ``docs/realdata/fsp_protocols/``.
Запуск: python3 tools/fsp_protocols/build_events.py <каталог headers> <каталог PDF>
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "backend/app/modules/fsp/evsk_data/events.json"
OUT_DOCS = ROOT / "docs/realdata/fsp_protocols/events.json"
BASE = "https://fsp-russia.ru/upload/iblock/"

# Субъекты РФ по федеральным округам (89 субъектов; ЮФО — с 2023 г. включая ДНР, ЛНР, Запорожскую и
# Херсонскую области).
FO = {  # основа слова -> (код, число субъектов РФ в округе)
    "центральн": ("ЦФО", 18), "северо-западн": ("СЗФО", 11), "южн": ("ЮФО", 12),
    "северо-кавказ": ("СКФО", 7), "приволжск": ("ПФО", 14), "уральск": ("УФО", 6),
    "сибирск": ("СФО", 10), "дальневосточн": ("ДФО", 11),
}
LAT = {"ЦФО": "cfo", "СЗФО": "szfo", "ЮФО": "yufo", "СКФО": "skfo", "ПФО": "pfo", "УФО": "ufo", "СФО": "sfo", "ДФО": "dfo"}
FO_TITLE = {"ЦФО": "Центрального", "СЗФО": "Северо-Западного", "ЮФО": "Южного", "СКФО": "Северо-Кавказского",
            "ПФО": "Приволжского", "УФО": "Уральского", "СФО": "Сибирского", "ДФО": "Дальневосточного"}
DISC = {
    "алгоритм": "программирование алгоритмическое", "продукт": "программирование продуктовое",
    "информационной": "программирование систем информационной безопасности",
    "робототехник": "программирование робототехники", "беспилотн": "программирование беспилотных авиационных систем",
}
TEAM_DISCIPLINES = {"программирование продуктовое", "программирование систем информационной безопасности",
                    "программирование робототехники", "программирование беспилотных авиационных систем"}

# Всероссийские соревнования: сверено глазами по изображениям страниц (агент А8, 21.10.2026).
# participants_total — спортсмены (без тренеров); judges — число судей по категориям из справки.
MANUAL = [
    dict(event_id="kr2025_algo_stage", title="Кубок России 2025, отборочный этап — программирование алгоритмическое",
         evsk_status="allrus_other_sport_ekp", stage="stage", discipline="программирование алгоритмическое",
         ekp_no="2101770020035561", date_start="2025-04-24", date_end="2025-04-26", venue="дистанционно",
         age_group="men_women", subjects_total=None, participants_total=None, judges=None,
         protocol="969/h77wns4jpn7z3pmkrm0azxfye6era08y.pdf", pages=None, certificates=[],
         note="справок о субъектах и судьях для отборочного этапа 2025 на сайте нет — условия п. 30 и 40.2 не проверены"),
    dict(event_id="kr2025_prod_stage", title="Кубок России 2025, отборочный этап — программирование продуктовое",
         evsk_status="allrus_other_sport_ekp", stage="stage", discipline="программирование продуктовое",
         ekp_no="2101000020035559", date_start="2025-04-21", date_end="2025-04-28", venue="дистанционно",
         age_group="men_women", subjects_total=None, participants_total=None, judges=None,
         protocol="6cb/txbuswvkginckkbtbwtkata1wbfukqda.pdf", pages=None, certificates=[],
         note="протокол только с названиями команд, без состава — личная сверка невозможна"),
    dict(event_id="kr2025_ib_stage", title="Кубок России 2025, отборочный этап — программирование систем информационной безопасности",
         evsk_status="allrus_other_sport_ekp", stage="stage", discipline="программирование систем информационной безопасности",
         ekp_no="2101000020041809", date_start="2025-04-26", date_end="2025-04-26", venue=None,
         age_group="men_women", subjects_total=None, participants_total=None, judges=None,
         protocol="922/9uxtofnr07t1n3lha1o0ku1anbqndqe1.pdf", pages=None, certificates=[],
         note="протокол только с названиями команд, без состава"),
    dict(event_id="kr2025_robo_stage", title="Кубок России 2025, отборочный этап — программирование робототехники",
         evsk_status="allrus_other_sport_ekp", stage="stage", discipline="программирование робототехники",
         ekp_no="2101000020035557", date_start="2025-05-12", date_end="2025-05-14", venue="дистанционно",
         age_group="men_women", subjects_total=None, participants_total=None,
         judges={"ВК": 1, "1К": 3, "2К": 2, "3К": 2},
         protocol="b0d/f4ikw0r1e2qwmvt3usudy5ve81r3ykrf.pdf", pages=None,
         certificates=[{"type": "judges", "file": "058/g6txm9cku30ktl7o93u8xw40kpjv9kin.pdf", "page": 1}],
         note="протокол только с названиями команд; справки о субъектах нет"),
    dict(event_id="kr2025_prod_final", title="Кубок России 2025, финал — программирование продуктовое",
         evsk_status="kr_final", stage="final", discipline="программирование продуктовое",
         ekp_no="2101620020035562", date_start="2025-05-18", date_end="2025-05-22", venue="Смоленск",
         age_group="men_women", subjects_total=23, participants_total=170,
         judges={"ВК": 1, "1К": 3, "2К": 2, "3К": 4},
         protocol="f5e/8ma6l935b05m4q88wi5n24ne23p7qbya.pdf", pages=None,
         certificates=[{"type": "subjects", "file": None, "match": "tcwdz7r278a2ag9tfs30wx0uhmbkyt3e.pdf", "page": 1},
                       {"type": "judges", "file": None, "match": "xmaz6tfu1s1i4npv4cov6i8tx9uih491.pdf", "page": 1}],
         note="в справке: 204 участника из 23 регионов (170 спортсменов и 34 тренера)"),
    dict(event_id="kr2025_ib_final", title="Кубок России 2025, финал — программирование систем информационной безопасности",
         evsk_status="kr_final", stage="final", discipline="программирование систем информационной безопасности",
         ekp_no="2101670020041686", date_start="2025-05-19", date_end="2025-05-22", venue="Смоленск",
         age_group="men_women", subjects_total=23, participants_total=294,
         judges={"ВК": 1, "1К": 3, "2К": 2, "3К": 4},
         protocol="27f/5hs99w6a2n362vlqnonn51110vlhkvc5.pdf", pages=None,
         certificates=[{"type": "subjects", "match": "dxry6o6q7cupi2869xufoyj5xmpd6oxl.pdf", "page": 1},
                       {"type": "judges", "match": "ioj8xp1kj123khtif177ghkajz37rlvt.pdf", "page": 1}],
         note="в справке: 336 участников из 23 регионов (294 спортсмена и 42 тренера)"),
    dict(event_id="kr2025_algo_final", title="Кубок России 2025, финал — программирование алгоритмическое",
         evsk_status="kr_final", stage="final", discipline="программирование алгоритмическое",
         ekp_no="2101770020035561", date_start="2025-05-23", date_end="2025-05-25", venue="Москва",
         age_group="men_women", subjects_total=32, participants_total=217,
         judges={"ВК": 1, "1К": 3, "2К": 2, "3К": 4},
         protocol="2fd/go7v4ekr13s1wwepx7poocbxgxd2u92i.pdf", pages=None,
         certificates=[{"type": "subjects", "match": "7e26ftguiuunswmt1d7njeoqq0ykg2cs.pdf", "page": 1},
                       {"type": "judges", "match": "iyazju5ylp8x0mh3dqlqf0iymppdonff.pdf", "page": 1}],
         note="в справке: 434 участника из 32 регионов (217 спортсменов и 217 тренеров)"),
    dict(event_id="chr2025_prod", title="Чемпионат России 2025 — программирование продуктовое",
         evsk_status="chr", stage="final", discipline="программирование продуктовое",
         ekp_no="2101590019043742", date_start="2025-11-20", date_end="2025-11-24", venue="Москва",
         age_group="men_women", subjects_total=10, participants_total=69,
         judges={"ВК": 3, "2К": 1, "3К": 1},
         protocol="138/tb1vnqokiid4fiwdb40evznavplvmysg.pdf", pages=[3, 5],
         certificates=[{"type": "judges", "page": 1}, {"type": "subjects", "page": 2}],
         note="субъектов 10 из 89 (меньше 25 %, но не менее 6) — по п. 31 нужен повторный результат"),
    dict(event_id="kr2026_algo_stage", title="Кубок России 2026, отборочный этап — программирование алгоритмическое",
         evsk_status="allrus_other_sport_ekp", stage="stage", discipline="программирование алгоритмическое",
         ekp_no="2101000020046569", date_start="2026-04-11", date_end="2026-04-12", venue="по месту нахождения участников",
         age_group="men_women", subjects_total=24, participants_total=199,
         judges={"ВК": 1, "1К": 3},
         protocol="fff/rof2o18vujo5me8hfep08nn3bp6sd3lv.pdf", pages=[1, 10],
         certificates=[{"type": "subjects", "page": 11}, {"type": "subjects", "page": 12}, {"type": "judges", "page": 13}]),
    dict(event_id="kr2026_algo_stage", alias_of="kr2026_algo_stage", protocol="a0b/f0gja1njckgfwu6heobl1o3z4021wlpg.pdf",
         pages=[1, 13], note="турнирная таблица того же соревнования (дубли результатов протокола)"),
    dict(event_id="kr2026_prod_stage", title="Кубок России 2026, отборочный этап — программирование продуктовое",
         evsk_status="allrus_other_sport_ekp", stage="stage", discipline="программирование продуктовое",
         ekp_no="2101000020046570", date_start="2026-04-17", date_end="2026-04-27", venue="по месту нахождения участников",
         age_group="men_women", subjects_total=18, participants_total=143,
         judges={"ВК": 2, "1К": 2},
         protocol="120/f8mtqy9398owua73i24f999rly5fovnf.pdf", pages=[1, 7],
         certificates=[{"type": "judges", "page": 8}, {"type": "subjects", "page": 9}],
         note="субъектов 18 из 89 — по п. 31 нужен повторный результат"),
    dict(event_id="kr2026_sib_stage", title="Кубок России 2026, отборочный этап — программирование систем информационной безопасности",
         evsk_status="allrus_other_sport_ekp", stage="stage", discipline="программирование систем информационной безопасности",
         ekp_no="2101000020046571", date_start="2026-04-18", date_end="2026-04-19", venue="по месту нахождения участников",
         age_group="men_women", subjects_total=25, participants_total=236,
         judges={"ВК": 1, "1К": 3},
         protocol="9db/e6rp6ekcljtfofzw99bao13a8mpav8i9.pdf", pages=[1, 6],
         certificates=[{"type": "judges", "page": 7}, {"type": "judges_other_event", "page": 8, "note": "финал КР 2026, ЕКП 2101000020046578, 11–14.05.2026, Воронеж — протокола финала на сайте нет"},
                       {"type": "subjects", "page": 9}, {"type": "subjects", "page": 10}]),
    dict(event_id="kr2026_bas_stage", title="Кубок России 2026, отборочный этап — программирование беспилотных авиационных систем",
         evsk_status="allrus_other_sport_ekp", stage="stage", discipline="программирование беспилотных авиационных систем",
         ekp_no="2101000020046573", date_start="2026-04-20", date_end="2026-04-23", venue="по месту нахождения участников",
         age_group="men_women", subjects_total=13, participants_total=51,
         judges={"ВК": 2, "1К": 1, "2К": 1},
         protocol="5c8/p3ikqnt1g9iw1kvczvxgv5qjhv2x9tya.pdf", pages=[3, 4],
         certificates=[{"type": "judges", "page": 1}, {"type": "subjects", "page": 2}],
         note="субъектов 13 из 89 — по п. 31 нужен повторный результат"),
    dict(event_id="kr2026_robo_stage", title="Кубок России 2026, отборочный этап — программирование робототехники",
         evsk_status="allrus_other_sport_ekp", stage="stage", discipline="программирование робототехники",
         ekp_no="2101000020046572", date_start="2026-04-26", date_end="2026-04-29", venue="по месту нахождения участников",
         age_group="men_women", subjects_total=13, participants_total=81,
         judges={"ВК": 2, "1К": 2},
         protocol="092/us9qvdfvm0kwathyo67wjuvje8c9v1ra.pdf", pages=[3, 6],
         certificates=[{"type": "judges", "page": 1}, {"type": "subjects", "page": 2}],
         note="субъектов 13 из 89 — по п. 31 нужен повторный результат"),
    dict(event_id="kf2026_sib_stage", title="Кубок Федерации спортивного программирования 2026, отборочный этап — программирование систем информационной безопасности",
         evsk_status=None, stage="stage", discipline="программирование систем информационной безопасности",
         ekp_no="1101770002005773", date_start="2026-09-19", date_end="2026-09-20", venue="онлайн",
         age_group="men_women", subjects_total=67, participants_total=1306,
         judges={"1К": 2, "2К": 1, "3К": 1},
         protocol="ef1/15a3exjee1npp1vux0sl5qborm4n6q3r.pdf", pages=[5, 70],
         certificates=[{"type": "judges", "page": 1}, {"type": "subjects", "page": 2}, {"type": "subjects", "page": 3}, {"type": "subjects", "page": 4}],
         note="отборочный этап всероссийского физкультурного мероприятия: итог мероприятия — финал; нормы ЕВСК к отборочному этапу не применяются (консервативно)"),
    dict(event_id="kf2026_sib_final", title="Кубок Федерации спортивного программирования 2026, финал — программирование систем информационной безопасности",
         evsk_status="allrus_other_fizkult_ekp", stage="final", discipline="программирование систем информационной безопасности",
         ekp_no="1101770002005773", date_start="2026-10-09", date_end="2026-10-11", venue="Москва",
         age_group="men_women", subjects_total=67, participants_total=1306,
         judges={"1К": 2, "2К": 1, "3К": 1},
         protocol="ef1/15a3exjee1npp1vux0sl5qborm4n6q3r.pdf", pages=[71, 75],
         certificates=[{"type": "judges", "page": 1}, {"type": "subjects", "page": 2}],
         note="всероссийское физкультурное мероприятие (ЕКП, часть I); справка о субъектах — общая для отборочного этапа и финала"),
    dict(event_id="sbornaya_rf_2026", title="Список кандидатов в спортивные сборные команды Российской Федерации по спортивному программированию 2026",
         evsk_status=None, stage="list", discipline=None, ekp_no=None, date_start="2026-05-14", date_end=None, venue=None,
         age_group=None, subjects_total=None, participants_total=None, judges=None,
         protocol="503/e5miei2aikivxs93d6qz2iqfnfaf0xp1.pdf", pages=None, certificates=[],
         note="не протокол соревнования: включение в список кандидатов в сборную — отдельный сильный признак"),
]


def disc_of(text: str | None) -> str | None:
    t = (text or "").lower()
    for k, v in DISC.items():
        if k in t:
            return v
    return None


def fo_events(hdr: dict, file: str) -> list[dict]:
    """Чемпионаты и первенства федеральных округов: тройки «судьи → субъекты → протокол»."""
    pages = hdr["pages"]
    starts = [p for p in pages if p.get("page_type") == "judges_certificate"]
    out = []
    for i, j in enumerate(starts):
        nxt = starts[i + 1]["page"] if i + 1 < len(starts) else len(pages) + 1
        seg = [p for p in pages if j["page"] <= p["page"] < nxt]
        subj = next((p for p in seg if p.get("page_type") == "subjects_certificate"), None)
        comp = j.get("competition") or ""
        fo_name = next((k for k in FO if k in comp.lower().replace("ё", "е")), None)
        kind = "fo_perv" if "первенств" in comp.lower() else "fo_champ"
        cats: dict[str, int] = {}
        for x in j.get("judges") or []:
            c = str(x.get("category") or "").upper().replace("K", "К")
            if c in {"ВК", "1К", "2К", "3К"}:
                cats[c] = cats.get(c, 0) + 1
        code, total = FO.get(fo_name, (None, None))
        proto_first = (subj["page"] + 1) if subj else j["page"] + 1
        disc = disc_of(j.get("discipline") or comp)
        out.append(dict(
            event_id=f"fo2026_{'perv' if kind == 'fo_perv' else 'champ'}_{LAT.get(code, 'x')}_{'prod' if disc and 'продукт' in disc else 'x'}",
            title=f"{'Первенство' if kind == 'fo_perv' else 'Чемпионат'} {FO_TITLE.get(code, '')} федерального округа 2026 — {disc or ''}",
            evsk_status=kind, stage="final", discipline=disc, ekp_no=j.get("ekp_no"),
            date_start=j.get("date_start"), date_end=j.get("date_end"), venue=j.get("venue"),
            age_group="youth_u19" if kind == "fo_perv" else "men_women",
            fo=code, fo_subjects_total=total,
            subjects_total=(subj or {}).get("subjects_total"), participants_total=(subj or {}).get("participants_total"),
            judges=cats or None, protocol=file, pages=[proto_first, nxt - 1],
            certificates=[{"type": "judges", "page": j["page"]}] + ([{"type": "subjects", "page": subj["page"]}] if subj else []),
            check="model", note="реквизиты из разметки страниц моделью; ЧСЗФО, ПЦФО и ПСФО сверены глазами",
        ))
    return out


def sha(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def main() -> None:
    hdr_dir, pdf_dir = Path(sys.argv[1]), Path(sys.argv[2])
    events: dict[str, dict] = {}
    page_map: dict[str, list[dict]] = {}
    sources: dict[str, dict] = {}

    def add_source(rel: str) -> str:
        name = rel.rsplit("/", 1)[-1]
        sources[name] = {"url": BASE + rel if "/" in rel else None, "sha256": sha(pdf_dir / name)}
        return name

    for m in MANUAL:
        name = add_source(m["protocol"])
        n_pages = None
        h = hdr_dir / f"h_{name[:6]}.json"
        if h.exists():
            n_pages = len(json.loads(h.read_text(encoding="utf-8"))["pages"])
        pages = m.get("pages") or [1, n_pages or 999]
        page_map.setdefault(name, []).append({"pages": pages, "event_id": m["event_id"], "page_type": "protocol"})
        for c in m.get("certificates", []):
            if c.get("page") and not c.get("match"):
                page_map[name].append({"pages": [c["page"], c["page"]], "event_id": m["event_id"], "page_type": f"certificate_{c['type']}"})
        if m.get("alias_of"):
            continue
        ev = {k: v for k, v in m.items() if k not in {"protocol", "pages", "alias_of"}}
        ev["protocol_url"] = sources[name]["url"]
        ev["protocol_sha256"] = sources[name]["sha256"]
        ev["team_event"] = (ev.get("discipline") in TEAM_DISCIPLINES)
        ev.setdefault("check", "visual")
        for c in ev.get("certificates", []):
            if c.get("match"):
                nm = c.pop("match")
                c["file"] = nm
                c["sha256"] = sha(pdf_dir / nm)
        events[m["event_id"]] = ev

    fo_files = {"f68/xqhh07qp40z3mfi8lraxt53842qlw772.pdf", "a3d/u4g6723ljtd8cxp3fa1kfhbs01f7cfbs.pdf"}
    for rel in sorted(fo_files):
        name = add_source(rel)
        hdr = json.loads((hdr_dir / f"h_{name[:6]}.json").read_text(encoding="utf-8"))
        for ev in fo_events(hdr, name):
            ev["protocol_url"] = sources[name]["url"]
            ev["protocol_sha256"] = sources[name]["sha256"]
            ev["team_event"] = ev.get("discipline") in TEAM_DISCIPLINES
            page_map.setdefault(name, []).append({"pages": ev["pages"], "event_id": ev["event_id"], "page_type": "protocol"})
            for c in ev["certificates"]:
                page_map[name].append({"pages": [c["page"], c["page"]], "event_id": ev["event_id"], "page_type": f"certificate_{c['type']}"})
            ev.pop("pages")
            ev.pop("protocol")
            events[ev["event_id"]] = ev

    for segs in page_map.values():
        segs.sort(key=lambda s: (s["pages"][0], 0 if s["page_type"] != "protocol" else 1))
    doc = {"version": "2026-10-21", "description": "Соревнования ФСП из официальных протоколов и справок (без ПДн)",
           "sources": sources, "events": events, "page_map": page_map}
    txt = json.dumps(doc, ensure_ascii=False, indent=1)
    for p in (OUT, OUT_DOCS):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(txt + "\n", encoding="utf-8")
    print(len(events), "events;", sum(len(v) for v in page_map.values()), "page segments")


if __name__ == "__main__":
    main()
