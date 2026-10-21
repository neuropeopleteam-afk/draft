"""Матрица прав доступа: ожидаемое поведение каждого маршрута API для каждой роли (tests/test_access_matrix.py).

Как это работает
----------------
Тест обходит ВСЕ маршруты приложения (tests/route_walk.py, включая вложенные роутеры FastAPI 0.142) и для каждой
пары «метод × путь» ищет политику в POLICY. Маршрут без политики роняет тест и печатает готовую строку для вставки.
Политика — имя из POLICIES (роль → ожидание) или кортеж ``("имя", {роль: ожидание})`` с точечными поправками.

Роли (ROLES): кто делает запрос. «Сторона» ресурса определяется ролью: учётки песочницы жюри (``jury_*``) работают
с объектами песочницы A, остальные — с объектами «настоящих» пользователей (кандидат C1, работодатель E1).
  anon                 без токена
  candidate            настоящий кандидат C1 (с категорией, видим работодателям); владелец своих объектов
  employer             настоящий работодатель E1 — владелец потребности, зонда, приглашения, кубка, вакансии
  employer_other       настоящий работодатель другой компании E2 (чужие объекты E1 → 404, кандидат C1 — общий пул)
  admin                UserRole.admin
  fsp_analyst          UserRole.fsp_analyst (Кабинет ФСП)
  expert               UserRole.expert (проверка развёрнутых ответов), не демо
  jury_candidate       кандидат песочницы жюри A (persona candidate) — владелец объектов стороны A
  jury_employer        работодатель песочницы A — владелец объектов стороны A
  jury_expert          эксперт песочницы A
  jury_fsp             аналитик ФСП песочницы A
  jury_other_employer  работодатель ДРУГОЙ песочницы B: объекты и кандидаты песочницы A для него не существуют (404)
  jury_other_candidate кандидат другой песочницы B: объекты песочницы A — 404

Ожидания:
  OK     — доступ есть: статус не 401/403/404 и меньше 500 (2xx, 3xx, 409 бизнес-правило, 422 пустое тело...)
  OK404  — доступ есть, но объект может отсутствовать (404 допустим): проверяется только, что нет 401/403
  401 / 403 / 404 — ровно этот код
  HIDDEN — 403 или 404 (чужой объект)
  ANY    — любой статус < 500 (заглушки сторонних API со своей авторизацией по токену, не JWT)
  OK_UPSTREAM — доступ есть, но маршрут ходит во внешнюю систему (ATS): допустим и 502 «система недоступна»
  SKIP   — роль не вызывает маршрут (например, сброс песочницы отзывает токены всех её персон — проверяется одной)

Как дополнять
-------------
Новый маршрут → строка в POLICY. Если в пути есть параметр, не известный PARAMS в test_access_matrix.py, добавьте
значение в PARAMS (или поправку в PARAM_OVERRIDES здесь); если метод изменяющий и важно проверить владение (политики
*_own / employer_ref), добавьте тело в BODIES — иначе чужак получит 422 раньше проверки владельца, и тест это покажет.
Изменяющие состояние маршруты, после которых другие проверки могут сломаться (сброс песочницы, завершение теста,
отзыв согласия), перечислите в LAST — они выполняются в конце.
Политики для маршрутов веток, ещё не влитых в integ (contact, passport, infra2, tasks, status, realdata, jury-test,
integrity, proctor, 2fa), уже добавлены — несуществующие маршруты тест пропускает молча (внутренний отчёт разработки).
"""
from __future__ import annotations

ROLES = ("anon", "candidate", "employer", "employer_other", "admin", "fsp_analyst", "expert",
         "jury_candidate", "jury_employer", "jury_expert", "jury_fsp", "jury_other_employer", "jury_other_candidate")
JURY_ROLES = tuple(r for r in ROLES if r.startswith("jury_"))

OK, OK404, HIDDEN, ANY, OK_UPSTREAM, SKIP = "ok", "ok404", "hidden", "any", "ok_upstream", "skip"


def _p(default, **over) -> dict[str, object]:
    unknown = set(over) - set(ROLES)
    assert not unknown, unknown
    return {r: over.get(r, default) for r in ROLES}


POLICIES: dict[str, dict[str, object]] = {
    # публичные
    "open": _p(OK),
    "open404": _p(OK404),
    # любой вошедший
    "auth": _p(OK, anon=401),
    "auth404": _p(OK404, anon=401),
    # кандидат (в т. ч. кандидаты песочниц); объекты кандидата — только свои
    "candidate": _p(403, anon=401, candidate=OK, jury_candidate=OK, jury_other_candidate=OK),
    "candidate_own": _p(403, anon=401, candidate=OK, jury_candidate=OK, jury_other_candidate=404),
    # работодатель; объекты компании — только своей; кандидат по ref — общий пул и своя песочница
    "employer": _p(403, anon=401, employer=OK, employer_other=OK, jury_employer=OK, jury_other_employer=OK),
    "employer_own": _p(403, anon=401, employer=OK, employer_other=404, jury_employer=OK, jury_other_employer=404),
    "employer_ref": _p(403, anon=401, employer=OK, employer_other=OK, jury_employer=OK, jury_other_employer=404),
    # то же, но объект в мире теста не создаётся (случайный id): владельцу допустим 404, чужаку — ровно 404
    "candidate_own404": _p(403, anon=401, candidate=OK404, jury_candidate=OK404, jury_other_candidate=404),
    "employer_own404": _p(403, anon=401, employer=OK404, employer_other=404, jury_employer=OK404, jury_other_employer=404),
    # служебные роли
    "admin": _p(403, anon=401, admin=OK),
    "expert": _p(403, anon=401, expert=OK, admin=OK, jury_expert=OK),
    "fsp": _p(403, anon=401, fsp_analyst=OK, admin=OK, jury_fsp=OK),
    # только демо-персоны жюри (сброс и удаление своей песочницы)
    "jury_demo": _p(403, anon=401, **{r: OK for r in JURY_ROLES}),
    # экран живой демонстрации жюри: только работодатель песочницы жюри (настоящий работодатель — 403 jury_sandbox_only)
    "jury_screen": _p(403, anon=401, jury_employer=OK, jury_other_employer=OK),
    # вакансии: видят все вошедшие, кроме чужой песочницы; отклик — кандидат своей песочницы или общего пула
    "vacancy": _p(OK, anon=401, jury_other_employer=404, jury_other_candidate=404),
    "vacancy_apply": _p(403, anon=401, candidate=OK, jury_candidate=OK, jury_other_candidate=404),
    # участник переписки по приглашению (кандидат и работодатель компании), остальным — 404
    "thread_party": _p(404, anon=401, candidate=OK, employer=OK, jury_candidate=OK, jury_employer=OK),
    # демо-набор данных (feat/realdata): только работодатель своей песочницы жюри или админ-демо
    "sandbox_employer": _p(403, anon=401, jury_employer=OK, jury_other_employer=OK),
    # сторонние заглушки ATS: авторизация токеном провайдера, JWT роли не участвуют
    "stub": _p(ANY),
}

