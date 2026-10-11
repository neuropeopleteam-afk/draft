"""Ошибки движка: один класс с кодом (контракт engine/CONTRACT.md, раздел 2). Модуль interview переводит в HTTP."""


class EngineError(Exception):
    STATUS = {"insufficient_context": 422, "bad_request": 400, "jury_limit": 429, "daily_cap": 429,
              "stt_unavailable": 503, "avatar_unavailable": 503, "finished": 409}

    def __init__(self, code: str, message: str, *, status: int | None = None, retry_after: int | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status or self.STATUS.get(code, 400)
        self.retry_after = retry_after

    def to_dict(self) -> dict:
        d = {"error": self.code, "message": self.message}
        if self.retry_after is not None:
            d["retry_after"] = self.retry_after
        return d
