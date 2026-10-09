"""Словари для вырезания ПДн (resume/pii.py): частые имена кириллицей и латиницей, слова, которые именами не считаются.

Используются только для узких правил, где имя стоит рядом с явным признаком: латиница — пара «имя из словаря +
слово с заглавной» («Ivan Petrov», «Petrov Ivan»), кириллица — одиночное имя рядом с контактом («Ольга, [телефон]»,
«пишите Ольге в tg»). Широкого NER на одно слово нет: «Гибрид», «Андроид» в словаре имён отсутствуют.

Технологии и продукты (словарь стека catalog/dictionary.py, справочник STACK, UNSUPPORTED_TECH и EXTRA_TECH ниже) именем
не считаются никогда: «Spring Boot», «React Native», «Apache Kafka», «Power BI» не режутся.
"""
from __future__ import annotations

from functools import lru_cache
from itertools import product
import re

# ---------------------------------------------------------------- имена кириллицей (именительный падеж)
RU_MALE = """
Александр Алексей Альберт Анатолий Андрей Антон Аркадий Арсений Артём Артем Артур Богдан Борис Вадим Валентин Валерий
Василий Виктор Виталий Владимир Владислав Всеволод Вячеслав Геннадий Георгий Герман Глеб Григорий Давид Даниил Данила
Демид Денис Дмитрий Евгений Егор Елисей Захар Иван Игорь Илья Камиль Кирилл Константин Лев Леонид Максим Марат Марк
Матвей Мирон Михаил Назар Никита Николай Олег Павел Пётр Петр Платон Ринат Роман Ростислав Руслан Рустам Савелий Святослав
Семён Семен Сергей Станислав Степан Тимофей Тимур Тихон Фёдор Федор Филипп Эдуард Эльдар Эмиль Юрий Ярослав Айдар Азат
Ильдар Ильнур Нурлан Расул Ислам Арман Ерлан Дамир Рамиль Рафаэль Валентин Аким Анатолий Ефим Яков Вениамин Алан
""".split()
RU_FEMALE = """
Александра Алина Алиса Алла Алёна Алена Альбина Амина Анастасия Ангелина Анна Антонина Арина Валентина Валерия Варвара
Василиса Вера Вероника Виктория Галина Гульнара Дарья Диана Диляра Ева Евгения Екатерина Елена Елизавета Есения Жанна
Зарина Злата Зоя Инна Ирина Камила Карина Кира Кристина Ксения Лариса Лейла Лидия Лилия Любовь Людмила Майя Маргарита
Марина Мария Милана Мирослава Надежда Наталья Наталия Нелли Нина Оксана Олеся Ольга Полина Раиса Регина Светлана
Снежана Софья София Стефания Таисия Тамара Татьяна Ульяна Эвелина Элина Эльвира Юлия Яна Айгуль Асель Динара Лиана
""".split()
# Уменьшительные — так подписываются рекрутёры («Пишите Маше в tg»). «Макс» нет: это мессенджер MAX.
RU_SHORT = """
Саша Лёша Леша Дима Женя Ваня Миша Коля Паша Петя Рома Серёжа Сережа Костя Вова Володя Боря Гриша Федя Юра Толя Стас Влад
Тёма Тема Гоша Маша Катя Лена Таня Настя Аня Юля Наташа Света Оля Ира Ксюша Даша Вика Лиза Поля Соня Галя Люда Надя Валя
Алёша Алеша Кирюша Никитос Танюша Анечка Леночка Катюша Машенька Оленька
""".split()
RU_FIRST = tuple(dict.fromkeys(RU_MALE + RU_FEMALE + RU_SHORT))

_IRREGULAR_STEM = {"Павел": "Павл", "Пётр": "Петр", "Петр": "Петр", "Лев": "Льв"}
_HUSHING = set("гкхжчшщц")


