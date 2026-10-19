"""Агрегация событий камеры в сигнал достоверности — чистые функции (покрыты tests/test_proctor.py).

Входные данные — только то, что прислал браузер кандидата (интервалы без нормального кадра и сколько камера
наблюдала каждое задание), и время заданий по часам сервера. Браузеру доверять нельзя, поэтому, как и сигналы
вкладки, камера только понижает достоверность и никогда её не повышает; тест без камеры — нейтральная пометка.

Пороги — баллы риска в общей шкале assessment/integrity.py (≥ 3 — низкая, 1–2 — средняя):
* нет лица в кадре: ≥ 2 мин или ≥ 5 заданий — 2 балла; ≥ 20 с или ≥ 2 заданий — 1 балл;
* несколько лиц: ≥ 2 заданий или ≥ 30 с — 2 балла; одно задание — 1 балл;
* камера закрыта или не передаёт изображение (в том числе задание, которое камера не наблюдала, хотя режим
  камеры включён): ≥ 2 мин или ≥ 3 заданий — 2 балла; ≥ 30 с — 1 балл.
Короткие интервалы не считаются: взгляд на клавиатуру или в окно — не нарушение (MIN_MS). Камера, выключенная
кандидатом кнопкой, — не нарушение: дальше тест идёт «без камеры», работодатель видит нейтральную пометку.
"""
from __future__ import annotations

from typing import Any

KINDS = ("no_face", "multi_face", "blocked", "camera_off")
# D3 п. 3: мгновенные события журнала (без длительности) — в журнале видны, в баллы камеры не входят: снимок экрана
# учитывается один раз — сигналом задания printscreen в assessment/integrity.py (proctoring_source)
MARK_KINDS = ("printscreen",)
EVENT_KINDS = KINDS + MARK_KINDS
KIND_TITLES = {"no_face": "нет лица в кадре", "multi_face": "в кадре несколько лиц", "blocked": "камера закрыта",
               "camera_off": "камера не передаёт изображение", "printscreen": "Снимок экрана (PrintScreen)"}
MODES = ("camera", "declined", "unsupported", "denied")
MODE_TITLES = {"camera": "с камерой", "declined": "без камеры — выбор кандидата",
               "unsupported": "без камеры — браузер не поддерживает анализ видео",
               "denied": "без камеры — нет доступа к камере в браузере", "none": "без камеры"}
MIN_MS = {"no_face": 3000, "multi_face": 2000, "blocked": 3000, "camera_off": 3000}
MAX_EVENT_MS = 3_600_000
UNCOVERED_GRACE_MS = 5000  # переход между заданиями, загрузка страницы
UNCOVERED_ITEM_MIN_S = 15.0  # короче — покрытие не проверяем
NO_FACE_MOSTLY = 0.8  # лицо не находилось почти всё время — скорее камера направлена мимо или мало света


def _n(k: int, one: str, few: str, many: str) -> str:
    m10, m100 = k % 10, k % 100
    w = one if m10 == 1 and m100 != 11 else few if 2 <= m10 <= 4 and not 12 <= m100 <= 14 else many
    return f"{k} {w}"


def on_items(k: int) -> str:
    """«на 1 задании», «на 3 заданиях»."""
    return "на " + _n(k, "задании", "заданиях", "заданиях")


def dur(seconds: float) -> str:
    """Длительность по-русски: «40 с», «2,5 мин»."""
    s = max(0.0, float(seconds))
    if s < 60:
        return f"{round(s):d}\u00a0с"
    m = s / 60
    return (f"{m:.1f}".replace(".", ",").replace(",0", "") if m < 10 else f"{round(m):d}") + "\u00a0мин"


def watched(windows: list[dict] | None, position: int) -> bool:
    return any(int(w.get("from") or 1) <= position and (w.get("to") is None or position < int(w["to"]))
               for w in windows or [])


def _window_start_mid(windows: list[dict] | None, position: int) -> bool:
    """Задание, на котором камеру включили посреди задания: покрытие по нему не проверяем."""
    return any(w.get("mid") and int(w.get("from") or 1) == position for w in windows or [])


