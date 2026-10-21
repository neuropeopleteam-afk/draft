"""Настя голосом объясняет кандидату итог теста (21.10, список улучшений Победы, п. 4).

Браузер присылает текст экрана результата (заголовок, итог, разбор, «что подтянуть» — то, что кандидат уже видит);
модель Насти пересказывает его голосом в 3–5 коротких фразах, строго по этому тексту, без новых чисел и тем.
Поток — как у ответов Насти: каждая фраза сразу в синтез (быстрая модель голоса), NDJSON: say → pcm… → end.
"""
from __future__ import annotations

import base64
import json
import logging
import queue
import re
import threading
import time
from typing import Iterator

log = logging.getLogger("interview.concierge")

SYSTEM = """Ты Настя, ИИ-проводник платформы «Драфт», говоришь с кандидатом голосом сразу после его теста на грейд.
Объясни итог в 3–5 коротких фразах, тепло и по делу, на «вы»: какой уровень получился и насколько он уверенный; что \
получилось хорошо; что подтянуть (одна-две темы); что дальше — финальный этап: короткий разговор со мной по его же \
ответам, уровень он не меняет.
Только из текста экрана ниже: не придумывай чисел, тем, навыков и оценок, которых там нет. Если чего-то нет — не говори \
об этом. Не обещай работу и зарплату. Не говори «предварительно» и «тета»: если уверенности не хватило — «нужен \
дополнительный этап». Без списков и markdown — обычная речь, проценты словами в правильном падеже."""


def _j(d: dict) -> bytes:
    return (json.dumps(d, ensure_ascii=False) + "\n").encode()


def explain_stream(screen: str) -> Iterator[bytes]:
    from app.modules.interview import concierge as cg  # noqa: F811
    from app.modules.interview import concierge_brain as brain
    from app.modules.interview import concierge_stream as cs

    t0 = time.monotonic()
    text = re.sub(r"[ \t]+", " ", screen or "").strip()[:4000]
    msgs = [{"role": "system", "content": [{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}]},
            {"role": "user", "content": f"Текст экрана результата:\n{text}\n\nОбъясни мне итог голосом."}]
    yield _j({"t": "ack"})
    stop = threading.Event()
    ev = cs.brain_events(msgs, brain.LLM_MODELS, hedge_s=brain.STREAM_HEDGE_S, deadline_s=10.0, stop=stop)
    jobs: queue.Queue = queue.Queue()

    def tts_job(t: str, cq: queue.Queue) -> None:
        try:
            for chunk in cg.synth_stream(t, "pcm24", live=True):
                cq.put(("pcm", chunk))
        except Exception as e:  # noqa: BLE001
            cq.put(("err", type(e).__name__))
        finally:
            cq.put(("end", None))

    def producer() -> None:
        sp = cs.Splitter()
        total = 0
        try:
            for e in ev:
                if e[0] == "text":
                    for x in sp.feed(e[1]):
                        t = cg._clean_reply(x)
                        if t and total < 600:
                            total += len(t)
                            cq: queue.Queue = queue.Queue()
                            threading.Thread(target=tts_job, args=(t, cq), daemon=True).start()
                            jobs.put((t, cq))
                elif e[0] in ("done", "fail"):
                    break
            for x in sp.flush():
                t = cg._clean_reply(x)
                if t and total < 600:
                    cq = queue.Queue()
                    threading.Thread(target=tts_job, args=(t, cq), daemon=True).start()
                    jobs.put((t, cq))
        except Exception as e:  # noqa: BLE001
            log.warning("concierge explain: %s", type(e).__name__)
        finally:
            jobs.put(None)

    threading.Thread(target=producer, daemon=True).start()
    said: list[str] = []
    first = None
    while True:
        try:
            j = jobs.get(timeout=25)
        except queue.Empty:
            break
        if j is None:
            break
        t, cq = j
        if said:
            yield _j({"t": "pcm", "b64": cg._GAP_B64})   # пауза между фразами (синтез срезает тишину в начале)
        said.append(t)
        yield _j({"t": "say", "text": t})
        while True:
            try:
                kind, v = cq.get(timeout=25)
            except queue.Empty:
                break
            if kind == "pcm":
                if first is None:
                    first = int((time.monotonic() - t0) * 1000)
                yield _j({"t": "pcm", "b64": base64.b64encode(v).decode()})
            elif kind == "err":
                yield _j({"t": "voice_error", "v": v})
            else:
                break
    stop.set()
    if not said:
        yield _j({"t": "say", "text": "Итог — на экране: уровень, разбор и что подтянуть. Дальше — короткий разговор со мной."})
    yield _j({"t": "end", "text": " ".join(said), "ms": int((time.monotonic() - t0) * 1000)})
    log.info("concierge explain: фраз %d, голос %s мс", len(said), first)