def ru_forms(name: str) -> set[str]:
    """Падежные формы имени: «Ольга» → Ольги, Ольге, Ольгу, Ольгой (без морфологического анализатора)."""
    out = {name}
    if name in _IRREGULAR_STEM:
        st = _IRREGULAR_STEM[name]
        return out | {st + e for e in ("а", "у", "ом", "е")}
    if name == "Любовь":
        return out | {"Любови", "Любовью"}
    low = name[-1]
    if name.endswith("ия"):
        st = name[:-2]
        out |= {st + e for e in ("ии", "ию", "ией")}
    elif name.endswith("ья"):
        st = name[:-1]
        out |= {st + e for e in ("и", "е", "ю", "ей", "ёй")}
    elif low == "а":
        st = name[:-1]
        gen = "и" if st[-1] in _HUSHING else "ы"
        ins = "ей" if st[-1] in "жчшщц" else "ой"
        out |= {st + gen, st + "е", st + "у", st + ins}
    elif low == "я":
        st = name[:-1]
        out |= {st + e for e in ("и", "е", "ю", "ей", "ёй")}
    elif low in "йь":
        st = name[:-1]
        out |= {st + e for e in ("я", "ю", "ем", "е", "и")}
    else:
        ins = "ем" if low in "жчшщц" else "ом"
        out |= {name + e for e in ("а", "у", ins, "е")}
    return out


@lru_cache(maxsize=1)
def ru_name_forms() -> frozenset[str]:
    return frozenset(f for n in RU_FIRST for f in ru_forms(n))


# ---------------------------------------------------------------- имена латиницей
_TR = {"а": ["a"], "б": ["b"], "в": ["v"], "г": ["g"], "д": ["d"], "е": ["e"], "ё": ["e", "yo"], "ж": ["zh"],
       "з": ["z"], "и": ["i"], "й": ["y", "i", "j"], "к": ["k"], "л": ["l"], "м": ["m"], "н": ["n"], "о": ["o"],
       "п": ["p"], "р": ["r"], "с": ["s"], "т": ["t"], "у": ["u"], "ф": ["f"], "х": ["kh", "h"], "ц": ["ts", "c"],
       "ч": ["ch"], "ш": ["sh"], "щ": ["shch", "sch"], "ъ": [""], "ы": ["y"], "ь": [""], "э": ["e"],
       "ю": ["yu", "iu", "ju"], "я": ["ya", "ia", "ja"]}
_TR_MULTI = [("ий", ["iy", "ii", "y", "ij", "i"]), ("ия", ["iya", "ia", "iia"]), ("ья", ["ya", "ia", "iya"]),
             ("кс", ["ks", "x"]), ("ье", ["ye", "ie", "e"])]


def translit_variants(name: str, cap: int = 24) -> set[str]:
    """Варианты латиницей: паспортный (ICAO), BGN, «бытовой» («Дмитрий» → Dmitriy, Dmitrii, Dmitry, Dmitrij …)."""
    s = name.lower()
    parts: list[list[str]] = []
    i = 0
    while i < len(s):
        for cyr, lat in _TR_MULTI:
            if s.startswith(cyr, i):
                parts.append(lat)
                i += len(cyr)
                break
        else:
            ch = s[i]
            if i == 0 and ch == "е":
                parts.append(["e", "ye"])
            elif i == 0 and ch in "юя":
                parts.append({"ю": ["yu", "ju", "iu"], "я": ["ya", "ja"]}[ch])
            else:
                parts.append(_TR.get(ch, [ch]))
            i += 1
    out = set()
    for combo in product(*parts):
        out.add("".join(combo).capitalize())
        if len(out) >= cap:
            break
    return out


# Международные и привычные англоязычные написания (Alexander вместо Aleksandr и т. п.)
LATIN_EXTRA = """
Alexander Alexandr Alex Alexey Alexei Aleksey Andrew Anthony Anton Arthur Boris Daniel Danil Denis Dmitri Dmitry Eugene
Evgeny Gleb George Gregory Igor Ilya Ivan Kirill Konstantin Leo Leonid Mikhail Michael Nick Nicholas Nikolai Oleg Paul
Pavel Peter Philip Roman Ruslan Sergey Sergei Stanislav Stepan Timothy Timur Victor Vadim Vladimir Vladislav Yaroslav
Yuri Yury Iurii Fedor Fyodor Theodore Artem Artyom Maksim Maxim Matvey Egor Yegor Gennady Valery Vitaly Vyacheslav
Anna Alina Alice Alla Alyona Anastasia Angelina Antonina Arina Daria Darya Diana Ekaterina Catherine Katherine Kate Katya
Elena Helen Helena Elizaveta Elizabeth Eva Eve Galina Inna Irina Julia Yulia Iuliia Ksenia Kseniya Kristina Christina
Larisa Lidia Lilia Liudmila Lyudmila Margarita Marina Maria Mariya Mary Natalia Natalya Natalie Nina Oksana Olga Olesya
Polina Svetlana Sofia Sofya Sophia Sophie Tatiana Tatyana Ulyana Valentina Valeria Vera Veronika Victoria Viktoria Yana
John James Robert William Thomas Richard Charles Christopher Matthew Steven Joshua Kevin Brian Jason Ryan Eric Adam
Emily Sarah Jessica Jennifer Laura Emma Olivia Linda Susan Karen Lisa Nancy Amanda Rachel Hannah Anne Claire Monica
Aigerim Aidar Azamat Bekzat Nurlan Asel Dinara Aruzhan Gulnara Timofey Savva Platon Arseny Arseniy Bogdan Kamil Rinat
""".split()
# Слишком похожи на обычные слова — именем латиницей не считаем
LATIN_AMBIGUOUS = {"Max", "Mark", "Will", "Bill", "Grant", "Chase", "Rose", "Hope", "Faith", "Joy", "Ray", "Art",
                   "Sky", "Summer", "Dawn", "Rich", "Pat", "Lev", "Yan", "Ian", "Jan", "Ada", "Ruby", "Pascal"}