Policy = str | tuple[str, dict[str, object]]

# маршруты, которые ходят в ATS: доступ есть, но внешняя система в тестах недоступна (502)
_UPSTREAM = {"employer": OK_UPSTREAM, "employer_other": OK_UPSTREAM, "jury_employer": OK_UPSTREAM,
             "jury_other_employer": OK_UPSTREAM}

_HH_OFF = {"employer": OK404, "employer_other": OK404, "jury_employer": OK404, "jury_other_employer": OK404}
_FSP_OFF = {"fsp_analyst": OK404, "admin": OK404, "jury_fsp": OK404}  # Я29: блок ФСП за TARIFFS_ENABLED (выкл.)

POLICY: dict[tuple[str, str], Policy] = {
    # ---------------------------------------------------------------- система, документация, справочники
    ("GET", "/api/health"): "open",
    ("GET", "/api/meta"): "open",
    ("GET", "/api/docs"): "open",
    ("GET", "/api/redoc"): "open",
    ("GET", "/api/openapi.json"): "open",
    ("GET", "/api/static/{path:path}"): "open",
    ("GET", "/api/catalog"): "open",
    ("GET", "/api/catalog/stack-tags"): "open",
    ("GET", "/api/legal/consents/{kind}"): "open",
    ("GET", "/api/fsp-registry/v1/participants/{fsp_id}/achievements"): "open",  # мок реестра ФСП (демо)
    # ---------------------------------------------------------------- вход и регистрация
    ("POST", "/api/auth/register"): "open",
    ("POST", "/api/auth/login"): "open",
    ("POST", "/api/auth/token"): "open",
    ("POST", "/api/auth/verify-email"): "open",
    ("POST", "/api/auth/resend-code"): "open",
    # второй фактор (feat/2fa, tf01): подключение/проверка/отключение/новые коды — любой вошедший (аноним 401; без тела 422);
    # /verify — второй шаг входа без JWT (промежуточный токен в теле), поэтому открыт; /api/admin/2fa/* — только admin
    ("GET", "/api/auth/2fa"): "auth",
    ("POST", "/api/auth/2fa/setup"): "auth",
    ("POST", "/api/auth/2fa/confirm"): "auth",
    ("POST", "/api/auth/2fa/check"): "auth",
    ("POST", "/api/auth/2fa/disable"): "auth",
    ("POST", "/api/auth/2fa/recovery-codes"): "auth",
    ("POST", "/api/auth/2fa/verify"): "open",
    ("GET", "/api/admin/2fa/users"): "admin",
    ("POST", "/api/admin/2fa/reset"): "admin",
    ("GET", "/api/fsp-id/config"): "open",
    ("POST", "/api/fsp-id/start"): "open",
    ("GET", "/api/fsp-id/callback"): "open404",  # без настроенного ФСП ID — 404
    ("POST", "/api/fsp-id/exchange"): "open",
    ("POST", "/api/fsp-id/complete"): "open",
    # ---------------------------------------------------------------- режим жюри
    ("GET", "/api/jury/status"): "open",
    ("POST", "/api/jury/login"): "open",
    # сброс/удаление песочницы отзывает токены всех её персон и имеет кулдаун — проверяем работодателями A и B
    ("POST", "/api/jury/reset"): ("jury_demo", {"jury_candidate": SKIP, "jury_expert": SKIP, "jury_fsp": SKIP,
                                                "jury_other_candidate": SKIP}),
    ("GET", "/api/jury/quick"): "jury_demo",  # Я9: демо-персоны своей песочницы для «Проверки за 12 минут»
    ("DELETE", "/api/jury/sandbox"): ("jury_demo", {"jury_candidate": SKIP, "jury_expert": SKIP, "jury_fsp": SKIP,
                                                    "jury_other_candidate": SKIP}),  # feat/jury-test
    # живая демонстрация: зал по QR — гости без регистрации (свой гостевой токен), экран — работодатель жюри
    ("GET", "/api/jury/live/j/{code}"): "open",
    ("GET", "/api/jury/live/j/{code}/qr.svg"): "open",
    ("GET", "/api/jury/live/j/{code}/qr.png"): "open",
    ("GET", "/api/jury/live/j/{code}/manifest.webmanifest"): "open",
    ("POST", "/api/jury/live/j/{code}/start"): "open",
    ("GET", "/api/jury/live/j/{code}/me"): "stub",  # гостевой токен X-Guest-Token, не JWT
    ("POST", "/api/jury/live/j/{code}/answer"): "stub",
    ("POST", "/api/jury/live/j/{code}/push"): "stub",
    ("POST", "/api/jury/live/j/{code}/respond"): "stub",
    ("POST", "/api/jury/live/room"): "jury_screen",
    ("GET", "/api/jury/live/room/feed"): "jury_screen",
    ("POST", "/api/jury/live/room/clear"): "jury_screen",
    # ---------------------------------------------------------------- текущий пользователь
    ("GET", "/api/me"): "auth",
    ("PATCH", "/api/me/candidate-profile"): "candidate",
    ("PATCH", "/api/me/company"): "employer",
    ("GET", "/api/me/card"): "candidate",
    ("GET", "/api/me/consents"): "candidate",
    ("POST", "/api/me/consents/{kind}"): "candidate",
    ("DELETE", "/api/me/consents/{kind}"): "candidate",  # kind=processing → 409 (через оператора), профиль не трогает
    ("GET", "/api/me/data"): "candidate",  # feat/my-data: «Мои данные»
    ("GET", "/api/me/data/export"): "candidate",
    ("GET", "/api/me/data/delete/preview"): "candidate",
    ("POST", "/api/me/data/contacts/revoke"): "candidate",  # отзыв доступа к контактам у всех (в LAST)
    ("POST", "/api/me/data/delete"): "candidate",  # без тела — 422: матрица ничего не удаляет
    ("GET", "/api/me/interest"): "candidate",
    ("GET", "/api/me/fsp"): "candidate",
    ("POST", "/api/me/fsp/link"): "candidate",
    ("POST", "/api/me/fsp/registry-sync"): "candidate",
    # А2: проверка и подтверждение достижений по официальным протоколам ФСП
    ("POST", "/api/me/fsp/protocols/search"): "candidate",
    ("POST", "/api/me/fsp/protocols/confirm"): "candidate",
    ("PUT", "/api/me/jury-mode"): ("candidate", {"candidate": 403}),  # только демо-учётки: живому кандидату 403
    ("GET", "/api/me/onboarding"): "candidate",
    ("PUT", "/api/me/onboarding"): "candidate",
    ("PUT", "/api/me/privacy"): "candidate",
    ("GET", "/api/me/profile.pdf"): "candidate",
    ("GET", "/api/me/resume"): "candidate",
    ("POST", "/api/me/resume"): "candidate",
    ("POST", "/api/me/resume/{resume_id}/apply"): "candidate_own",
    ("GET", "/api/me/passport"): "candidate",  # feat/passport
    ("POST", "/api/me/passport/revoke"): "candidate",
    ("POST", "/api/me/passport/reissue"): "candidate",
    # ---------------------------------------------------------------- тест на грейд
    ("GET", "/api/assessment/status"): "candidate",
    ("POST", "/api/assessment/sessions"): "candidate",
    ("GET", "/api/assessment/sessions/{session_id}"): "candidate_own",
    ("POST", "/api/assessment/sessions/{session_id}/answers"): "candidate_own",
    ("POST", "/api/assessment/sessions/{session_id}/finish"): "candidate_own",
    ("GET", "/api/assessment/feedback"): "candidate",
    ("GET", "/api/assessment/attempts"): "candidate",  # feat/attempts (И26): свои попытки; чужие a/b — 404
    ("GET", "/api/assessment/grade-hint"): "candidate",  # feat/jury-test
    ("GET", "/api/assessment/sessions/{session_id}/result"): "candidate_own",
    ("GET", "/api/assessment/sessions/{session_id}/evidence"): "candidate_own",  # feat/evidence-grade
    ("POST", "/api/assessment/sessions/{session_id}/accept-lower"): "candidate_own",
    # А4: апелляция по заданию теста (только кандидат — владелец своей сессии; токен задания не из мира теста → OK404)
    ("GET", "/api/assessment/sessions/{session_id}/appeals"): "candidate_own",
    ("POST", "/api/assessment/sessions/{session_id}/appeals"): "candidate_own404",
    # камера по согласию (feat/proctor, pc01): только кандидат; сессия — своя (чужая → 404); работодателю API нет,
    # агрегат ФСП — аналитик и администратор (в песочнице жюри — персона «Федерация»)
    ("GET", "/api/proctor/consent"): "candidate",
    ("POST", "/api/proctor/consent"): "candidate",
    ("DELETE", "/api/proctor/consent"): "candidate",
    ("GET", "/api/proctor/me/sessions"): "candidate",
    ("GET", "/api/proctor/sessions/{session_id}"): "candidate_own",
    ("POST", "/api/proctor/sessions/{session_id}/start"): "candidate_own",
    ("POST", "/api/proctor/sessions/{session_id}/events"): "candidate_own",
    ("POST", "/api/proctor/sessions/{session_id}/stop"): "candidate_own",
    ("GET", "/api/proctor/stats"): "fsp",
    # ---------------------------------------------------------------- кандидат: зонды, приглашения, кубки, отклики
    ("GET", "/api/candidate/probes"): "candidate",
    ("GET", "/api/candidate/probes/{probe_id}"): "candidate_own",
    ("POST", "/api/candidate/probes/{probe_id}/answer"): "candidate_own",
    ("POST", "/api/candidate/probes/{probe_id}/decline"): "candidate_own",
    ("GET", "/api/candidate/invitations"): "candidate",
    ("GET", "/api/candidate/invitations/{inv_id}"): "candidate_own",
    ("POST", "/api/candidate/invitations/{inv_id}/accept"): "candidate_own",
    ("POST", "/api/candidate/invitations/{inv_id}/decline"): "candidate_own",
    ("POST", "/api/candidate/invitations/{inv_id}/complaint"): "candidate_own",
    ("GET", "/api/candidate/invitations/{inv_id}/trust"): "candidate_own",
    ("GET", "/api/candidate/invitations-trust"): "candidate",
    ("POST", "/api/candidate/invitations/{inv_id}/counter"): "candidate_own",  # feat/contact
    ("POST", "/api/candidate/invitations/{inv_id}/contacts/revoke"): "candidate_own",
    ("POST", "/api/candidate/invitations/{inv_id}/contacts/restore"): "candidate_own",
    # найм после принятия (feat/hiring, Н8): собеседование {iid} в мире теста не создаётся — own404
    ("GET", "/api/candidate/invitations/{inv_id}/hiring"): "candidate_own",
    ("POST", "/api/candidate/invitations/{inv_id}/interviews/{iid}/choose"): "candidate_own404",
    ("POST", "/api/candidate/invitations/{inv_id}/interviews/{iid}/reschedule"): "candidate_own404",
    ("POST", "/api/candidate/invitations/{inv_id}/offer/accept"): "candidate_own",
    ("POST", "/api/candidate/invitations/{inv_id}/offer/decline"): "candidate_own",
    ("POST", "/api/candidate/invitations/{inv_id}/offer/counter"): "candidate_own",
    ("GET", "/api/employer/invitations/{inv_id}/hiring"): "employer_own",
    ("POST", "/api/employer/invitations/{inv_id}/interviews"): "employer_own",
    ("POST", "/api/employer/invitations/{inv_id}/interviews/{iid}/done"): "employer_own404",
    ("POST", "/api/employer/invitations/{inv_id}/interviews/{iid}/cancel"): "employer_own404",
    ("POST", "/api/employer/invitations/{inv_id}/offer"): "employer_own",
    ("POST", "/api/employer/invitations/{inv_id}/offer/withdraw"): "employer_own",
    ("POST", "/api/employer/invitations/{inv_id}/offer/counter/accept"): "employer_own",
    ("POST", "/api/employer/invitations/{inv_id}/offer/counter/decline"): "employer_own",
    ("POST", "/api/employer/invitations/{inv_id}/outcome"): "employer_own",
    ("GET", "/api/hiring/todo"): "auth",
    ("GET", "/api/candidate/cups"): "candidate",
    ("GET", "/api/candidate/cups/passport"): "candidate",
    ("GET", "/api/candidate/cups/{cup_id}"): "candidate_own",  # кубок чужой песочницы → 404 (_sees)
    ("POST", "/api/candidate/cups/{cup_id}/join"): "candidate_own",
    ("POST", "/api/candidate/cups/{cup_id}/leave"): "candidate_own",
    ("POST", "/api/candidate/cups/{cup_id}/start"): "candidate_own",
    ("POST", "/api/candidate/cups/{cup_id}/submit"): "candidate_own",
    ("GET", "/api/candidate/applications"): "candidate",
    ("POST", "/api/candidate/applications/{app_id}/withdraw"): "candidate_own",
    ("GET", "/api/candidate/assignments"): "candidate",  # feat/tasks
    ("GET", "/api/candidate/assignments/{atid}"): "candidate_own404",  # задание в мире теста не создаётся
    ("POST", "/api/candidate/assignments/{atid}/start"): "candidate_own404",
    ("POST", "/api/candidate/assignments/{atid}/submit"): "candidate_own404",
    ("POST", "/api/candidate/assignments/{atid}/decline"): "candidate_own404",
    ("PUT", "/api/candidate/assignments/prefs"): "candidate",  # К5 расписание ленты
    ("POST", "/api/candidate/assignments/demo/next-week"): ("candidate", {"candidate": 403}),  # К5: только песочница жюри
    # ---------------------------------------------------------------- вакансии (публичный список для вошедших)
    ("GET", "/api/vacancies"): "auth",
    ("GET", "/api/vacancies/{vid}"): "vacancy",
    ("POST", "/api/vacancies/{vid}/apply"): "vacancy_apply",
    ("GET", "/api/companies/{company_id}"): "auth",
    # ---------------------------------------------------------------- работодатель
    ("GET", "/api/employer/categories"): "employer",
    ("GET", "/api/employer/candidates"): "employer",
    ("GET", "/api/employer/candidates/{ref}"): "employer_ref",
    ("GET", "/api/employer/candidates/{ref}/profile.pdf"): "employer_ref",
    ("GET", "/api/employer/candidates/{ref}/attempts"): "employer_ref",  # feat/attempts (И26)
    ("GET", "/api/employer/candidates/{ref}/evidence"): "employer_ref",  # feat/evidence-grade
    ("GET", "/api/employer/candidates/{ref}/passport"): ("employer_ref", {"employer": OK404, "employer_other": OK404,
                                                                             "jury_employer": OK404}),  # feat/passport
    ("POST", "/api/employer/needs/parse"): "employer",
    ("POST", "/api/employer/needs/file"): "employer",  # Ф5: текст потребности из файла вакансии
    ("POST", "/api/employer/needs/voice"): "employer",  # надиктованная потребность → текст (выкл. — 409)
    ("GET", "/api/employer/needs/parse/{job_id}"): "employer_own404",  # И27: задача фонового разбора, чужая — 404
    ("GET", "/api/employer/needs"): "employer",
    ("POST", "/api/employer/needs"): "employer",
    ("GET", "/api/employer/needs/{need_id}"): "employer_own",
    ("PATCH", "/api/employer/needs/{need_id}"): "employer_own",
    ("POST", "/api/employer/needs/{need_id}/selections"): "employer_own",
    ("GET", "/api/employer/needs/{need_id}/selections/{version}"): "employer_own",
    ("GET", "/api/employer/needs/{need_id}/selections/{version}/what-if"): "employer_own",  # И18 «Что если»
    # взаимный подбор, отзывы, ссылка руководителю (Н9, Н2, Н3 — feat/mutual)
    ("GET", "/api/employer/needs/{need_id}/selections/{version}/mutual"): "employer_own",
    ("PUT", "/api/employer/needs/{need_id}/feedback"): "employer_own",
    ("DELETE", "/api/employer/needs/{need_id}/feedback/{ref}"): "employer_own",
    ("POST", "/api/employer/needs/{need_id}/selections/{version}/refine"): "employer_own",
    ("POST", "/api/employer/needs/{need_id}/selections/{version}/similar"): "employer_own",
    ("POST", "/api/employer/needs/{need_id}/shares"): "employer_own",
    ("GET", "/api/employer/needs/{need_id}/shares"): "employer_own",
    ("POST", "/api/employer/needs/{need_id}/shares/{share_id}/revoke"): "employer_own404",  # ссылки в мире теста нет
    ("POST", "/api/employer/mutual/offer-check"): "employer_ref",
    ("GET", "/api/candidate/preferences"): "candidate",
    ("PUT", "/api/candidate/preferences"): "candidate",
    ("GET", "/api/candidate/invitations/{inv_id}/why"): "candidate_own404",
    ("GET", "/api/share/{token}"): "open404",
    ("POST", "/api/share/{token}/reactions"): "open404",
    ("GET", "/api/employer/needs/{need_id}/compare"): "employer_own",
    ("POST", "/api/employer/needs/{need_id}/advisor"): "employer_own",  # Н1 ИИ-советник руководителя
    ("POST", "/api/employer/needs/{need_id}/advisor/avatar-token"): ("employer_own", {"employer": 503, "jury_employer": 503}),
    ("POST", "/api/employer/needs/{need_id}/advisor/speech"): ("employer_own", {"employer": 503, "jury_employer": 503}),
    ("GET", "/api/employer/probes"): "employer",
    ("POST", "/api/employer/probes"): "employer_ref",
    ("POST", "/api/employer/probes/{probe_id}/review"): "employer_own",
    ("GET", "/api/employer/invitations"): "employer",
    ("POST", "/api/employer/invitations"): "employer_ref",
    ("POST", "/api/employer/invitations/{inv_id}/withdraw"): "employer_own",
    ("GET", "/api/employer/invitations/{inv_id}/export.json"): "employer_own",
    ("POST", "/api/employer/invitations/{inv_id}/counter/accept"): "employer_own",  # feat/contact
    ("POST", "/api/employer/invitations/{inv_id}/counter/decline"): "employer_own",
    ("GET", "/api/employer/cups"): "employer",
    ("POST", "/api/employer/cups"): "employer",
    ("GET", "/api/employer/cups/options"): "employer",
    ("GET", "/api/employer/cups/{cup_id}"): "employer_own",
    ("POST", "/api/employer/cups/{cup_id}/cancel"): "employer_own",
    ("POST", "/api/employer/cups/{cup_id}/finish"): "employer_own",
    ("POST", "/api/employer/cups/{cup_id}/entries/{entry_id}/score"): "employer_own",
    ("POST", "/api/employer/cups/{cup_id}/entries/{entry_id}/invite"): "employer_own",  # Н5: призёр в 1 клик
    ("POST", "/api/employer/cups/from-need/{need_id}"): "employer_own",  # Н5: отборочный турнир ФСП под вакансию
    ("GET", "/api/employer/vacancies"): "employer",
    ("POST", "/api/employer/vacancies"): "employer",
    ("PATCH", "/api/employer/vacancies/{vid}"): "employer_own",
    ("POST", "/api/employer/vacancies/{vid}/publish"): "employer_own",
    ("POST", "/api/employer/vacancies/{vid}/close"): "employer_own",
    ("GET", "/api/employer/vacancies/{vid}/applications"): "employer_own",
    # И23: импорт вакансий из «Потока» — своя компания; без токена 422, ATS недоступна — 502
    ("GET", "/api/employer/vacancies/import/potok/preview"): ("employer", _UPSTREAM),
    ("POST", "/api/employer/vacancies/import/potok"): ("employer", _UPSTREAM),
    # Я12 hh.ru: по умолчанию выключено (HH_ENABLED) — работодателю 404 hh_disabled, роли проверяются раньше
    ("GET", "/api/employer/vacancies/import/hh/preview"): ("employer", _HH_OFF),
    ("POST", "/api/employer/vacancies/import/hh"): ("employer", _HH_OFF),
    ("GET", "/api/employer/market/hh"): ("employer", _HH_OFF),
    # Я29 тарифы: по умолчанию выключено (TARIFFS_ENABLED) — 404 tariffs_disabled, роли проверяются раньше
    ("GET", "/api/tariffs"): "open404",
    ("GET", "/api/employer/tariff"): ("employer", _HH_OFF),
    ("POST", "/api/employer/tariff"): ("employer", _HH_OFF),
    ("POST", "/api/employer/tariff/partner-request"): ("employer", _HH_OFF),
    ("GET", "/api/fsp-cabinet/partners"): ("fsp", _FSP_OFF),
    ("GET", "/api/fsp-cabinet/partners/search"): ("fsp", _FSP_OFF),
    ("POST", "/api/fsp-cabinet/partners/{company_id}"): ("fsp", _FSP_OFF),
    ("GET", "/api/fsp-cabinet/benefit"): ("fsp", _FSP_OFF),
    ("GET", "/api/fsp-cabinet/benefit/export.csv"): ("fsp", _FSP_OFF),
    ("POST", "/api/employer/applications/{app_id}/view"): "employer_own",
    ("POST", "/api/employer/applications/{app_id}/status"): "employer_own",
    ("GET", "/api/employer/applications/{app_id}/export.json"): "employer_own",
    ("POST", "/api/employer/company/registry-check"): "employer",
    ("GET", "/api/employer/company/trust"): "employer",
    ("GET", "/api/employer/assignments"): "employer",  # feat/tasks
    ("POST", "/api/employer/assignments"): ("employer_ref", {"employer_other": 404}),  # need_id — потребность E1
    ("POST", "/api/employer/assignments/preview"): "employer",
    ("GET", "/api/employer/assignments/{aid}"): "employer_own404",  # задание в мире теста не создаётся
    ("POST", "/api/employer/assignments/{aid}/send"): "employer_own404",
    ("POST", "/api/employer/assignments/{aid}/close"): "employer_own404",
    ("POST", "/api/employer/assignments/{aid}/attempts/{atid}/review"): "employer_own404",  # К5 рубрика
    # ATS компании: настройки и журнал — только работодатель своей компании (объекты по id — журнал передач)
    ("GET", "/api/employer/ats/settings"): "employer",
    ("PUT", "/api/employer/ats/settings"): "employer",
    ("GET", "/api/employer/ats/webhook-secret"): "employer",
    ("POST", "/api/employer/ats/huntflow/check"): ("employer", _UPSTREAM),
    ("POST", "/api/employer/ats/stub/connect"): "employer",
    ("GET", "/api/employer/ats/stub/records"): "employer",
    ("POST", "/api/employer/ats/demo/connect-all"): "employer",
    ("GET", "/api/employer/ats/providers"): "employer",
    ("PUT", "/api/employer/ats/providers/{code}"): "employer",
    ("POST", "/api/employer/ats/providers/{code}/check"): ("employer", _UPSTREAM),
    ("POST", "/api/employer/ats/providers/{code}/demo"): "employer",
    ("GET", "/api/employer/ats/providers/{code}/vacancies"): ("employer", _UPSTREAM),
    ("GET", "/api/employer/ats/providers/{code}/vacancies/{vacancy_id}/stages"): ("employer", _UPSTREAM),
    ("GET", "/api/employer/ats/deliveries"): "employer",
    ("POST", "/api/employer/ats/deliveries/{delivery_id}/retry"): ("employer_own",
                                                                     {"employer": OK404, "jury_employer": OK404}),
    ("POST", "/api/employer/ats/push"): "employer_own",  # приглашение в теле — только своей компании
    ("GET", "/api/employer/ats/stages"): "employer",  # feat/infra2
    ("POST", "/api/employer/ats/stages/sync"): "employer",
    ("GET", "/api/employer/ats/stub/potok/pipeline"): "employer",
    ("POST", "/api/employer/ats/stub/potok/move"): "employer",
    # подписанная ссылка на PDF для ATS: токен — сам пропуск, без входа
    ("GET", "/api/ats/profile/{token}.pdf"): "open404",
    # ---------------------------------------------------------------- переписка (feat/contact)
    ("GET", "/api/messages/threads"): "auth",
    ("GET", "/api/messages/unread"): "auth",
    ("GET", "/api/messages/{kind}/{tid}"): "thread_party",
    ("POST", "/api/messages/{kind}/{tid}"): "thread_party",
    # А2: трёхсторонняя связь работодатель ↔ кандидат ↔ представитель ФСП (tw01)
    ("GET", "/api/trio/meta"): "open",
    ("GET", "/api/trio/unread"): ("auth", {"expert": 403, "jury_expert": 403}),
    ("GET", "/api/trio/threads"): ("auth", {"expert": 403, "jury_expert": 403}),
    ("GET", "/api/trio/eligible"): ("auth", {"admin": 403, "fsp_analyst": 403, "expert": 403, "jury_expert": 403, "jury_fsp": 403}),
    ("POST", "/api/trio/threads"): ("auth", {"admin": 403, "fsp_analyst": 403, "expert": 403, "jury_expert": 403, "jury_fsp": 403}),
    ("GET", "/api/trio/threads/{tid}"): ("auth404", {"employer_other": 404, "expert": 403, "jury_expert": 403, "jury_other_employer": 404, "jury_other_candidate": 404}),
    ("POST", "/api/trio/threads/{tid}/messages"): ("auth404", {"employer_other": 404, "expert": 403, "jury_expert": 403, "jury_other_employer": 404, "jury_other_candidate": 404}),
    ("POST", "/api/trio/threads/{tid}/consent"): "candidate_own404",
    ("POST", "/api/trio/threads/{tid}/close"): ("auth404", {"employer_other": 404, "expert": 403, "jury_expert": 403, "jury_other_employer": 404, "jury_other_candidate": 404}),
    # ---------------------------------------------------------------- эксперт проверки ответов, панель разметки
    ("GET", "/api/expert/queue"): "expert",
    ("POST", "/api/expert/review"): "expert",
    ("GET", "/api/expert/agreement"): "expert",
    ("POST", "/api/expert-panel/enter"): "open",  # вход по персональной ссылке
    ("GET", "/api/expert-panel/me"): "expert",
    # эксперт вне панели разметки — 404 not_in_panel (вход в панель по персональной ссылке)
    ("POST", "/api/expert-panel/ack"): ("expert", {"expert": OK404, "admin": OK404, "jury_expert": OK404}),
    ("GET", "/api/expert-panel/items/{kind}"): ("expert", {"expert": OK404, "admin": OK404, "jury_expert": OK404}),
    ("POST", "/api/expert-panel/labels"): "expert",
    ("POST", "/api/expert-panel/invites"): "admin",
    ("GET", "/api/expert-panel/status"): "admin",
    # ---------------------------------------------------------------- Кабинет ФСП и администратор
    ("GET", "/api/fsp-cabinet/overview"): "fsp",
    ("GET", "/api/fsp-cabinet/funnel"): "fsp",
    ("GET", "/api/fsp-cabinet/demand"): "fsp",
    ("GET", "/api/fsp-cabinet/salaries"): "fsp",
    ("GET", "/api/fsp-cabinet/fsp-effect"): "fsp",
    ("GET", "/api/fsp-cabinet/cups"): "fsp",
    ("GET", "/api/fsp-cabinet/report"): "fsp",
    ("GET", "/api/fsp-cabinet/regions"): "fsp",  # А2: карта талантов по регионам РФ
    ("GET", "/api/fsp-cabinet/export/{section}.csv"): "fsp",
    ("GET", "/api/admin/sus"): "admin",
    ("POST", "/api/admin/passports/{pid}/revoke"): ("admin", {"admin": OK404}),  # feat/passport; паспорт не создаётся
    # ---------------------------------------------------------------- паспорт грейда (feat/passport), публичный
    ("GET", "/api/passport/keys"): "open",
    ("POST", "/api/passport/verify"): "open",
    ("GET", "/api/passport/{pid}"): "open404",
    ("GET", "/api/passport/{pid}/qr.svg"): "open404",
    ("GET", "/.well-known/jwks.json"): "open",
    ("GET", "/api/.well-known/jwks.json"): "open",
    ("GET", "/api/passport/{pid}/offline.json"): "open404",
    ("GET", "/api/passport/demo"): "open404",
    ("POST", "/api/passport/demo/revoke"): ("jury_demo", {r: OK404 for r in JURY_ROLES}),
    ("POST", "/api/passport/demo/reissue"): ("jury_demo", {r: OK404 for r in JURY_ROLES}),
    # ---------------------------------------------------------------- валидация, SUS, push
    ("GET", "/api/validation/report"): "open",
    ("GET", "/api/validation/matching-bench"): "open",
    ("GET", "/api/validation/fsp-rating"): "open",
    ("POST", "/api/validation/attacks/{attack_id}"): "auth404",  # attack_id=nope: вход проверяется, атаки нет
    ("GET", "/api/validation/junior-stability"): "open",  # feat/status
    ("GET", "/api/validation/grader-check"): "open",  # feat/integrity
    ("GET", "/api/validation/evidence"): "open",  # feat/evidence-grade
    ("GET", "/api/validation/llm-models"): "open",  # feat/llm-local
    ("GET", "/api/validation/ru-llm"): "open",  # замер «только российская модель»
    ("GET", "/api/validation/strongest"): "open",  # сильнейшие модели по функциям
    ("GET", "/api/validation/path-retest"): "open",  # feat/validation (ВЛ)
    ("GET", "/api/validation/grade-accuracy"): "open",  # feat/grade-accuracy: сводка перебора правил теста (как path-retest)
    ("GET", "/api/validation/two-stage"): "open",  # feat/two-stage: «одна сессия / две сессии» (симуляция, как grade-accuracy)
    ("GET", "/api/validation/partial-credit"): "open",  # частичный балл 0–4 (симуляция)
    ("GET", "/api/validation/headline"): "open",
    ("GET", "/api/validation/criteria"): "open",  # feat/criteria-page (К1)
    ("GET", "/api/validation/hh-parse"): "open",  # Я12: замер разбора на корпусе hh.ru
    ("GET", "/api/validation/hh-match"): "open",  # Я12б: подбор на вакансиях hh.ru и спрос по направлениям (агрегаты)
    ("GET", "/api/validation/attempts-repeat"): "open",  # feat/attempts (И26)
    ("GET", "/api/validation/test-length"): "open",  # Ф6 (Н8): длина теста на экране старта
    ("GET", "/api/validation/provenance"): "open",  # Я8: происхождение чисел /validation
    ("POST", "/api/validation/self-check"): "auth",  # feat/jury-test
    ("GET", "/api/validation/closed-set/template/{format}"): "open",  # feat/realdata
    ("POST", "/api/validation/closed-set/evaluate"): "sandbox_employer",
    ("POST", "/api/validation/closed-set/export"): "sandbox_employer",
    # А4: методика грейда SPRT, утечка K вариантов, вызов «Обмани тест», кросс-вендорный протокол экспертов
    ("GET", "/api/validation/sprt-verdict"): "open",
    ("GET", "/api/validation/leak-k-variants"): "open",
    ("GET", "/api/validation/cheat-challenge"): "open",
    ("POST", "/api/validation/cheat-challenge/attempt"): "open",
    ("GET", "/api/validation/expert-surrogate"): "open",
    # подписка на потребность, уведомления, напоминания (И25, Н6 — feat/subs)
    ("GET", "/api/employer/subscriptions"): "employer",
    ("GET", "/api/employer/needs/{need_id}/subscription"): "employer_own",
    ("PUT", "/api/employer/needs/{need_id}/subscription"): "employer_own",
    ("POST", "/api/employer/needs/{need_id}/subscription/seen"): "employer_own",
    ("POST", "/api/employer/needs/{need_id}/subscription/check"): "employer_own",
    ("POST", "/api/employer/needs/{need_id}/subscription/new-version"): "employer_own",
    ("GET", "/api/notifications"): "auth",
    ("POST", "/api/notifications/read"): "auth",
    ("GET", "/api/notifications/prefs"): "auth",
    ("PUT", "/api/notifications/prefs"): "auth",
    ("POST", "/api/jury/subs/simulate"): "sandbox_employer",
    ("POST", "/api/jury/subs/fast-forward"): "sandbox_employer",
    ("GET", "/api/sus/questions"): "open",
    ("POST", "/api/sus"): "open",
    ("GET", "/api/sus/mine"): "open",
    ("GET", "/api/sus/summary"): "open",
    # обезличенная статистика прохождения (app.modules.study): любой вошедший; сводка открыта; служебная — админ
    ("GET", "/api/study/me"): "auth",
    ("POST", "/api/study/enroll"): "auth",
    ("POST", "/api/study/decline"): "auth",
    ("POST", "/api/study/events"): "auth",
    ("GET", "/api/study/survey"): "auth404",
    ("POST", "/api/study/survey"): "auth404",
    ("POST", "/api/study/survey/shown"): "auth",
    ("GET", "/api/study/summary"): "open",
    ("GET", "/api/study/admin/report"): "admin",
    ("GET", "/api/push/config"): "open",
    ("POST", "/api/push/subscribe"): "auth",
    ("POST", "/api/push/unsubscribe"): "auth",
    ("GET", "/api/push/status"): "auth",
    ("POST", "/api/push/test"): "auth",
    # ---------------------------------------------------------------- заглушки сторонних ATS (свой токен, не JWT)
    ("GET", "/api/ats-stub/huntflow/v2/me"): "stub",
    ("GET", "/api/ats-stub/huntflow/v2/accounts"): "stub",
    ("GET", "/api/ats-stub/huntflow/v2/accounts/{account_id}/vacancies"): "stub",
    ("GET", "/api/ats-stub/huntflow/v2/accounts/{account_id}/vacancies/statuses"): "stub",
    ("POST", "/api/ats-stub/huntflow/v2/accounts/{account_id}/applicants"): "stub",
    ("POST", "/api/ats-stub/huntflow/v2/accounts/{account_id}/applicants/{applicant_id}/vacancy"): "stub",
    ("POST", "/api/ats-stub/webhook/{stub_key}"): "stub",
    ("GET", "/api/ats-stub/talantix/auth_check"): "stub",
    ("POST", "/api/ats-stub/talantix/graphql"): "stub",
    ("POST", "/api/ats-stub/talantix/oauth/token"): "stub",
    ("GET", "/api/ats-stub/potok/api/v3/jobs.json"): "stub",
    ("GET", "/api/ats-stub/potok/api/v3/jobs/{job_id}.json"): "stub",
    ("GET", "/api/ats-stub/potok/api/v3/jobs/{job_id}/ajs_joins.json"): "stub",  # feat/infra2
    ("POST", "/api/ats-stub/potok/api/v3/jobs/{job_id}/{applicant_id}/decline.json"): "stub",
    ("POST", "/api/ats-stub/potok/api/v3/applicants.json"): "stub",
    ("GET", "/api/ats-stub/potok/api/v3/applicants/{applicant_id}.json"): "stub",
    ("POST", "/api/ats-stub/potok/api/v3/ajs_joins.json"): "stub",
    ("POST", "/api/ats-stub/potok/api/v3/ajs_joins/{join_id}/change_stage.json"): "stub",
    ("POST", "/api/ats-stub/potok/api/v3/events.json"): "stub",
    # ---------------------------------------------------------------- Я15: устная защита и ИИ-интервью (флаг выкл. — 409 после
    # проверки владения); {session_id} у /sessions — сессия интервью, в мире не создаётся (владельцу 404); с телом — 422 до владения
    ("GET", "/api/interview/defense/{session_id}"): "candidate_own",
    ("POST", "/api/interview/defense/{session_id}"): "candidate",
    ("GET", "/api/interview/sessions/{session_id}"): "candidate_own404",
    ("DELETE", "/api/interview/sessions/{session_id}"): "candidate_own404",
    ("POST", "/api/interview/sessions/{session_id}/begin"): "candidate",
    ("POST", "/api/interview/sessions/{session_id}/answer"): "candidate",
    ("POST", "/api/interview/sessions/{session_id}/channel"): "candidate",
    ("POST", "/api/interview/sessions/{session_id}/finish"): "candidate_own404",
    ("POST", "/api/interview/sessions/{session_id}/transcribe"): "candidate_own404",
    ("GET", "/api/interview/sessions/{session_id}/speech"): "candidate_own404",
    ("POST", "/api/interview/sessions/{session_id}/avatar-token"): "candidate_own404",
    ("GET", "/api/interview/candidates/{ref}"): "employer_ref",
    ("GET", "/api/employer/invitations/{inv_id}/ai-interview"): "employer_own",
    ("POST", "/api/employer/invitations/{inv_id}/ai-interview"): "employer",
    ("GET", "/api/candidate/invitations/{inv_id}/ai-interview"): "candidate_own",
    ("POST", "/api/candidate/invitations/{inv_id}/ai-interview"): "candidate",
    ("POST", "/api/interview/quick-defense"): "candidate",
    ("POST", "/api/interview/concierge/avatar-token"): "open",
    ("POST", "/api/interview/concierge/speech"): "open",
    ("POST", "/api/interview/concierge/transcribe"): "open",
    ("POST", "/api/interview/concierge/chat"): "open",
    ("POST", "/api/interview/concierge/turn"): "open",
    ("GET", "/api/interview/concierge/script"): "open",
    ("POST", "/api/interview/concierge/event"): "open",
    # WebSocket живого распознавания: обычный GET на него — 404 (не HTTP-маршрут), сам канал — с проверкой Origin и лимитами
    ("GET", "/api/interview/live/stt"): "stub",
    # А5: режим «Принесите свой набор» для жюри (подбор, метрики P@5/P@10/nDCG@10/MRR, объяснение, выгрузка CSV)
    ("GET", "/api/employer/benchmark/sample"): "open",
    ("POST", "/api/employer/benchmark/upload"): "sandbox_employer",
    # ---------------------------------------------------------------- А1: восстановление пароля, поддержка, заявки на тариф, мини-админка
    ("POST", "/api/auth/forgot"): "open",
    ("POST", "/api/auth/reset"): "open",
    ("GET", "/api/support"): "open",
    ("POST", "/api/support"): "open",
    ("GET", "/api/support/my"): "auth",
    ("POST", "/api/tariffs/request"): "open",
    ("GET", "/api/tariffs/requests/my"): "employer",
    ("GET", "/api/admin/overview"): "admin",
    ("GET", "/api/admin/funnel"): "admin",
    ("GET", "/api/admin/users"): "admin",
    ("POST", "/api/admin/users/status"): "admin",
    ("GET", "/api/admin/companies"): "admin",
    ("POST", "/api/admin/companies/tariff"): "admin",
    ("GET", "/api/admin/requests"): "admin",
    ("POST", "/api/admin/requests/tariff-resolve"): "admin",
    ("POST", "/api/admin/requests/support-resolve"): "admin",
    ("GET", "/api/admin/flags"): "admin",
    ("POST", "/api/admin/flags"): "admin",
    # А7: уведомления в Telegram (привязка по одноразовому коду, проверка и вебхук бота)
    ("GET", "/api/telegram/status"): "auth",
    ("POST", "/api/telegram/link"): "auth",
    ("DELETE", "/api/telegram/link"): "auth",
    ("POST", "/api/telegram/test"): "auth",
    ("POST", "/api/telegram/webhook"): "open",
    # А9: Боевой ИИ-Полигон (/api/warroom/*)
    ("GET", "/api/warroom/scenarios"): "open",
    ("GET", "/api/warroom/scenarios/{scenario_id}"): "open",
    ("POST", "/api/warroom/simulate"): "open",
    ("POST", "/api/warroom/evaluate"): "open",
    ("GET", "/api/warroom/attempts/my"): "candidate",
    ("GET", "/api/warroom/candidates/{ref}"): "employer_ref",
    ("POST", "/api/warroom/anticheat/inspect"): "open",
}

