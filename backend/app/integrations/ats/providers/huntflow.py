"""Хантфлоу (публичный API v2) в общем интерфейсе провайдера. Клиент — app.integrations.ats.clients.HuntflowClient.

* ``GET /me``, ``GET /accounts`` — проверка токена; ``GET /accounts/{id}/vacancies`` — вакансии для выбора;
* ``GET /accounts/{id}/vacancies/statuses`` — этапы подбора;
* ``POST /accounts/{id}/applicants`` — кандидат; ``POST /accounts/{id}/applicants/{applicant_id}/vacancy`` —
  на вакансию и этап (тот же вызов меняет этап, поэтому повтор безопасен).
"""
from __future__ import annotations

from app.integrations.ats import profile as prof
from app.integrations.ats.clients import HuntflowClient
from app.integrations.ats.providers.base import LinkState, Provider, Target

DOCS_URL = "https://api.huntflow.ru/v2/docs"


def applicant_body(d: dict) -> dict:
    last, first = d["last_name"], d["first_name"]
    if not last:
        last, first = d["ref"], "Кандидат"
    body = {"last_name": last, "first_name": first, "middle_name": d["middle_name"], "email": d["email"],
            "phone": d["phone"], "position": d["category_title"],
            "money": f"{d['salary_from']}–{d['salary_to']} ₽ (вилка предложения)",
            "externals": [{"auth_type": "NATIVE", "data": {"body": prof.as_text(d)}}]}
    if d["telegram"]:
        body["social"] = [{"social_type": "TELEGRAM", "value": d["telegram"]}]
    return {k: v for k, v in body.items() if v not in (None, "")}


class HuntflowProvider(Provider):
    code, title = "huntflow", "Хантфлоу"

    def __init__(self, client: HuntflowClient, account_id: int | None):
        self.cl, self.account_id = client, account_id

    def check(self) -> dict:
        me = self.cl.me()
        accounts = self.cl.accounts()
        statuses = self.cl.statuses(self.account_id) if self.account_id else []
        return {"ok": True, "account": me.get("name"), "me": {"id": me.get("id"), "name": me.get("name")},
                "accounts": [{"id": a.get("id"), "name": a.get("name")} for a in accounts],
                "statuses": [{"id": s.get("id"), "name": s.get("name"), "order": s.get("order")} for s in statuses],
                "details": [f"Токен действителен (GET /me): {me.get('name')}",
                            "Организации: " + ", ".join(f"{a.get('name')} (id {a.get('id')})" for a in accounts)]}

    def vacancies(self) -> list[dict]:
        if not self.account_id:
            return []
        items = self.cl._req("GET", f"/accounts/{self.account_id}/vacancies?count=100").get("items", [])
        return [{"id": v["id"], "title": v.get("position"), "status": (v.get("state") or "").lower(),
                 "department": v.get("company")} for v in items]

    def stages(self, vacancy_id: int) -> list[dict]:
        items = sorted(self.cl.statuses(self.account_id), key=lambda s: s.get("order", 0)) if self.account_id else []
        return [{"id": s["id"], "title": s.get("name")} for s in items if not s.get("removed")]

    def push(self, d: dict, target: Target, link: LinkState, *, force: bool = False) -> dict:
        steps: list[str] = []
        aid = int(link.external_id) if link.external_id else None
        dedup = "link" if aid else None
        if aid is None:
            created = self.cl.create_applicant(self.account_id, applicant_body(d))
            aid = created.get("id")
            link.save(external_id=aid)
            steps.append(f"Создан кандидат (POST /applicants, id {aid})")
        else:
            steps.append(f"Кандидат уже есть в Хантфлоу (id {aid}) — новый не создаём")
        res = {"applicant_id": aid, "external_id": aid, "dedup": dedup, "steps": steps}
        vid = target.vacancy_id
        if vid and aid and (force or not link.on_vacancy(vid)):
            status_id = target.stage_id or next((s["id"] for s in self.stages(vid)), None)
            if status_id:
                comment = prof.offer_text(d) if not dedup else "Повторная передача с платформы «Встречный»"
                lk = self.cl.add_to_vacancy(self.account_id, aid, vid, status_id, comment)
                link.save(vacancy={"id": vid, "join_id": lk.get("id")})
                res.update({"vacancy_id": vid, "status_id": status_id, "link_id": lk.get("id")})
                steps.append(f"На вакансии {vid}, этап {status_id} (POST /applicants/{aid}/vacancy)")
        elif vid:
            res.update({"vacancy_id": vid})
            steps.append(f"Уже на вакансии {vid} — повтор без изменений")
        return res
