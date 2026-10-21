"""Поток ответа Насти: модель → решение первой строкой → текст по предложениям → голос каждого предложения сразу.

Формат ответа модели (см. concierge_brain.SYSTEM_STATIC, «Формат ответа»):
    {"action": "goto", "step": "cand-defense", "point": null, "role": null, "user_name": null, "dir": null, "offer": null}
    Задания каждый раз генерируются заново. Сейчас покажу, как это выглядит.
Первая строка — решение (что сделать), со второй — что сказать голосом. Решение приходит через ≈1,8 с, первое
предложение — через ≈2,0 с (Sonnet 5.5 без рассуждений через ретранслятор, замер 21.10); голос первого предложения
начинается, пока модель дописывает остальное.

Модели: первая из CONCIERGE_BRAIN_MODELS — основная (поток); если её решения нет за CONCIERGE_LLM_HEDGE_S — параллельно
спрашиваем вторую, берём того, кто первым дал решение. Ответ целиком JSON со старым полем reply тоже понимаем.
"""
from __future__ import annotations

import json
import logging
import queue
import re
import threading
import time
from typing import Iterator

log = logging.getLogger("interview.concierge")

_HEAD_KEYS = ("action", "step", "point", "role", "user_name", "dir", "offer", "full")


def _spec(spec: str) -> tuple[str, str, str]:
    prov, _, rest = spec.partition("=")
    if not rest:
        prov, rest = "openrouter", spec
    model, _, effort = rest.partition("@")
    return prov, model, effort


def stream_llm(msgs: list[dict], spec: str, *, max_tokens: int = 420, stop: threading.Event | None = None,
               timeout: float = 12.0) -> Iterator[str]:
    """Куски текста ответа модели по мере генерации (SSE через ретранслятор). Ошибка — исключение."""
    import httpx

    from app.core.config import get_settings
    from app.modules.interview import concierge_brain as brain
    from app.modules.llm import client as llm

    prov, model, effort = _spec(spec)
    use = msgs if model.startswith("anthropic/") else brain._flat(msgs)
    url, headers, extra = llm._endpoint(prov, get_settings())
    body = {"model": model, "messages": use, "temperature": 0.35, "max_tokens": max_tokens, "stream": True, **extra}
    if effort.startswith("~") and effort[1:].isdigit():
        body["reasoning"] = {"max_tokens": int(effort[1:])}
        body["max_tokens"] = max_tokens + int(effort[1:])
    elif effort:
        body["reasoning"] = {"effort": effort}
    with brain._client().stream("POST", url, headers=headers, json=body,
                                timeout=httpx.Timeout(timeout, connect=5)) as r:
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}")
        for line in r.iter_lines():
            if stop is not None and stop.is_set():
                return
            if not line.startswith("data: "):
                continue
            d = line[6:].strip()
            if d == "[DONE]":
                return
            try:
                j = json.loads(d)
            except ValueError:
                continue
            if j.get("error"):
                raise RuntimeError(str(j["error"])[:120])
            c = ((j.get("choices") or [{}])[0].get("delta") or {}).get("content") or ""
            if c:
                yield c


def parse_head(line: str) -> dict | None:
    """Первая строка ответа — JSON решения. Не JSON — None."""
    t = (line or "").strip().strip("`").strip()
    if t.startswith("json"):
        t = t[4:].strip()
    if not t.startswith("{"):
        return None
    try:
        d = json.loads(t)
    except ValueError:
        m = re.search(r"\{.*\}", t)
        if not m:
            return None
        try:
            d = json.loads(m.group(0))
        except ValueError:
            return None
    return d if isinstance(d, dict) else None


class Splitter:
    """Режет поток текста на фразы для голоса — только по концу предложения: разрез по запятой давал интонацию конца
    фразы посреди предложения («а имя, | пол и возраст»), естественность важнее 0,2 с. Исключение — первое предложение
    длиннее first_cut знаков: режется по тире не ближе 60 знаков от начала."""

    END = re.compile(r"([.?…!]+)(\s+|$)")

    def __init__(self, first_cut: int = 260):
        self.buf = ""
        self.n = 0
        self.first_cut = first_cut

    def feed(self, s: str) -> list[str]:
        self.buf += s
        out: list[str] = []
        while True:
            m = None
            for mm in self.END.finditer(self.buf):
                if mm.group(2) or False:   # конец предложения и за ним пробел — фраза готова
                    m = mm
                    break
            if m is None:
                if self.n == 0 and len(self.buf) > self.first_cut:
                    cut = self.buf.rfind(" — ", 60, self.first_cut)
                    if cut > 0:
                        out.append(self.buf[:cut].strip())
                        self.buf = self.buf[cut + 3:]
                        self.n += 1
                        continue
                break
            piece = self.buf[:m.end(1)].strip()
            self.buf = self.buf[m.end():]
            if piece:
                out.append(piece)
                self.n += 1
        return out

    def flush(self) -> list[str]:
        p = self.buf.strip()
        self.buf = ""
        return [p] if p else []