# Значения параметров пути, не зависящие от стороны (остальные — PARAMS в test_access_matrix.py: ресурсы сторон)
PARAM_OVERRIDES: dict[tuple[str, str], dict[str, object]] = {
    ("POST", "/api/validation/attacks/{attack_id}"): {"attack_id": "nope"},
    ("DELETE", "/api/me/consents/{kind}"): {"kind": "processing"},  # 409 — профиль из подборок не пропадает
    ("POST", "/api/me/consents/{kind}"): {"kind": "publication"},
    ("GET", "/api/legal/consents/{kind}"): {"kind": "processing"},
    ("GET", "/api/expert-panel/items/{kind}"): {"kind": "A"},
    ("GET", "/api/messages/{kind}/{tid}"): {"kind": "invitation"},
    ("POST", "/api/messages/{kind}/{tid}"): {"kind": "invitation"},
    ("GET", "/api/employer/needs/parse/{job_id}"): {"job_id": "00000000-0000-4000-8000-000000000027"},  # И27
    # А9: Боевой ИИ-Полигон
    ("GET", "/api/warroom/scenarios/{scenario_id}"): {"scenario_id": "payment"},
}

# Маршруты, меняющие состояние так, что дальнейшие проверки могут сломаться (сброс песочницы отзывает токены,
# завершение теста/кубка меняет статусы): выполняются последними, в этом порядке.
LAST: tuple[tuple[str, str], ...] = (
    ("POST", "/api/me/data/contacts/revoke"),
    ("POST", "/api/candidate/invitations/{inv_id}/decline"),
    ("POST", "/api/employer/invitations/{inv_id}/withdraw"),
    ("POST", "/api/candidate/probes/{probe_id}/decline"),
    ("POST", "/api/candidate/cups/{cup_id}/leave"),
    ("POST", "/api/candidate/applications/{app_id}/withdraw"),
    ("POST", "/api/employer/vacancies/{vid}/close"),
    ("POST", "/api/employer/cups/{cup_id}/cancel"),
    ("POST", "/api/employer/cups/{cup_id}/finish"),
    ("POST", "/api/assessment/sessions/{session_id}/finish"),
    ("POST", "/api/assessment/sessions/{session_id}/accept-lower"),
    ("DELETE", "/api/proctor/consent"),  # отзыв согласия останавливает камеру в открытых сессиях
    ("POST", "/api/jury/live/room/clear"),
    ("POST", "/api/jury/reset"),
    ("DELETE", "/api/jury/sandbox"),
)
