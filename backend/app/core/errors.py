"""Единый формат ошибок API: {"detail": {"code": "...", "message": "..."}}."""
from fastapi import HTTPException
from pydantic import BaseModel


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    detail: ErrorDetail


def api_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def err(description: str) -> dict:
    return {"model": ErrorResponse, "description": description}
