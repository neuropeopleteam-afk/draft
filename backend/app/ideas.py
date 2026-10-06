"""Нестандартные решения 9, 10 и 13: «Кабинет ФСП», «Кубок работодателя», живая демонстрация для жюри (QR →
мини-тест → автоприглашение) — подключение роутеров одним местом."""
from __future__ import annotations

from fastapi import FastAPI

from app.cup.router import TAGS as CUP_TAGS
from app.cup.router import candidate_router as cup_candidate_router
from app.cup.router import employer_router as cup_employer_router
from app.fsp_cabinet.router import TAGS as FSP_CABINET_TAGS
from app.fsp_cabinet.router import router as fsp_cabinet_router
from app.jury_live.router import TAGS as JURY_LIVE_TAGS
from app.jury_live.router import router as jury_live_router

TAGS = CUP_TAGS + FSP_CABINET_TAGS + JURY_LIVE_TAGS


def include_routers(app: FastAPI) -> None:
    for r in (cup_employer_router, cup_candidate_router, fsp_cabinet_router, jury_live_router):
        app.include_router(r)
