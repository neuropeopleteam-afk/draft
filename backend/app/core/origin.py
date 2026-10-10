"""Я8 (п. 4): единые метки происхождения данных интеграций — ФСП, ФНС (ЕГРЮЛ), ATS.

Четыре метки на всю платформу (фронт — ``frontend/src/components/Origin.tsx``, те же подписи; тест сверяет):

* ``model`` — «модельные данные»: сведения сгенерированы для демо (демо-паспорт ФСП, демо-сведения ФНС у
  демо-компаний без ИНН); на решения работодателя в демо влияют, но о реальных людях и компаниях ничего не говорят;
* ``stub`` — «заглушка по спецификации»: настоящий HTTP-обмен тем же кодом, что и с внешней системой, но отвечает
  наша заглушка по публичной спецификации (демо-ATS, демо-стенд ФСП ID в Keycloak, демо-реестр ФСП);
* ``real`` — «реальный запрос»: ответ внешней системы (egrul.nalog.ru, реестр ФСП, ATS с токеном владельца
  аккаунта и успешной проверкой связи);
* ``unverified`` — «не проверено»: запроса не было или он не удался (капча ФНС, нет ИНН, нет токена ATS).

Метка — только подпись источника, на расчёты (индекс доверия, бонус ФСП, ранжирование) не влияет.
"""
from __future__ import annotations

ORIGIN: dict[str, str] = {
    "model": "модельные данные",
    "stub": "заглушка по спецификации",
    "real": "реальный запрос",
    "unverified": "не проверено",
}
HINT: dict[str, str] = {
    "model": "сведения сгенерированы для демонстрации, о реальных людях и компаниях не говорят",
    "stub": "обмен идёт по настоящему HTTP тем же кодом, но отвечает наша заглушка по публичной спецификации системы",
    "real": "ответ внешней системы",
    "unverified": "запроса не было или он не удался — сведения не подтверждены",
}
# Отсутствие истории ФСП (судья п. 17): без штрафа, а подтверждённые достижения — бонус. Одна фраза везде.
NO_FSP = "Истории ФСП нет — без штрафа; подтверждённые достижения ФСП дают бонус"
NO_FSP_SHORT = "без штрафа; подтверждённые достижения ФСП дают бонус"


def tag(kind: str, note: str | None = None) -> dict:
    """Метка происхождения: код, подпись, пояснение (что именно за источник)."""
    return {"kind": kind, "label": ORIGIN[kind], "note": note or HINT[kind]}


def fns_origin(registry: dict | None) -> dict:
    """Сведения ФНС в индексе доверия: статус проверки ЕГРЮЛ → метка."""
    st = (registry or {}).get("status")
    if st in ("demo_found", "demo_not_found"):
        return tag("model", "демо-сведения ФНС у демо-компании без ИНН — запроса в ФНС не было")
    if st in ("found", "not_found", "invalid"):
        when = (registry or {}).get("checked_at")
        return tag("real", "egrul.nalog.ru" + (f", проверено {when[:10]}" if when else ""))
    why = {"captcha": "ФНС ответила капчей", "error": "ФНС не ответила", "pending": "проверка ещё не выполнялась",
           "no_inn": "работодатель не указал ИНН"}.get(st or "", "проверки ФНС нет")
    return tag("unverified", why)


def fsp_origin(link_source: str | None, raw: dict | None = None, *, fsp_id_demo: bool | None = None) -> dict | None:
    """Паспорт ФСП: способ связи (demo / keycloak / registry) и режим реестра → метка; паспорта нет — None."""
    if not link_source:
        return None
    reg = (raw or {}).get("registry") or {}
    if link_source == "demo":
        return tag("model", "демо-паспорт ФСП: реестр ФСП на хакатоне недоступен")
    if reg.get("demo") or reg.get("mode") == "mock":
        return tag("stub", "демо-реестр ФСП по спецификации API реестра")
    if link_source == "keycloak":
        if fsp_id_demo is None:
            from app.integrations.settings import get_isettings

            fsp_id_demo = get_isettings().fsp_id_demo
        return (tag("stub", "вход через демо-стенд ФСП ID (Keycloak, OIDC)") if fsp_id_demo
                else tag("real", "вход через ФСП ID (OIDC)"))
    if reg.get("mode") == "external":
        return tag("real", "API реестра ФСП")
    return tag("unverified", "источник паспорта не записан")


def ats_origin(mode: str | None, token_set: bool, last_check_ok: bool | None = None) -> dict:
    """ATS: демо-режим — заглушка по спецификации; реальный — «реальный запрос» только после успешной проверки связи."""
    if mode == "demo":
        return tag("stub")
    if not token_set:
        return tag("unverified", "токен владельца аккаунта не задан")
    if last_check_ok:
        return tag("real", "API системы с токеном владельца аккаунта, проверка связи успешна")
    return tag("unverified", "токен задан, проверка связи не пройдена или не выполнялась")
