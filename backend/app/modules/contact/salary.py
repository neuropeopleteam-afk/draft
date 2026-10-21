"""Зарплата «до вычета НДФЛ» или «на руки» и пересчёт между ними.

* Предложения (приглашение, зонд, вакансия, кубок, встречное предложение) хранят основание суммы
  ``salary_basis``: ``gross`` — до вычета НДФЛ (по умолчанию, как в трудовом договоре), ``net`` — на руки.
* Рыночный диапазон категории — открытые данные рынка и офферы на платформе: суммы указываются **на руки после
  вычета налога**. Поэтому рынок — ``net``.
* Сравнения с рынком и со скрытым минимумом кандидата (минимум — на руки) делаются в одном основании.

Пересчёт — прогрессивная шкала НДФЛ для налоговых резидентов с 2025 года (п. 1 ст. 224 НК РФ): 13 % до 2,4 млн ₽
в год, 15 % — 2,4–5 млн, 18 % — 5–20 млн, 20 % — 20–50 млн, 22 % — свыше 50 млн; ставка применяется к части
дохода сверх порога. Месячная сумма считается как среднее за год (12 одинаковых выплат) без вычетов — это
оценка «≈», а не расчётный листок.
"""
from __future__ import annotations

from typing import Literal

Basis = Literal["gross", "net"]
BASIS_TITLES = {"gross": "до вычета НДФЛ", "net": "на руки"}
MARKET_BASIS: Basis = "net"
MARKET_SOURCE_NOTE = "открытые данные рынка и офферы на платформе, суммы на руки после вычета НДФЛ"
# (верхняя граница годового дохода, ставка); None — без верхней границы
NDFL_SCALE: list[tuple[int | None, float]] = [
    (2_400_000, 0.13), (5_000_000, 0.15), (20_000_000, 0.18), (50_000_000, 0.20), (None, 0.22)]


def ndfl_year(income: float) -> float:
    """НДФЛ с годового дохода по прогрессивной шкале."""
    tax, lower = 0.0, 0
    for upper, rate in NDFL_SCALE:
        top = income if upper is None else min(income, upper)
        if top > lower:
            tax += (top - lower) * rate
        if upper is None or income <= upper:
            break
        lower = upper
    return tax


def net_of(gross_month: int) -> int:
    """≈ на руки в месяц по сумме до вычета НДФЛ."""
    year = 12 * gross_month
    return int(round((year - ndfl_year(year)) / 12))


def gross_of(net_month: int) -> int:
    """≈ до вычета НДФЛ по сумме на руки (обратная к net_of, монотонна — бисекция)."""
    lo, hi = float(net_month), float(net_month) / 0.78 + 1
    for _ in range(60):
        mid = (lo + hi) / 2
        if net_of(int(round(mid))) < net_month:
            lo = mid
        else:
            hi = mid
    return int(round(hi))


def convert(v: int, frm: str, to: str) -> int:
    if frm == to:
        return v
    return net_of(v) if frm == "gross" else gross_of(v)


def to_net(v: int, basis: str | None) -> int:
    return convert(v, basis or "gross", "net")


def basis_title(basis: str | None) -> str:
    return BASIS_TITLES.get(basis or "gross", BASIS_TITLES["gross"])


def basis_out(basis: str | None) -> dict:
    b = basis or "gross"
    return {"salary_basis": b, "salary_basis_title": BASIS_TITLES.get(b, BASIS_TITLES["gross"])}


def market_out(lo: int | None, hi: int | None, median: int | None = None) -> dict:
    """Пометка источника и основания рыночного диапазона, с оценкой «до вычета НДФЛ»."""
    out = {"basis": MARKET_BASIS, "basis_title": BASIS_TITLES[MARKET_BASIS], "source_note": MARKET_SOURCE_NOTE}
    if lo and hi:
        out["gross_from"], out["gross_to"] = gross_of(lo), gross_of(hi)
        if median:
            out["gross_median"] = gross_of(median)
    return out