@lru_cache(maxsize=1)
def latin_first() -> frozenset[str]:
    names = set(LATIN_EXTRA)
    for n in RU_MALE + RU_FEMALE:
        names |= translit_variants(n)
    tech = tech_tokens()
    return frozenset(n for n in names if len(n) >= 3 and n not in LATIN_AMBIGUOUS and n.lower() not in tech)


SURNAME_LAT = re.compile(r"(?:ov|ova|ev|eva|yov|yova|in|ina|yn|yna|sky|skiy|skii|skij|ski|skaya|skaia|tsky|tskiy|"
                         r"tskaya|enko|uk|yuk|chuk|ich|vich|ko|dze|shvili|yan|ian|ykh|ikh|aya|aia|ets|ets)$", re.I)
PATRONYMIC_LAT = re.compile(r"(?:ovich|evich|ich|ovna|evna|ichna|inichna|ogly|kyzy)$", re.I)

# ---------------------------------------------------------------- слова, которые не имена
EXTRA_TECH = """
spring boot apache native kafka hadoop spark airflow jenkins jira confluence visual studio code intellij idea pycharm
webstorm vscode postman swagger windows macos ubuntu debian centos fedora redhat hat openshift nginx tomcat wildfly jboss
oracle mssql clickhouse vertica snowflake databricks tableau power excel word office outlook teams slack zoom figma
sketch adobe photoshop illustrator unity unreal android ios swift xcode flutter dart react angular vue svelte next nuxt
node express nest nestjs django flask fastapi pandas numpy scipy scikit learn pytorch torch tensorflow keras jupyter
notebook colab hugging face transformers langchain openai claude gpt llama bert yolo opencv selenium playwright cypress
jest mocha pytest junit allure testng cucumber gatling jmeter locust prometheus grafana zabbix kibana logstash elastic
elasticsearch splunk sentry datadog terraform ansible helm vault consul istio envoy redis memcached rabbitmq celery
nats grpc graphql rest soap kotlin java scala groovy clojure rust go golang ruby rails php laravel symfony perl haskell
elixir erlang lua pascal delphi fortran cobol matlab sql postgres postgresql mysql mongodb mongo cassandra tarantool
greenplum flink hive presto trino superset looker metabase aws gcp azure yandex cloud sber sbercloud selectel vk
google microsoft amazon apple meta facebook telegram whatsapp github gitlab bitbucket gitflic linkedin habr leetcode
kaggle codeforces stackoverflow docker compose kubernetes podman vagrant virtualbox vmware proxmox linux unix bash zsh
powershell shell vim emacs neovim typescript javascript python html css sass scss less tailwind bootstrap material
webpack vite rollup babel eslint prettier storybook redux mobx rxjs zustand tanstack query router hibernate gradle
maven lombok quarkus micronaut vertx netty akka kibana opensearch minio ceph hdfs yarn oozie sqoop nifi dbt db victoriametrics metrics logs traces
jetpack compose multiplatform active directory cobalt strike metasploit wireshark burp suite kali nmap ghidra ida
pro bpmn uml cucumber appium charles fiddler insomnia notion miro trello asana youtrack teamcity bamboo circleci travis
argo argocd flux keycloak okta auth0 oauth openid jwt ldap kerberos saml stripe paypal firebase supabase heroku vercel
netlify cloudflare digitalocean hetzner bitrix 1c sap salesforce hubspot zendesk freshdesk qlik datalens
""".split()
STOP_EN = """
developer engineer senior junior middle lead team teamlead head chief principal staff software web mobile frontend
backend fullstack full stack data scientist science analyst analytics manager product project qa test tester testing
automation devops sre security architect designer intern trainee student university state school institute college
academy the and of for with from at in on to by my our your about summary profile experience education skills skill
contacts contact phone email resume cv curriculum vitae moscow russia saint petersburg company inc llc ltd group bank
labs lab technologies tech solutions systems digital services service open source hello hi dear regards best thanks
new york january february march april may june july august september october november december monday tuesday
wednesday thursday friday saturday sunday mr mrs ms dr prof phd msc bsc master bachelor degree computer information
technology department faculty programming language languages framework frameworks tools tool platform platforms
system api apis app apps application applications server client database databases machine deep learning artificial
intelligence vision natural processing big analysis engineering management business marketing sales support help
desk office remote hybrid relocation location city country street avenue road lane drive square native speaker
english russian german french spanish chinese level upper intermediate advanced fluent basic course courses
certificate certified award awards hackathon winner prize finalist participant olympiad cup championship
github gitlab portfolio site website blog link links page home main about me personal info information general
key responsibilities achievements projects project work worked working job position title role current previous
present now today year years month months part time contract freelance self employed
""".split()
CYR_STOP = """
разработчик программист инженер аналитик тестировщик архитектор дизайнер менеджер руководитель специалист стажёр стажер
студент студентка ведущий ведущая старший старшая младший младшая главный главная резюме контакты опыт образование
навыки себе цель должность желаемая желаемый зарплата занятость график работы проекты проект достижения курсы
сертификаты языки английский русский немецкий гражданство переезд командировки полная частичная удаленная удалённая
""".split()
# Города — не имена (иначе строка «Нижний Новгород» в шапке принималась за «Фамилия Имя»). Совпадающие с именами и
# частыми фамилиями («Владимир», «Киров», «Королёв») — не включены.
CITIES = """
Москва Санкт-Петербург Петербург Новосибирск Екатеринбург Казань Нижний Новгород Челябинск Самара Омск Ростов-на-Дону
Уфа Красноярск Воронеж Пермь Волгоград Краснодар Саратов Тюмень Тольятти Ижевск Барнаул Ульяновск Иркутск Хабаровск
Ярославль Владивосток Махачкала Томск Оренбург Кемерово Новокузнецк Рязань Астрахань Набережные Челны Пенза
Липецк Чебоксары Калининград Тула Курск Сочи Ставрополь Улан-Удэ Тверь Магнитогорск Иваново Брянск Белгород Сургут
Архангельск Чита Калуга Смоленск Волжский Курган Череповец Орёл Орел Вологда Саранск Владикавказ Якутск Мурманск
Подольск Грозный Тамбов Стерлитамак Петрозаводск Кострома Нижневартовск Новороссийск Йошкар-Ола Таганрог Сыктывкар
Нальчик Шахты Дзержинск Иннополис Химки Мытищи Балашиха Люберцы Зеленоград Долгопрудный Дубна Обнинск
Минск Алматы Астана Ташкент Бишкек Ереван Тбилиси Баку Russia Moscow Kazan Novosibirsk Yekaterinburg
""".split()