def aggregate(mode: str | None, items: list[dict], events: list[dict], observed: dict | None = None,
              windows: list[dict] | None = None, stop: dict | None = None) -> dict:
    """mode — режим сессии (None — запись о камере не создавалась: API, старый клиент).
    items — задания сессии по порядку: {position, time_s (часы сервера, None — ещё не отвечено), canary};
    events — {position, kind, duration_ms, faces}; observed — {"<position>": {"ms", "frames", "face"}};
    windows — окна наблюдения [{from, to, mid}]; stop — {"position", "reason"} если кандидат выключил камеру.

    Возвращает {mode, camera, title, points, reasons[(баллы, текст)], remarks[], notes[], totals{}, per_item[]}.
    """
    observed = observed or {}
    if mode != "camera" or not windows:
        return {"mode": mode or "none", "camera": False, "title": "Тест без камеры", "points": 0, "reasons": [],
                "remarks": [], "notes": [MODE_TITLES.get(mode or "none", MODE_TITLES["none"])], "totals": {},
                "per_item": []}
    per: dict[int, dict] = {}
    for it in items:
        pos = int(it["position"])
        if not watched(windows, pos):
            continue
        obs = observed.get(str(pos)) or {}
        per[pos] = {"position": pos, "time_s": it.get("time_s"), "observed_ms": int(obs.get("ms") or 0),
                    "frames": int(obs.get("frames") or 0), **{k: 0 for k in KINDS}, "faces_max": 0,
                    "uncovered_ms": 0}
    for e in events:
        pos, kind = int(e.get("position") or 0), e.get("kind")
        ms = max(0, min(int(e.get("duration_ms") or 0), MAX_EVENT_MS))
        if pos not in per or kind not in KINDS or ms < MIN_MS[kind]:
            continue
        per[pos][kind] += ms
        if kind == "multi_face":
            per[pos]["faces_max"] = max(per[pos]["faces_max"], int(e.get("faces") or 2))
    for pos, p in per.items():
        t = p["time_s"]
        if t is None or float(t) < UNCOVERED_ITEM_MIN_S or _window_start_mid(windows, pos):
            continue
        gap = int(float(t) * 1000) - p["observed_ms"] - UNCOVERED_GRACE_MS
        if gap > 0:
            p["uncovered_ms"] = gap  # режим камеры включён, а наблюдения не было (перезагрузка, сбой, обход)

    rows = list(per.values())
    no_face_items = [p for p in rows if p["no_face"]]
    multi_items = [p for p in rows if p["multi_face"]]
    off_items = [p for p in rows if p["blocked"] + p["camera_off"] + p["uncovered_ms"] > 0]
    no_face_s = sum(p["no_face"] for p in rows) / 1000
    multi_s = sum(p["multi_face"] for p in rows) / 1000
    off_s = sum(p["blocked"] + p["camera_off"] + p["uncovered_ms"] for p in rows) / 1000
    observed_s = sum(p["observed_ms"] for p in rows) / 1000
    reasons: list[tuple[int, str]] = []
    nf_pts = 2 if no_face_s >= 120 or len(no_face_items) >= 5 else 1 if no_face_s >= 20 or len(no_face_items) >= 2 else 0
    if nf_pts:
        hint = ("; лицо почти не определялось — возможно, камера направлена мимо или мало света"
                if observed_s and no_face_s / observed_s >= NO_FACE_MOSTLY else "")
        reasons.append((nf_pts, f"нет лица в кадре {dur(no_face_s)} {on_items(len(no_face_items))}{hint}"))
    mf_pts = 2 if len(multi_items) >= 2 or multi_s >= 30 else 1 if multi_items else 0
    if mf_pts:
        reasons.append((mf_pts, f"в кадре несколько лиц {on_items(len(multi_items))} ({dur(multi_s)})"))
    off_pts = 2 if off_s >= 120 or len(off_items) >= 3 else 1 if off_s >= 30 else 0
    if off_pts:
        reasons.append((off_pts, f"камера закрыта или не передавала изображение {dur(off_s)} "
                                 f"{on_items(len(off_items))}"))
    notes = []
    if stop and stop.get("position"):
        who = "согласие отозвано" if stop.get("reason") == "revoked" else "камера выключена кандидатом"
        notes.append(f"{who} на задании {int(stop['position'])} — дальше тест шёл без камеры")
    reasons.sort(key=lambda x: -x[0])
    points = sum(p for p, _ in reasons)
    remarks = [t for _, t in reasons]
    title = "Камера: включена, замечаний нет" if not remarks else "Камера: включена, есть замечания"
    return {
        "mode": "camera", "camera": True, "title": title, "points": points,
        "reasons": [(p, "Камера: " + t) for p, t in reasons], "remarks": remarks, "notes": notes,
        "totals": {"items_watched": len(rows), "observed_s": round(observed_s, 1), "no_face_s": round(no_face_s, 1),
                   "no_face_items": len(no_face_items), "multi_face_s": round(multi_s, 1),
                   "multi_face_items": len(multi_items), "off_s": round(off_s, 1), "off_items": len(off_items)},
        "per_item": sorted(rows, key=lambda p: p["position"]),
    }


def employer_view(summary: dict) -> dict:
    """Что видит работодатель: только итог — режим, заголовок и замечания (без событий и времени по заданиям)."""
    return {"mode": "on" if summary.get("camera") else "off", "title": summary.get("title") or "Тест без камеры",
            "remarks": list(summary.get("remarks") or [])[:3], "notes": list(summary.get("notes") or [])[:1]
            if summary.get("camera") else []}


def items_from_state(state: dict[str, Any]) -> list[dict]:
    """Задания сессии из состояния движка: банк — items с token/position/time_s; заглушка — item_ids по порядку."""
    if isinstance(state.get("items"), list):
        return [{"position": int(i["position"]), "token": i.get("token"), "time_s": i.get("time_s") if i.get("done")
                 else None, "canary": bool(i.get("canary"))} for i in state["items"] if i.get("position")]
    ids = state.get("item_ids") or []
    answers = state.get("answers") or {}
    return [{"position": k + 1, "token": iid, "time_s": None, "canary": False, "answered": iid in answers}
            for k, iid in enumerate(ids)]


def current_position(state: dict[str, Any]) -> int:
    """Номер задания, которое кандидат видит сейчас (или следующего)."""
    if isinstance(state.get("items"), list):
        cur = state.get("current")
        for i in state["items"]:
            if cur and i.get("token") == cur:
                return int(i["position"])
        return max([int(i["position"]) for i in state["items"]] or [0]) + 1
    return len(state.get("answers") or {}) + 1
