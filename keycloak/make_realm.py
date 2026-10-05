"""Генератор keycloak/realm-fsp.json — демо-realm «ФСП ID» (python3 keycloak/make_realm.py).

Секреты в файл не попадают: ${FSP_OIDC_CLIENT_SECRET}, ${FSP_DEMO_PASSWORD}, ${PLATFORM_BASE_URL} подставляет
Keycloak из окружения при импорте (--import-realm). Пользователи синтетические, совпадения с реальными людьми случайны.
"""
import json
from pathlib import Path


def ach(discipline, event, level, date, place, result, team=None, role=None):
    a = {"discipline": discipline, "event": event, "level": level, "date": date, "place": place, "result": result}
    if team:
        a["team"] = team
    if role:
        a["role"] = role
    return json.dumps(a, ensure_ascii=False)


def attr_mapper(name, multivalued=False, json_type="String"):
    return {"name": name, "protocol": "openid-connect", "protocolMapper": "oidc-usermodel-attribute-mapper",
            "consentRequired": False,
            "config": {"user.attribute": name, "claim.name": name, "jsonType.label": json_type,
                       "id.token.claim": "true", "access.token.claim": "false", "userinfo.token.claim": "true",
                       "introspection.token.claim": "true", "multivalued": str(multivalued).lower(),
                       "aggregate.attrs": "false"}}


PROFILE = {
    "attributes": [
        {"name": "username", "multivalued": False,
         "validations": {"length": {"min": 3, "max": 255}, "username-prohibited-characters": {},
                         "up-username-not-idn-homograph": {}},
         "permissions": {"view": ["admin", "user"], "edit": ["admin", "user"]}},
        {"name": "email", "multivalued": False,
         "validations": {"email": {}, "length": {"max": 255}}, "required": {"roles": ["user"]},
         "permissions": {"view": ["admin", "user"], "edit": ["admin", "user"]}},
        {"name": "firstName", "multivalued": False,
         "validations": {"length": {"max": 255}, "person-name-prohibited-characters": {}},
         "permissions": {"view": ["admin", "user"], "edit": ["admin", "user"]}},
        {"name": "lastName", "multivalued": False,
         "validations": {"length": {"max": 255}, "person-name-prohibited-characters": {}},
         "permissions": {"view": ["admin", "user"], "edit": ["admin", "user"]}},
    ],
    "groups": [{"name": "user-metadata", "displayHeader": "User metadata",
                "displayDescription": "Attributes, which refer to user metadata"}],
    # Атрибуты паспорта ФСП (fsp_*) ведёт реестр — пользователь их не редактирует, видны только администратору
    "unmanagedAttributePolicy": "ADMIN_EDIT",
}

USERS = [
    {"username": "fsp-champion", "email": "champion@demo.fsp-id.example", "firstName": "Алексей",
     "lastName": "Демин", "attributes": {
         "fsp_id": ["FSP-770012"], "fsp_rank": ["КМС"], "fsp_disciplines": ["product", "algorithmic"],
         "fsp_achievements": [
             ach("product", "Чемпионат России по продуктовому программированию", "national", "2025-11-22", 1,
                 "победитель", "Команда «Синтез» (демо)", "тимлид, backend"),
             ach("algorithmic", "Кубок России по спортивному программированию", "national", "2025-04-12", 3,
                 "призёр", "Команда «Синтез» (демо)"),
             ach("product", "Всероссийский хакатон ФСП", "interregional", "2024-10-05", 2, "призёр",
                 "Команда «Синтез» (демо)", "backend")]}},
    {"username": "fsp-prizer", "email": "prizer@demo.fsp-id.example", "firstName": "Мария",
     "lastName": "Пробная", "attributes": {
         "fsp_id": ["FSP-540377"], "fsp_rank": ["II разряд"], "fsp_disciplines": ["security"],
         "fsp_achievements": [
             ach("security", "Первенство Сибирского ФО по программированию систем ИБ (CTF)", "regional",
                 "2026-03-14", 2, "призёр", "Команда «Шифр» (демо)", "reverse, web")]}},
    {"username": "fsp-newcomer", "email": "newcomer@demo.fsp-id.example", "firstName": "Илья",
     "lastName": "Новиков", "attributes": {}},
]


def realm() -> dict:
    return {
        "realm": "fsp", "enabled": True, "displayName": "ФСП ID (демо)",
        "displayNameHtml": "<b>ФСП ID</b> · демо", "sslRequired": "external",
        "registrationAllowed": False, "resetPasswordAllowed": False, "rememberMe": False,
        "loginWithEmailAllowed": True, "duplicateEmailsAllowed": False, "editUsernameAllowed": False,
        "bruteForceProtected": True, "permanentLockout": False, "failureFactor": 30,
        "internationalizationEnabled": True, "supportedLocales": ["ru", "en"], "defaultLocale": "ru",
        "accessTokenLifespan": 300, "ssoSessionIdleTimeout": 1800, "ssoSessionMaxLifespan": 36000,
        "clients": [{
            "clientId": "spectrek-platform", "name": "Встречный — платформа спецтрека ФСП",
            "description": "Демо-клиент: Authorization Code + PKCE (S256), конфиденциальный",
            "enabled": True, "protocol": "openid-connect", "publicClient": False,
            "clientAuthenticatorType": "client-secret", "secret": "${FSP_OIDC_CLIENT_SECRET}",
            "standardFlowEnabled": True, "implicitFlowEnabled": False, "directAccessGrantsEnabled": False,
            "serviceAccountsEnabled": False, "consentRequired": False, "frontchannelLogout": True,
            "rootUrl": "${PLATFORM_BASE_URL}", "baseUrl": "/",
            "redirectUris": ["${PLATFORM_BASE_URL}/api/fsp-id/callback"],
            "webOrigins": ["${PLATFORM_BASE_URL}"],
            "attributes": {"pkce.code.challenge.method": "S256",
                           "post.logout.redirect.uris": "${PLATFORM_BASE_URL}/*",
                           "use.refresh.tokens": "false", "id.token.signed.response.alg": "RS256"},
            "protocolMappers": [attr_mapper("fsp_id"), attr_mapper("fsp_rank"),
                                attr_mapper("fsp_disciplines", multivalued=True),
                                attr_mapper("fsp_achievements", multivalued=True, json_type="JSON")],
        }],
        "users": [{**u, "enabled": True, "emailVerified": True,
                   "credentials": [{"type": "password", "value": "${FSP_DEMO_PASSWORD}", "temporary": False}]}
                  for u in USERS],
        "components": {"org.keycloak.userprofile.UserProfileProvider": [{
            "providerId": "declarative-user-profile", "subComponents": {},
            "config": {"kc.user.profile.config": [json.dumps(PROFILE, ensure_ascii=False)]}}]},
    }


if __name__ == "__main__":
    out = Path(__file__).with_name("realm-fsp.json")
    out.write_text(json.dumps(realm(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(out)
