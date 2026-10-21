"""mobile.security.secret_storage_mcq — mcq_concept: где хранить секрет на устройстве.

Секрет (refresh-токен, ключ шифрования локальной базы, токен устройства для подписи платежей) хранится в
системном защищённом хранилище: iOS Keychain (класс доступности …ThisDeviceOnly), Android — ключ в Android
Keystore, секрет зашифрован им. Обычные настройки (UserDefaults, SharedPreferences, AsyncStorage), файлы и
база без шифрования, константы в сборке — нет (OWASP MASVS-STORAGE-1, MASTG). Состав дистракторов фиксирован.
Ключ — справочная таблица (исполнение невозможно).
"""
from __future__ import annotations

from assessment_bank.gen_utils import build_variant, make_rng
from assessment_bank.schema import AnswerKey

from ._mob_utils import balanced_options

FAMILY_ID = "mobile.security.secret_storage_mcq"

SECRETS = [("refresh-токен", "чтобы пользователь не вводил пароль при каждом запуске"),
           ("ключ шифрования локальной базы", "которым шифруется кэш выписок"),
           ("токен привязки устройства", "которым подписываются подтверждения платежей"),
           ("токен доступа к API партнёра, выданный пользователю", "для работы офлайн-синхронизации"),
           ("секрет для одноразовых кодов (TOTP)", "встроенного генератора кодов входа")]
CTX = ["банковское приложение", "медицинская карта", "мессенджер", "приложение брокера", "корпоративная почта"]

PLATFORM = {
    "ios": ("iOS", {"good": "Keychain с классом доступности …ThisDeviceOnly",
                    "prefs": "UserDefaults с отдельным ключом для секрета",
                    "file": "Файл в каталоге Application Support приложения",
                    "build": "Константа в Info.plist, заданная при сборке"}),
    "android": ("Android", {"good": "Зашифрованным ключом из Android Keystore",
                            "prefs": "SharedPreferences в режиме MODE_PRIVATE",
                            "file": "Файл во внутреннем каталоге filesDir",
                            "build": "Поле BuildConfig, заданное при сборке"}),
    "rn": ("React Native (iOS и Android)", {"good": "Keychain и Keystore через модуль безопасного хранения",
                                            "prefs": "AsyncStorage под отдельным ключом",
                                            "file": "Файл в каталоге документов приложения",
                                            "build": "Переменная .env, встроенная в сборку"}),
}


def generate(seed: int):
    rng = make_rng(FAMILY_ID, seed)
    secret, why = rng.choice(SECRETS)
    plat = rng.choice(sorted(PLATFORM))
    name, opts_t = PLATFORM[plat]
    ctx = rng.choice(CTX)
    dist = ["prefs", "file", "build"]
    opts, key = balanced_options(FAMILY_ID, seed, rng, (opts_t["good"], None), [(opts_t[d], None) for d in dist])
    stem = (f"Мобильное приложение ({ctx}, {name}) должно хранить на устройстве {secret}, {why}. Секрет нельзя "
            f"извлечь из резервной копии устройства или с устройства с root/jailbreak простым копированием файлов "
            f"приложения. Где его хранить?")
    ak = AnswerKey(kind="option", value=key,
                   explanation=("Верно: системное защищённое хранилище — Keychain (iOS) и ключ в Android Keystore: "
                                "ключ не покидает защищённое хранилище, класс …ThisDeviceOnly не переносится в "
                                "резервные копии. Обычные настройки и файлы приложения хранятся открыто в его "
                                "песочнице и копируются с устройства; константа сборки одинакова у всех и "
                                "извлекается из пакета (OWASP MASVS-STORAGE-1)."))
    return build_variant(FAMILY_ID, seed, stem=stem, options=opts, answer_key=ak, context=ctx,
                         verification="reference_table", language="text",
                         params={"platform": plat, "distractors": dist,
                                 "reference": "OWASP MASVS-STORAGE-1, MASTG; Apple Keychain Services; Android Keystore"})
