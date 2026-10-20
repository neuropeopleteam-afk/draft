"""База знаний Елены и поиск по ней (RAG): BM25 по блокам concierge_kb.md с лёгким русским стеммингом.

Блоки — по экранам и темам стенда (формат описан в начале concierge_kb.md). На каждый ход в подсказку модели идут:
карта сайта (заголовки всех блоков одной строкой), блоки текущего экрана и шага обзора и лучшие по запросу.
Живые цифры проверки (точность, атаки) подмешиваются отдельным блоком из concierge.numbers_chunk().
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

KB_PATH = Path(__file__).with_name("concierge_kb.md")

_SUFFIXES = sorted("""
иями ями ами иях ях ах ией ией ием ем иям ям ом ев ов ей ий ый ой ая яя ое ее ые ие ую юю ого его ому ему ыми ими
ость ости остью ение ения ению ением ений ании ание ания ировать ировал ируют ирует ывает ивает ают яют ует ют ут ит ет
ать ять ить еть оть ла ло ли ал ял ил ел ешь ишь ете ите ем им ся сь ться тся ая ы и а я о е у ю ь
""".split(), key=len, reverse=True)

_WORD = re.compile(r"[a-zа-яё0-9]+", re.I)
_STOP = set("""
а и в во на по о об от до из за к ко с со у же ли бы не ни но да то это этот эта эти тот та те как что чем кто где когда
зачем почему какой какая какие каким какую сколько ещё еще уже вот вы ты мы я он она они его её ее их мне меня вам вас
нам нас там тут здесь есть быть был была было были будет можно нужно надо очень просто ну так или для при над под про
""".split())


def stem(word: str) -> str:
    w = word.lower().replace("ё", "е")
    if len(w) <= 4 or not re.match(r"[а-я]", w):
        return w
    for s in _SUFFIXES:
        if w.endswith(s) and len(w) - len(s) >= 3:
            return w[: -len(s)]
    return w


def tokens(text: str) -> list[str]:
    out = []
    for m in _WORD.findall(text or ""):
        lw = m.lower()
        if lw in _STOP or len(lw) < 2:
            continue
        out.append(stem(lw))
    return out


@dataclass
class Chunk:
    id: str
    title: str
    text: str
    paths: list[str] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)
    keys: str = ""

    def body(self) -> str:
        return f"{self.title}. {self.text}"


def parse_kb(raw: str) -> list[Chunk]:
    raw = re.sub(r"<!--.*?-->", "", raw, flags=re.S)
    chunks: list[Chunk] = []
    for part in re.split(r"^## ", raw, flags=re.M)[1:]:
        lines = part.strip().splitlines()
        head = lines[0]
        cid, _, title = head.partition("|")
        ch = Chunk(id=cid.strip(), title=title.strip() or cid.strip(), text="")
        body: list[str] = []
        for ln in lines[1:]:
            s = ln.strip()
            if s.startswith("paths:"):
                ch.paths = s[6:].split()
            elif s.startswith("steps:"):
                ch.steps = s[6:].split()
            elif s.startswith("keys:"):
                ch.keys = s[5:].strip()
            elif s:
                body.append(s)
        ch.text = " ".join(body)
        if ch.id and ch.text:
            chunks.append(ch)
    return chunks


class Index:
    """BM25 (k1=1.4, b=0.6) по заголовку, ключам и тексту блока; заголовок и ключи весят вдвое."""

    def __init__(self, chunks: list[Chunk]):
        self.chunks = chunks
        self.docs: list[list[str]] = []
        for c in chunks:
            self.docs.append(tokens(c.title) * 2 + tokens(c.keys) * 2 + tokens(c.text))
        self.avg = sum(len(d) for d in self.docs) / max(1, len(self.docs))
        df: dict[str, int] = {}
        for d in self.docs:
            for t in set(d):
                df[t] = df.get(t, 0) + 1
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - v + 0.5) / (v + 0.5)) for t, v in df.items()}
        self.tf = []
        for d in self.docs:
            m: dict[str, int] = {}
            for t in d:
                m[t] = m.get(t, 0) + 1
            self.tf.append(m)

    def score(self, query: str) -> list[float]:
        q = tokens(query)
        out = []
        for i, d in enumerate(self.docs):
            s = 0.0
            ln = len(d)
            for t in q:
                f = self.tf[i].get(t)
                if not f:
                    continue
                s += self.idf.get(t, 0) * f * 2.4 / (f + 1.4 * (0.4 + 0.6 * ln / self.avg))
            out.append(s)
        return out


@lru_cache(maxsize=2)
def _index(_mtime: float) -> Index:
    return Index(parse_kb(KB_PATH.read_text(encoding="utf-8")))


def index() -> Index:
    try:
        return _index(KB_PATH.stat().st_mtime)
    except OSError:
        return Index([])


def _path_hit(paths: list[str], current: str) -> bool:
    cur = (current or "/").split("?")[0].rstrip("/") or "/"
    for p in paths:
        p = p.rstrip("/") or "/"
        if p == "/" and cur == "/":
            return True
        if p != "/" and (cur == p or cur.startswith(p + "/")):
            return True
    return False


def site_map() -> str:
    """Карта сайта одной строкой на блок — модель видит всё, что знает, и куда может отвести."""
    return "\n".join(f"- {c.title}" + (f" ({' '.join(c.paths[:2])})" if c.paths else "") for c in index().chunks)


def retrieve(query: str, *, current_path: str = "/", step: str | None = None, extra_text: str = "",
             k: int = 5) -> list[Chunk]:
    """Блоки для ответа: текущий экран и шаг (сколько есть, до двух) + лучшие по запросу (всего до k)."""
    idx = index()
    if not idx.chunks:
        return []
    scores = idx.score(f"{query} {extra_text}")
    ranked = sorted(range(len(idx.chunks)), key=lambda i: scores[i], reverse=True)
    picked: list[int] = []
    for i in ranked:
        if scores[i] <= 0.4 or len(picked) >= k:
            break
        picked.append(i)
    ctx = [i for i, c in enumerate(idx.chunks) if (step and step in c.steps) or _path_hit(c.paths, current_path)]
    ctx.sort(key=lambda i: scores[i], reverse=True)
    for i in ctx[:2]:
        if i not in picked:
            picked.append(i)
    if not picked:
        picked = [0]
    return [idx.chunks[i] for i in picked[: k + 2]]
