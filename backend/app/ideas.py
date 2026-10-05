"""Нестандартные решения 9 и 10: «Кабинет ФСП» и «Кубок работодателя» — подключение роутеров одним местом."""
from __future__ import annotations

from fastapi import FastAPI

from app.cup.router import TAGS as CUP_TAGS
from app.cup.router import candidate_router as cup_candidate_router
from app.cup.router import employer_router as cup_employer_router
from app.fsp_cabinet.router import TAGS as FSP_CABINET_TAGS
from app.fsp_cabinet.router import router as fsp_cabinet_router

TAGS = CUP_TAGS + FSP_CABINET_TAGS


def include_routers(app: FastAPI) -> None:
    for r in (cup_employer_router, cup_candidate_router, fsp_cabinet_router):
        app.include_router(r)