def _head_of(buf: str) -> tuple[dict | None, str, bool]:
    """Из начала ответа: (решение, остаток текста, готово ли). Не готово — ждём ещё кусок."""
    st = buf.lstrip()
    if not st:
        return None, "", False
    if st.startswith("`"):
        st = st.lstrip("`")
        if st.startswith("json"):
            st = st[4:]
        st = st.lstrip()
        if not st:
            return None, "", False
    if st.startswith("{"):
        if '"reply"' in st[:400]:
            return None, "", False   # старый формат целиком JSON — ждём конца ответа
        if "\n" not in st:
            # решение одной строкой без перевода — может прийти сразу с текстом: «{...} Текст»
            depth, end = 0, -1
            for i, ch in enumerate(st):
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        end = i
                        break
            if end < 0 or len(st) <= end + 1:
                return None, "", False
            first, rest = st[:end + 1], st[end + 1:]
        else:
            first, _, rest = st.partition("\n")
        rest = rest.lstrip("`").lstrip()
        h = parse_head(first)
        return (h if h is not None else {"action": "answer"}), (rest if h is not None else st), True
    return {"action": "answer"}, st, True   # сразу заговорила текстом — ответ без действия


def brain_events(msgs: list[dict], models: list[str], *, hedge_s: float = 2.5, deadline_s: float = 9.0,
                 stop: threading.Event | None = None) -> Iterator[tuple]:
    """События ответа: ("head", решение, модель, мс) один раз, затем ("text", кусок)…, в конце ("done", модель, мс).
    Основная (первая) и страховка (вторая) спрашиваются сразу; решение основной берём, если оно пришло до hedge_s,
    иначе — первое готовое. Ничего не пришло — ("fail",)."""
    q: queue.Queue = queue.Queue()
    models = models[:2]
    stops = [threading.Event() for _ in models]
    t0 = time.monotonic()

    def run(k: int, spec: str) -> None:
        buf = ""
        head_sent = False
        try:
            for c in stream_llm(msgs, spec, stop=stops[k]):
                if stops[k].is_set():
                    return
                if head_sent:
                    q.put(("text", k, c))
                    continue
                buf += c
                h, rest, ready = _head_of(buf)
                if ready:
                    head_sent = True
                    q.put(("head", k, h))
                    if rest:
                        q.put(("text", k, rest))
            if not head_sent and buf.strip():
                from app.modules.interview import concierge_brain as brain
                from app.modules.llm import client as llm

                st = buf.strip().strip("`")
                d = llm._extract_json(st) or brain._salvage(st)
                if isinstance(d, dict) and isinstance(d.get("reply"), str) and d["reply"].strip():
                    q.put(("head", k, {x: d.get(x) for x in _HEAD_KEYS}))
                    q.put(("text", k, d["reply"]))
                elif not st.startswith("{"):
                    q.put(("head", k, {"action": "answer"}))
                    q.put(("text", k, st))
                elif parse_head(st.removeprefix("json").strip()) is not None:
                    q.put(("head", k, parse_head(st.removeprefix("json").strip())))   # только решение, без слов
        except Exception as e:  # noqa: BLE001 — сбой одной модели не роняет разговор
            log.warning("concierge stream %s: %s за %d мс", spec, str(e)[:80] or type(e).__name__,
                        int((time.monotonic() - t0) * 1000))
        finally:
            q.put(("end", k, None))

    if not models:
        yield ("fail",)
        return
    for k, spec in enumerate(models):
        threading.Thread(target=run, args=(k, spec), name=f"concierge-llm-{k}", daemon=True).start()
    heads: dict[int, tuple[dict, int]] = {}
    texts: dict[int, list[str]] = {k: [] for k in range(len(models))}
    ended: set[int] = set()
    win: int | None = None
    deadline = t0 + deadline_s

    def choose(k: int) -> Iterator[tuple]:
        for j, e in enumerate(stops):
            if j != k:
                e.set()
        yield ("head", heads[k][0], models[k], heads[k][1])
        for c in texts[k]:
            yield ("text", c)
        texts[k].clear()

    while True:
        if stop is not None and stop.is_set():
            for e in stops:
                e.set()
            return
        now = time.monotonic()
        if win is None:
            if now > deadline:
                for e in stops:
                    e.set()
                yield ("fail",)
                return
            pick = None
            if 0 in heads:
                pick = 0
            elif heads and (now - t0 >= hedge_s or 0 in ended):
                pick = min(heads)
            if pick is not None:
                win = pick
                yield from choose(win)
                if win in ended:
                    yield ("done", models[win], int((time.monotonic() - t0) * 1000))
                    return
                deadline = t0 + 30
                continue
            if len(ended) >= len(models):
                yield ("fail",)
                return
        try:
            kind, k, v = q.get(timeout=0.05 if win is None else 0.5)
        except queue.Empty:
            if win is not None and time.monotonic() > deadline:
                return
            continue
        if kind == "head":
            heads[k] = (v, int((time.monotonic() - t0) * 1000))
        elif kind == "text":
            if win is None:
                texts[k].append(v)
            elif k == win:
                yield ("text", v)
        elif kind == "end":
            ended.add(k)
            if win is not None and k == win:
                yield ("done", models[win], int((time.monotonic() - t0) * 1000))
                return
