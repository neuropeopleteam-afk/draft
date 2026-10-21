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

import math
import re
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


# ------------------------------------------------------------------ «двойник при копировании» и индекс честности (P1)
_DECOY_NUM_RE = re.compile(r"(?<![A-Za-zА-Яа-яЁё0-9_./\-])(\d+(?:[.,]\d+)?)(?![A-Za-zА-Яа-яЁё0-9_./\-])")
_SKIP_NUMS = {0, 1, 2, 3, 200, 201, 204, 400, 401, 403, 404, 409, 422, 429, 500, 502, 503, 2024, 2025, 2026, 2027}


def make_copy_decoy(stem: str, key_value: float | int | str | None = None, *, factor: float = 1.25) -> dict | None:
    """Для параметрических числовых заданий: при копировании условия в буфер обмена (событие copy) подменяет одно
    опорное число условия (на экране остаётся исходное).

    Возвращает {"clipboard_stem", "orig_number", "decoy_number", "decoy_answer"} или None, если подходящего числа нет.
    """
    text = stem or ""
    for m in _DECOY_NUM_RE.finditer(text):
        raw = m.group(1)
        try:
            val = float(raw.replace(",", "."))
        except ValueError:
            continue
        if val < 4 or (val.is_integer() and int(val) in _SKIP_NUMS):
            continue
        if "," in raw or "." in raw:
            decoy_val = round(val * factor, 2)
            if abs(decoy_val - val) < 1e-6:
                decoy_val = round(val + 1.5, 2)
            decoy_str = str(decoy_val).replace(".", ",") if "," in raw else str(decoy_val)
        else:
            iv = int(val)
            decoy_iv = int(round(iv * factor))
            if decoy_iv == iv:
                decoy_iv = iv + 5
            decoy_val = float(decoy_iv)
            decoy_str = str(decoy_iv)
        clip_stem = text[: m.start(1)] + decoy_str + text[m.end(1) :]
        decoy_ans: float | None = None
        if key_value is not None:
            try:
                kv = float(str(key_value).replace(",", "."))
                if math.isfinite(kv) and val != 0:
                    decoy_ans = round(kv * (decoy_val / val), 4)
            except ValueError:
                decoy_ans = None
        return {
            "clipboard_stem": clip_stem,
            "orig_number": val,
            "decoy_number": decoy_val,
            "orig_str": raw,
            "decoy_str": decoy_str,
            "decoy_answer": decoy_ans,
        }
    return None


def check_copy_decoy(answer: Any, decoy: dict | None, *, copied: bool = True, tol: float = 0.02) -> bool:
    """Проверяет, решено ли задание по скопированному тексту-двойнику (без автоблокировки → сигнал в контур origin)."""
    if not copied or not decoy:
        return False
    decoy_ans = decoy.get("decoy_answer")
    orig_num = decoy.get("orig_number")
    decoy_num = decoy.get("decoy_number")
    if answer is None:
        return False
    # 1. Числовой ответ
    try:
        ans_val = float(str(answer).strip().replace(",", "."))
        if decoy_ans is not None and math.isfinite(ans_val):
            denom = max(1.0, abs(float(decoy_ans)))
            if abs(ans_val - float(decoy_ans)) / denom <= tol:
                return True
    except ValueError:
        pass
    # 2. Развёрнутый ответ: упоминается подменённое число из буфера при отсутствии исходного числа с экрана
    ans_str = str(answer)
    decoy_s = str(decoy.get("decoy_str") or "")
    orig_s = str(decoy.get("orig_str") or "")
    if decoy_s and decoy_s in ans_str and (not orig_s or orig_s not in ans_str):
        return True
    if decoy_num is not None and orig_num is not None:
        nums = [float(x.replace(",", ".")) for x in _DECOY_NUM_RE.findall(ans_str)]
        if any(abs(x - float(decoy_num)) < 1e-6 for x in nums) and not any(abs(x - float(orig_num)) < 1e-6 for x in nums):
            return True
    return False


