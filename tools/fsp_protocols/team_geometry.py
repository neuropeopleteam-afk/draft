"""Геометрия таблицы командного протокола: сколько строк участников в каждом блоке команды.

Модель хорошо читает ФИО по порядку, но ошибается в границах объединённых ячеек «место/команда».
Границы блоков видны на изображении: в колонке «Место» горизонтальная линия есть только между командами,
в колонке «Состав» — между всеми участниками. Считаем линии и получаем точное число участников в каждом
блоке, затем режем упорядоченный список ФИО от модели по этим числам.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image


def _groups(xs: list[int], gap: int = 3) -> list[int]:
    out: list[list[int]] = []
    for x in xs:
        if out and x - out[-1][-1] <= gap:
            out[-1].append(x)
        else:
            out.append([x])
    return [(g[0] + g[-1]) // 2 for g in out]


def block_row_counts(img_path: Path, *, dark: int = 140, vthr: float = 0.5, hthr: float = 0.85,
                     place_col: int = 0, fio_col: int = 2) -> dict:
    """Вернуть {"vlines", "team_borders", "row_borders", "counts"} для страницы протокола.

    place_col / fio_col — номер колонки (0 — «Место», 2 — «Состав» в протоколах КР/ЧР; у протоколов
    с колонкой «Статус» номера те же, лишние колонки правее).
    """
    im = np.array(Image.open(img_path).convert("L")) < dark
    h, w = im.shape
    # вертикальные линии ищем в нижних 2/3 страницы (над таблицей — шапка документа)
    band = im[int(h * 0.35): int(h * 0.95)]
    v = _groups([x for x in range(w) if band[:, x].mean() > vthr], gap=4)
    # утолщаем по вертикали на ±2 px — линии слегка наклонены на сканах
    im = im | np.roll(im, 1, axis=0) | np.roll(im, -1, axis=0) | np.roll(im, 2, axis=0) | np.roll(im, -2, axis=0)
    if len(v) < fio_col + 2:
        return {"vlines": v, "team_borders": [], "row_borders": [], "counts": []}

    def hlines(x0: int, x1: int) -> list[int]:
        seg = im[:, x0 + 3: x1 - 3]
        f = seg.mean(axis=1)
        return _groups([y for y in range(h) if f[y] > hthr])

    team = hlines(v[place_col], v[place_col + 1])
    rows = hlines(v[fio_col], v[fio_col + 1])
    # шапка таблицы: первая граница «Состава», выше которой нет участников, — по первой линии блока
    counts = []
    for a, b in zip(team, team[1:]):
        counts.append(max(0, sum(1 for y in rows if a - 3 <= y <= b + 3) - 1))
    return {"vlines": v, "team_borders": team, "row_borders": rows, "counts": counts}


def _otsu(a: np.ndarray) -> int:
    hist = np.bincount(a.ravel(), minlength=256).astype(float)
    p = hist / hist.sum()
    w = np.cumsum(p)
    mu = np.cumsum(p * np.arange(256))
    s = (mu[-1] * w - mu) ** 2 / (w * (1 - w) + 1e-12)
    return int(np.argmax(s))


def _deskew(img: Image.Image) -> tuple[float, Image.Image]:
    """Угол наклона листа (−2…2°, шаг 0,1°) по максимуму резкости горизонтальной проекции."""
    small = img.resize((img.width // 2, img.height // 2))
    best = (0.0, -1.0)
    for a in np.arange(-2.0, 2.01, 0.1):
        r = np.array(small.rotate(float(a), resample=Image.BILINEAR, fillcolor=255)) < 160
        s = float((r.sum(axis=1).astype(float) ** 2).sum())
        if s > best[1]:
            best = (round(float(a), 2), s)
    return best[0], (img.rotate(best[0], resample=Image.BILINEAR, fillcolor=255) if best[0] else img)


def block_row_counts_v2(img_path: Path, *, hthr: float = 0.85, place_col: int = 0, fio_col: int = 2) -> dict:
    """Как block_row_counts, но устойчивее к сканам (переезд 16): выравнивание наклона, порог тёмного по Оцу
    (серые линии), вертикальные линии ищутся между первой и последней сплошной горизонтальной линией таблицы,
    а не в фиксированной полосе страницы (короткие таблицы над подписями). Фотографии листа с перспективой
    (КР-2026 робототехника) не выравниваются — для них counts остаётся пустым."""
    angle, img = _deskew(Image.open(img_path).convert("L"))
    g = np.array(img)
    dark = min(220, max(140, _otsu(g)))
    im = g < dark
    h, w = im.shape
    imv = im.copy()
    for s in (1, 2, -1, -2):
        imv |= np.roll(im, s, axis=0)
    rowfrac = imv.mean(axis=1)
    hl_all = _groups([y for y in range(h) if rowfrac[y] > 0.6])
    res = {"angle": angle, "dark": dark, "vlines": [], "team_borders": [], "row_borders": [], "counts": []}
    if len(hl_all) < 3:
        return res
    y0, y1 = hl_all[0], hl_all[-1]
    imh = im.copy()
    for s in (1, 2, -1, -2):
        imh |= np.roll(im, s, axis=1)
    colfrac = imh[y0:y1].mean(axis=0)
    v = _groups([x for x in range(w) if colfrac[x] > 0.5], gap=8)
    res["vlines"] = v
    if len(v) < fio_col + 2:
        return res

    def hlines(x0: int, x1: int) -> list[int]:
        f = imv[:, x0 + 6: x1 - 6].mean(axis=1)
        return _groups([y for y in range(max(0, y0 - 3), min(h, y1 + 4)) if f[y] > hthr])

    team = hlines(v[place_col], v[place_col + 1])
    rows = hlines(v[fio_col], v[fio_col + 1])
    res.update(team_borders=team, row_borders=rows,
               counts=[max(0, sum(1 for y in rows if a - 3 <= y <= b + 3) - 1) for a, b in zip(team, team[1:])])
    return res