def _words(s: str) -> list[str]:
    return [w for w in re.split(r"[^0-9a-zа-яё+#]+", s.lower()) if w]


@lru_cache(maxsize=1)
def tech_tokens() -> frozenset[str]:
    """Все слова словаря стека (синонимы, названия тегов, неподдерживаемые технологии) + EXTRA_TECH."""
    from app.modules.catalog.dictionary import ROLES, STACK_ALIASES, UNSUPPORTED_TECH
    from app.modules.catalog.seed_data import STACK

    out: set[str] = set(EXTRA_TECH)
    for aliases in STACK_ALIASES.values():
        for a in aliases:
            out.update(_words(a))
    for title, aliases in UNSUPPORTED_TECH.items():
        out.update(_words(title))
        for a in aliases:
            out.update(_words(a))
    for t in STACK.values():
        out.update(_words(t[0]))
    for aliases in ROLES.values():
        for a in aliases:
            out.update(_words(a))
    # латиницей — только «слова» длиной ≥ 2 (однобуквенные «c», «r» не мешают)
    return frozenset(w for w in out if len(w) >= 2)


@lru_cache(maxsize=1)
def not_name_lower() -> frozenset[str]:
    return frozenset(tech_tokens() | set(STOP_EN) | {w.lower() for w in CYR_STOP} | {c.lower() for c in CITIES})


@lru_cache(maxsize=1)
def city_words() -> frozenset[str]:
    return frozenset(c.lower() for c in CITIES)