def integrity_followup(integ: dict | None, *, decoy_hits: int = 0) -> dict:
    """Сводный индекс честности попытки (person-fit + время + фокус + вставки + двойник при копировании) для А4.

    Не блокирует кандидата автоматически, а переводит вердикт в «нужен дополнительный этап / устная защита»
    при risk_points >= 2 или срабатывании двойника при копировании, формируя понятное объяснение для работодателя.
    """
    integ = integ or {}
    sig = integ.get("signals") or {}
    decoy_n = max(int(decoy_hits or 0), int(sig.get("copy_decoy_items") or 0))
    decoy_hit = decoy_n > 0

    factors: list[str] = []
    human_parts: list[str] = []
    pts = 0

    # 1. Психометрическая согласованность ответов (person-fit)
    lz = sig.get("lz")
    if sig.get("lz_flag") or (isinstance(lz, (int, float)) and lz < -2.0):
        factors.append("person_fit")
        pts += 2 if (isinstance(lz, (int, float)) and lz < -3.0) else 1
        human_parts.append("ошибки на базовых вопросах при верных ответах на сложных")

    # 2. Аномалии времени и предзнание
    if sig.get("preknowledge_flagged") or (sig.get("canary_fast") or 0) > 0 or (sig.get("instant_correct") or 0) >= 2 or (sig.get("fast_text_items") or 0) > 0:
        factors.append("time_anomaly")
        pts += 2 if sig.get("preknowledge_flagged") or (sig.get("instant_correct") or 0) >= 2 else 1
        human_parts.append("ответы даны быстрее времени прочтения условия")

    # 3. Уход со вкладки / экран
    if (sig.get("focus_lost_items") or 0) >= 2 or (sig.get("hidden_s") or 0) >= 30 or (sig.get("fs_exits") or 0) >= 2 or (sig.get("printscreen_items") or 0) > 0:
        factors.append("focus_lost")
        pts += 2 if (sig.get("focus_lost_items") or 0) >= 5 or (sig.get("hidden_s") or 0) >= 180 else 1
        human_parts.append("переключение вкладки или снимки экрана во время заданий")

    # 4. Происхождение текста ответа (вставки, ИИ-метка, инъекции, ритм набора)
    if (sig.get("paste_items") or 0) > 0 or (sig.get("ai_mark_items") or 0) > 0 or (sig.get("not_typed_items") or 0) > 0 or (sig.get("even_rhythm_items") or 0) > 0 or (sig.get("injection_items") or 0) > 0:
        factors.append("paste_origin")
        pts += 2 if (sig.get("ai_mark_items") or 0) > 0 or (sig.get("injection_items") or 0) > 0 or (sig.get("paste_items") or 0) >= 2 else 1
        human_parts.append("вставка готового текста или признаки внешней подсказки в развёрнутом ответе")

    # 5. Двойник при копировании
    if decoy_hit:
        factors.append("copy_decoy")
        pts += 2
        human_parts.append("расчёт выполнен по числу из скопированного в буфер условия-двойника")

    # 6. Камера (если была включена и дала замечания)
    cam = integ.get("camera") or {}
    if cam.get("remarks"):
        factors.append("camera")
        pts += 1
        human_parts.append("замечания камеры во время теста")

    base_pts = int(integ.get("points") or 0)
    risk_points = max(pts, base_pts + (2 if decoy_hit else 0))
    honesty_index = round(max(0.0, 1.0 - 0.15 * risk_points), 2)
    needs_followup = risk_points >= 2 or decoy_hit
    followup_kind = ("oral_defense" if ("paste_origin" in factors or "copy_decoy" in factors or "person_fit" in factors)
                     else "stage2") if needs_followup else None

    if needs_followup:
        joined = "; ".join(human_parts) if human_parts else "совокупность сигналов прохождения"
        employer_reason = (
            f"Назначен дополнительный проверочный этап ({'3-минутная устная защита' if followup_kind == 'oral_defense' else 'короткий доп. блок заданий у порога'}): "
            f"зафиксированы нетипичные сигналы самостоятельности прохождения ({joined}). "
            f"Попытка не аннулируется — дополнительный этап подтверждает квалификацию кандидата."
        )
        candidate_reason = (
            "Для подтверждения результата на пограничном участке назначен короткий дополнительный этап. "
            "Оценка не обнуляется — это стандартная процедура верификации грейда."
        )
    else:
        employer_reason = "Самостоятельность прохождения подтверждена: показатели времени, фокуса и согласованности ответов в норме."
        candidate_reason = "Замечаний к самостоятельности выполнения нет."

    return {
        "honesty_index": honesty_index,
        "risk_points": risk_points,
        "threshold_points": 2,
        "needs_followup_stage": needs_followup,
        "followup_kind": followup_kind,
        "triggered_factors": factors,
        "decoy_hit": decoy_hit,
        "employer_reason_ru": employer_reason,
        "candidate_reason_ru": candidate_reason,
    }

