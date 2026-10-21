#!/usr/bin/env python3
"""Цифры для материалов сдачи «Драфт» — только из docs/NUMBERS.json.

Правило (владелец, 21.10.2026): в README, документации, презентации и сценарии видео нет чисел, вписанных руками.
Каждая цифра берётся здесь из docs/NUMBERS.json по ключу и публикуется вместе с условием: на ком измерено
(симуляция / модель / люди / реальные документы), N, дата, команда пересчёта. Нет ключа — нет цифры (факт
помечается отсутствующим, а текст, который от него зависит, не попадает в материалы).

Кроме NUMBERS.json скрипт читает только описательные сведения из самого репозитория (не метрики качества):
правила продукта из backend/app/core/config.py, число операций API из docs/api/openapi.json, версии библиотек из
backend/requirements.txt и frontend/package-lock.json.

Запуск: python3 docs/submission/numfacts.py [--numbers <путь к NUMBERS.json>] → docs/submission/out/facts.json
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "submission" / "out"
NBSP = "\u00a0"
THIN = "\u202f"


# ---------- форматирование по-русски ----------
def fint(x) -> str:
    s = f"{int(round(x)):,}".replace(",", NBSP)
    return s


def fpct(v: float, nd: int = 1) -> str:
    s = f"{v * 100:.{nd}f}".replace(".", ",")
    return f"{s}{NBSP}%"


def fdec(v: float, nd: int = 2) -> str:
    return f"{v:.{nd}f}".replace(".", ",")


def fmin(v: float) -> str:
    return f"{fdec(v, 0) if float(v).is_integer() else fdec(v, 1)}{NBSP}мин"


def date_ru(s: str | None) -> str:
    if not s:
        return ""
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(s))
    if not m:
        return str(s)
    return f"{m.group(3)}.{m.group(2)}.{m.group(1)}"


def get(d, path: str):
    """Путь вида a.b.0.c или a.top5[id=exact_grade].value (элемент списка по полю)."""
    cur = d
    for p in path.split("."):
        m = re.match(r"^([^\[]+)\[(\w+)=([^\]]+)\]$", p)
        if m:
            lst = cur.get(m.group(1)) if isinstance(cur, dict) else None
            cur = next((x for x in (lst or []) if isinstance(x, dict) and str(x.get(m.group(2))) == m.group(3)), None)
            if cur is None:
                return None
            continue
        if isinstance(cur, dict) and p in cur:
            cur = cur[p]
        elif isinstance(cur, list) and p.isdigit() and int(p) < len(cur):
            cur = cur[int(p)]
        else:
            return None
    return cur


def first(d, *paths):
    for p in paths:
        v = get(d, p)
        if v is not None:
            return p, v
    return None, None


class Facts:
    def __init__(self, numbers: dict):
        self.n = numbers
        self.facts: dict[str, dict] = {}
        self.missing: list[str] = []

    def add(self, fid: str, *, text: str, key: str, cond: str, recompute: str | None, value=None,
            kn: str | None = None, ci: str | None = None, label: str = "", group: str = "", basis: str = ""):
        self.facts[fid] = {
            "text": text, "key": key, "cond": cond, "recompute": recompute or self.n.get("recompute_all", ""),
            "value": value, "kn": kn or "", "ci": ci or "", "label": label, "group": group, "basis": basis,
        }

    def miss(self, fid: str):
        self.missing.append(fid)

    # доля вида {"value", "k", "n", "ci95"}
    def share(self, fid: str, path: str, *, cond: str, recompute: str | None, label: str, group: str, basis: str,
              nd: int = 1):
        v = get(self.n, path)
        if not isinstance(v, dict) or v.get("value") is None:
            return self.miss(fid)
        kn = f"{fint(v['k'])} из {fint(v['n'])}" if v.get("k") is not None and v.get("n") else ""
        ci = ""
        if v.get("ci95"):
            lo, hi = v["ci95"]
            ci = f"95{NBSP}% ДИ {fdec(lo * 100, nd)}–{fpct(hi, nd)}"
        self.add(fid, text=fpct(v["value"], nd), key=path, cond=cond, recompute=recompute, value=v["value"],
                 kn=kn, ci=ci, label=label, group=group, basis=basis)


def build(numbers: dict) -> dict:
    F = Facts(numbers)
    n = numbers

    # ---------- банк заданий ----------
    b = n.get("bank") or {}
    if b.get("families"):
        seeds = f"{b['seeds']} вариантов-зёрен на каждое семейство, " if b.get("seeds") else ""
        cond_b = (f"автоматическая проверка банка: {seeds}"
                  f"коммит банка {b.get('bank_commit', '')}, {date_ru(b.get('synced_at'))}")
        rc = b.get("recompute")
        F.add("bank_families", text=fint(b["families"]), value=b["families"], key="bank.families", cond=cond_b,
              recompute=rc, label="семейств заданий в банке", group="bank", basis="проверка банка")
        for fid, k, lab in (("bank_variants", "unique_variants_20seeds", "уникальных вариантов на проверке"),
                            ("bank_checks", "checks", "автоматических проверок ответов"),
                            ("bank_checks_failed", "checks_failed", "проверок с ошибкой"),
                            ("bank_directions", "directions", "направлений"),
                            ("bank_practical", "code_and_open_families", "семейств с кодом и развёрнутым ответом"),
                            ("bank_seeds", "seeds", "вариантов на семейство при проверке")):
            if b.get(k) is not None:
                F.add(fid, text=fint(b[k]), value=b[k], key=f"bank.{k}", cond=cond_b, recompute=rc, label=lab,
                      group="bank", basis="проверка банка")
            else:
                F.miss(fid)
    else:
        F.miss("bank_families")

    # ---------- вердикт по грейду (симуляция продукта) ----------
    gv = n.get("grade_verdict") or {}
    # Главная строка теста — стандартные условия (как в заголовке пар), а не отдельный «калиброванный» прогон main:
    # иначе в README рядом оказались бы цифры разных прогонов без пометки.
    _stv = ((gv.get("st") or {}).get("view") or {})
    MP = "grade_verdict.st.view" if _stv.get("verdict_accuracy") else "grade_verdict.main"
    m = _stv if _stv.get("verdict_accuracy") else (gv.get("main") or {})
    if m.get("verdict_accuracy"):
        cond_s = ((f"стандартные условия (как в аналогичных решениях), зёрна {m['seeds'][0]}–{m['seeds'][-1]}; " if MP.endswith("st.view") and m.get("seeds") else "") + f"симуляция продукта: модельные кандидаты, не люди; N{NBSP}={NBSP}{fint(m.get('n', 0))}; тот же движок "
                  f"теста, что на сайте; банк {m.get('bank_commit') or b.get('bank_commit', '')} "
                  f"({fint(m.get('bank_families') or b.get('families') or 0)} семейств заданий); {date_ru(m.get('date') or n.get('generated_at'))}")
        rc = m.get("command") or gv.get("recompute")
        g = "grade"
        bs = "симуляция, модельные кандидаты"
        F.share("verdict_accuracy", f"{MP}.verdict_accuracy", cond=cond_s, recompute=rc,
                label="верный итог проверки заявленного грейда", group=g, basis=bs)
        F.share("confident_share", f"{MP}.confident_share", cond=cond_s, recompute=rc,
                label="кандидатов получают уверенный ответ уже по основному тесту", group=g, basis=bs)
        F.share("confident_accuracy", f"{MP}.confident_accuracy", cond=cond_s, recompute=rc,
                label="точность уверенного ответа", group=g, basis=bs)
        F.share("followup_share", f"{MP}.followup_share", cond=cond_s, recompute=rc,
                label="кандидатов направляется на короткий дополнительный этап", group=g, basis=bs)
        F.share("exact_grade", f"{MP}.exact_grade", cond=cond_s, recompute=rc,
                label="грейд определён точно", group=g, basis=bs)
        F.share("false_confirm_all", f"{MP}.false_confirm_all", cond=cond_s, recompute=rc,
                label="ложных подтверждений от всех кандидатов", group=g, basis=bs)
        F.share("gross_error", f"{MP}.gross_error", cond=cond_s, recompute=rc,
                label="ошибок больше чем на одну ступень", group=g, basis=bs)
        mt = m.get("minutes_total") or {}
        if mt.get("mean") is not None:
            F.add("minutes_mean", text=fmin(mt["mean"]), value=mt["mean"], key=f"{MP}.minutes_total.mean",
                  cond=cond_s, recompute=rc, label="среднее время теста", group=g, basis=bs)
        if mt.get("p90") is not None:
            F.add("minutes_p90", text=fmin(mt["p90"]), value=mt["p90"], key=f"{MP}.minutes_total.p90",
                  cond=cond_s, recompute=rc, label="время теста у 90 % кандидатов не больше", group=g, basis=bs)
        rt = m.get("retest") or {}
        if rt:
            F.share("retest_verdict", "grade_verdict.main.retest.verdict_agreement", cond=cond_s + "; повтор на другом наборе заданий",
                    recompute=rc, label="совпадение итога при повторном прохождении", group=g, basis=bs)
            F.share("retest_exact", "grade_verdict.main.retest.exact_agreement", cond=cond_s + "; повтор на другом наборе заданий",
                    recompute=rc, label="совпадение грейда при повторном прохождении", group=g, basis=bs)
        for sc, lab in (("misspec", "при неточно известной трудности заданий"),
                        ("rater_noise", "при ошибках проверки развёрнутых ответов")):
            s = gv.get(sc) or {}
            if s.get("verdict_accuracy"):
                c2 = (f"симуляция продукта, модельные кандидаты; N{NBSP}={NBSP}{fint(s.get('n', 0))}; "
                      f"{'трудность и различающая сила заданий в «мире» сдвинуты случайно, движок об этом не знает' if sc == 'misspec' else 'проверка развёрнутых ответов ошибается случайно'}; "
                      f"{date_ru(s.get('date') or m.get('date'))}")
                F.share(f"verdict_{sc}", f"grade_verdict.{sc}.verdict_accuracy", cond=c2,
                        recompute=s.get("command") or rc, label=f"верный итог {lab}", group=g, basis=bs)
            else:
                F.miss(f"verdict_{sc}")
    else:
        F.miss("verdict_accuracy")

    # ---------- «Обмани тест»: боты через движок ----------
    cb = n.get("cheat_bots")
    if isinstance(cb, dict) and cb:
        F.add("cheat_bots_present", text="есть", key="cheat_bots", cond=str(cb.get("what", ""))[:300],
              recompute=cb.get("recompute"), label="прогон ботов", group="cheat", basis="симуляция, боты")
        _, conf = first(cb, "confirmed_any.value", "summary.confirmed_share.value", "confirmed_share.value")
        if conf is not None:
            p, v = first(cb, "confirmed_any", "summary.confirmed_share", "confirmed_share")
            F.share("cheat_bots_confirmed", f"cheat_bots.{p}", cond=f"боты со стратегиями обмана через движок теста, "
                    f"N{NBSP}={NBSP}{fint(get(cb, p + '.n') or 0)}; {date_ru(cb.get('date') or cb.get('generated_at'))}",
                    recompute=cb.get("recompute"), label="ботов получили подтверждение", group="cheat",
                    basis="симуляция, боты")
    else:
        F.miss("cheat_bots_present")

    # ---------- подбор: синтетические отложенные миры ----------
    mt = n.get("matching") or {}
    p5 = mt.get("p5")
    if isinstance(p5, dict) and p5.get("mean") is not None:
        cond_m = (f"модель: {fint(mt.get('n_needs', 0))} потребностей × {fint(mt.get('n_candidates', 0))} модельных "
                  f"кандидатов на отложенных мирах (истина известна, не люди); миры заморожены до прогона, веса подбирались "
                  f"на других мирах; {date_ru(mt.get('generated_at'))}")
        rc = mt.get("recompute")
        ci = f"95{NBSP}% ДИ {fdec(p5['lo'])}–{fdec(p5['hi'])}" if p5.get("lo") is not None else ""
        F.add("match_p5", text=fdec(p5["mean"]), value=p5["mean"], key="matching.p5.mean", cond=cond_m, recompute=rc,
              ci=ci, label="доля подходящих в первой пятёрке подборки (P@5)", group="match", basis="модель")
        mrr = mt.get("mrr") or {}
        if mrr.get("mean") is not None:
            F.add("match_mrr", text=fdec(mrr["mean"]), value=mrr["mean"], key="matching.mrr.mean", cond=cond_m,
                  recompute=rc, label="MRR — насколько высоко первый подходящий кандидат", group="match", basis="модель")
        rep = (mt.get("replication") or [None])[0]
        if rep and rep.get("p5") is not None:
            F.add("match_p5_rep", text=fdec(rep["p5"]), value=rep["p5"], key="matching.replication.0.p5", cond=cond_m,
                  recompute=rc, label="P@5 на втором отложенном мире", group="match", basis="модель")
        bl = mt.get("baselines") or {}
        for fid, k, lab in (("match_bm25", "bm25", "поиск по тексту резюме (BM25)"),
                            ("match_no_test", "no_test", "тот же подбор без результатов теста"),
                            ("match_keywords", "keywords_grade", "ключевые слова + заявленный грейд"),
                            ("match_no_fsp", "no_fsp", "тот же подбор без учёта ФСП")):
            if (bl.get(k) or {}).get("p5") is not None:
                F.add(fid, text=fdec(bl[k]["p5"]), value=bl[k]["p5"], key=f"matching.baselines.{k}.p5", cond=cond_m,
                      recompute=rc, label=f"P@5: {lab}", group="match", basis="модель")
    else:
        F.miss("match_p5")

    # ---------- разбор реальных вакансий hh.ru ----------
    hh = n.get("hh_match") or {}
    if (hh.get("direction_ok") or {}).get("value") is not None:
        site = hh.get("site") if isinstance(hh.get("site"), dict) else None
        cond_h = (f"реальные вакансии hh.ru: {str(hh.get('set') or '').strip()}; N{NBSP}={NBSP}{fint(hh.get('n', 0))}; "
                  f"{date_ru(hh.get('generated_at'))}")
        rc = hh.get("recompute")
        F.share("hh_direction", "hh_match.direction_ok", cond=cond_h, recompute=rc,
                label="верно определено направление вакансии", group="hh", basis="реальные вакансии")
        if (hh.get("direction_ok_adjudicated") or {}).get("value") is not None:
            F.share("hh_direction_adj", "hh_match.direction_ok_adjudicated",
                    cond=cond_h + "; спорные метки hh.ru перепроверены двумя независимыми моделями-арбитрами (не люди)",
                    recompute=rc, label="направление после проверки спорных меток", group="hh",
                    basis="реальные вакансии, арбитры — модели")
        # hh_match.grade_ok не публикуем: грейд берётся из слова в названии вакансии, и «метка» берётся из того же
        # слова — совпадение тавтологично (решение оркестратора 21.10).
        F.share("hh_skills", "hh_match.key_skills_recall", cond=cond_h, recompute=rc,
                label="ключевых навыков вакансии найдено разбором", group="hh", basis="реальные вакансии")
        if site and (site.get("value") is not None or site.get("direction_ok")):
            p = "hh_match.site" if site.get("value") is not None else "hh_match.site.direction_ok"
            F.share("hh_site", p, cond=str(site.get("cond") or site.get("set_ru") or cond_h), recompute=site.get("recompute") or rc,
                    label="направление вакансии (цифра на сайте)", group="hh", basis="реальные вакансии")
        sm = (hh.get("selection_model_pool") or {}).get("confirmed_exact")
        if sm:
            F.share("hh_confirmed_pool", "hh_match.selection_model_pool.confirmed_exact",
                    cond=cond_h + "; пул кандидатов — модельный (демо-мир), проверка механики, не рынка",
                    recompute=rc, label="вакансий, где в подборке есть кандидат с подтверждённым грейдом точной категории",
                    group="hh", basis="реальные вакансии, модельный пул")
        nf, npool = hh.get("no_fsp_top5_share"), hh.get("no_fsp_pool_share")
        if nf and npool:
            F.add("no_fsp_top5", text=fpct(nf["share"], 0), value=nf["share"], key="hh_match.no_fsp_top5_share.share",
                  cond=cond_h + "; модельный пул", recompute=rc, kn=f"{fint(nf['k'])} из {fint(nf['n'])}",
                  label="мест в первых пятёрках у кандидатов без ФСП", group="hh", basis="модельный пул")
            F.add("no_fsp_pool", text=fpct(npool["share"], 0), value=npool["share"], key="hh_match.no_fsp_pool_share.share",
                  cond=cond_h + "; модельный пул", recompute=rc, kn=f"{fint(npool['k'])} из {fint(npool['n'])}",
                  label="доля кандидатов без ФСП в пуле", group="hh", basis="модельный пул")
    else:
        F.miss("hh_direction")

    # ---------- античит ----------
    ac = n.get("anticheat") or {}
    ho = ac.get("holdout_offline") or {}
    # Публикуем только отложенный набор с отметкой «один прогон после фиксации кода» (single_pass) — иначе это не проверка.
    if ho.get("total") and ho.get("single_pass"):
        cond_a = (f"отложенный набор атак на проверку ответов, составлен после фиксации кода фильтра "
                  f"(коммит {ho.get('frozen_after_filter_commit', '')}), один прогон без донастройки; "
                  f"N{NBSP}={NBSP}{fint(ho['total'])} атак и {fint(ho.get('honest_n', 0))} честных ответов; "
                  f"{date_ru((ac.get('llm_chain') or {}).get('date') or n.get('generated_at'))}")
        rc = ac.get("recompute")
        F.add("ac_filter", text=fpct(ho["rate"]), value=ho["rate"], key="anticheat.holdout_offline.rate", cond=cond_a,
              recompute=rc, kn=f"{fint(ho.get('caught', 0))} из {fint(ho['total'])}",
              label="атак перехвачено фильтром до оценки моделью", group="ac", basis="отложенный набор атак")
        if ho.get("false_positive_rate") is not None:
            F.add("ac_fp", text=fpct(ho["false_positive_rate"]), value=ho["false_positive_rate"],
                  key="anticheat.holdout_offline.false_positive_rate", cond=cond_a, recompute=rc,
                  kn=f"{fint(ho.get('false_positives', 0))} из {fint(ho.get('honest_n', 0))}",
                  label="ложных срабатываний на честных ответах", group="ac", basis="отложенный набор")
        lc = ac.get("llm_chain") or {}
        if lc.get("total") and lc.get("pierced") is not None:
            F.add("ac_chain_pierced", text=f"{fint(lc['pierced'])} из {fint(lc['total'])}", value=lc.get("pierce_rate"),
                  key="anticheat.llm_chain.pierced", cond=cond_a + "; полная цепочка проверки", recompute=ac.get("recompute_llm"),
                  label="атак прошли всю цепочку защиты", group="ac", basis="отложенный набор атак")
        bf = ac.get("behavioral_followup") or {}
        if bf.get("honest_simulated_total"):
            cb2 = (f"симуляция поведения: {fint(bf['honest_simulated_total'])} модельных честных сессий и "
                   f"{fint(bf.get('bot_simulated_total', 0))} модельных ботов; правило «два и больше сигнала или прямое "
                   f"доказательство», автоматической блокировки нет")
            F.add("ac_honest_false", text=f"{fint(bf['honest_false_followup'])} из {fint(bf['honest_simulated_total'])}",
                  value=bf.get("honest_false_followup_rate"), key="anticheat.behavioral_followup.honest_false_followup",
                  cond=cb2, recompute=rc, label="честных кандидатов ошибочно отправлено на проверку", group="ac",
                  basis="симуляция")
            if bf.get("bot_detection_rate") is not None:
                F.add("ac_bot_detect", text=fpct(bf["bot_detection_rate"], 0), value=bf["bot_detection_rate"],
                      key="anticheat.behavioral_followup.bot_detection_rate", cond=cb2, recompute=rc,
                      kn=f"{fint(bf.get('bot_flagged_followup', 0))} из {fint(bf.get('bot_simulated_total', 0))}",
                      label="модельных ботов отправлено на дополнительную проверку", group="ac", basis="симуляция")
        if ac.get("proctoring_signals_total"):
            F.add("ac_signals", text=fint(ac["proctoring_signals_total"]), value=ac["proctoring_signals_total"],
                  key="anticheat.proctoring_signals_total", cond="описание механики: число видов сигналов в коде",
                  recompute=rc, label="видов сигналов честности прохождения", group="ac", basis="код")
    else:
        F.miss("ac_filter")

    # ---------- протоколы ФСП ----------
    fi = get(n, "fsp_protocols.index") or {}
    if fi.get("documents"):
        cond_f = (f"официальные протоколы ФСП России {fi.get('years', '')} с сайта федерации; судьи, тренеры и справки "
                  f"исключены; {date_ru(fi.get('generated_at'))}")
        rc = fi.get("recompute") or get(n, "fsp_protocols.recompute")
        for fid, k, lab in (("fsp_documents", "documents", "официальных протоколов в индексе"),
                            ("fsp_events", "events", "соревнований"),
                            ("fsp_results", "results", "результатов"),
                            ("fsp_athletes", "athletes", "спортсменов"),
                            ("fsp_regions", "regions", "субъектов РФ"),
                            ("fsp_evsk", "athletes_with_evsk_norm", "спортсменов с выполненным нормативом ЕВСК")):
            if fi.get(k) is not None:
                F.add(fid, text=fint(fi[k]), value=fi[k], key=f"fsp_protocols.index.{k}", cond=cond_f, recompute=rc,
                      label=lab, group="fsp", basis="реальные документы")
        if fi.get("years"):
            F.add("fsp_years", text=str(fi["years"]), value=fi["years"], key="fsp_protocols.index.years", cond=cond_f,
                  recompute=rc, label="годы протоколов", group="fsp", basis="реальные документы")
        oa = get(n, "fsp_protocols.ocr_audit")
        if isinstance(oa, dict):
            p, v = first(oa, "accuracy", "field_accuracy", "rows_ok_share")
            if isinstance(v, (int, float)):
                F.add("fsp_ocr", text=fpct(v), value=v, key=f"fsp_protocols.ocr_audit.{p}",
                      cond=f"ручная сверка распознавания с исходными PDF; {date_ru(oa.get('generated_at'))}",
                      recompute=oa.get("recompute") or rc, label="точность распознавания протоколов", group="fsp",
                      basis="реальные документы")
    else:
        F.miss("fsp_documents")

    # ---------- нагрузка и мутационный контроль (появятся после волны 2) ----------
    ld = n.get("load")
    if isinstance(ld, dict) and ld:
        p, v = first(ld, "p95_ms", "summary.p95_ms", "http.p95_ms")
        if v is not None:
            F.add("load_p95", text=f"{fint(v)}{NBSP}мс", value=v, key=f"load.{p}",
                  cond=f"нагрузочный прогон: {ld.get('what') or ld.get('scenario') or ''}; {date_ru(ld.get('date') or ld.get('generated_at'))}",
                  recompute=ld.get("recompute"), label="время ответа у 95 % запросов", group="load", basis="замер")
        p, v = first(ld, "users", "summary.users", "rps")
        if v is not None:
            F.add("load_users", text=fint(v), value=v, key=f"load.{p}", cond="нагрузочный прогон",
                  recompute=ld.get("recompute"), label="одновременных пользователей / запросов в секунду", group="load",
                  basis="замер")
    else:
        F.miss("load_p95")
    mu = n.get("mutation_testing")
    if isinstance(mu, dict) and mu:
        p, v = first(mu, "killed_share", "score", "kill_rate")
        if isinstance(v, (int, float)):
            F.add("mutation", text=fpct(v), value=v, key=f"mutation_testing.{p}",
                  cond=f"мутационный контроль банка: в проверку ответов вносятся ошибки и считается, сколько поймано; {date_ru(mu.get('date') or mu.get('generated_at'))}",
                  recompute=mu.get("recompute"), label="внесённых ошибок поймано проверкой банка", group="bank",
                  basis="мутационный контроль")
    else:
        F.miss("mutation")

    # ---------- «один в один» на открытом генераторе другого решения ----------
    # Обе строки рядом (решение владельца 21.10): по умолчанию и «строго запрошенный грейд» с ценой. Название
    # другого решения не публикуем: в NUMBERS.json условие уже обезличено (condition_ru).
    ext = (n.get("external_benchmarks") or {}).get("devdev_1to1") or {}
    if ext.get("main") and ext.get("condition_ru"):
        chk = re.sub(r"^[АA]\d+,\s*", "независимый рецензент, ", ext.get("checked_by") or "")  # без внутренних кодов агентов
        cond_x = ext["condition_ru"] + (f"; проверка: {chk}" if chk else "")
        rc_x = ext.get("recompute")
        base_k = "external_benchmarks.devdev_1to1"

        def dec3(v):
            return fdec(v, 3)

        def pp(v):
            return f"{'+' if v > 0 else '−' if v < 0 else ''}{fdec(abs(v) * 100, 1)}{NBSP}п.{NBSP}п."

        def sgn3(v):
            return f"{'+' if v > 0 else '−' if v < 0 else ''}{fdec(abs(v), 3)}"

        labels = {"ndcg10": ("nDCG@10", dec3, sgn3), "p5": ("точность в топ-5", fpct, pp),
                  "p10": ("точность в топ-10", fpct, pp), "rr": ("первый подходящий — насколько высоко (MRR)", fpct, pp),
                  "overrated10": ("переоценённых в топ-10 (меньше — лучше)", fpct, pp)}
        for mode, tag in (("main", "по умолчанию"), ("exact_option_api", "«строго запрошенный грейд»")):
            for m, (lab, f1, f2) in labels.items():
                v = (ext.get(mode) or {}).get(m)
                if not v:
                    continue
                short = "ext_" + ("main" if mode == "main" else "exact") + "_" + m
                ci = ""
                if v.get("ours_ci95"):
                    lo, hi = v["ours_ci95"]
                    ci = f"95{NBSP}% ДИ {f1(lo)}–{f1(hi)}"
                F.add(short, text=f1(v["ours"]), value=v["ours"], key=f"{base_k}.{mode}.{m}.ours", cond=cond_x,
                      recompute=rc_x, ci=ci, label=f"{lab}, наш подбор, режим {tag}", group="ext", basis="открытый генератор")
                dci = ""
                if v.get("diff_ci95"):
                    lo, hi = v["diff_ci95"]
                    dci = f"95{NBSP}% ДИ {f2(lo)}…{f2(hi)}"
                F.add(short + "_diff", text=f2(v["diff"]), value=v["diff"], key=f"{base_k}.{mode}.{m}.diff",
                      cond=cond_x, recompute=rc_x, ci=dci, label=f"{lab}: разность с другим решением, режим {tag}",
                      group="ext", basis="открытый генератор")
                if mode == "main":
                    F.add("ext_other_" + m, text=f1(v["other"]), value=v["other"], key=f"{base_k}.main.{m}.other",
                          cond=cond_x, recompute=rc_x, label=f"{lab}, ранжирование другого решения его же кодом",
                          group="ext", basis="открытый генератор")
    else:
        F.miss("ext_main_ndcg10")

    # ---------- журнал отчётных прогонов: что заморожено до прогона и чем проверено ----------
    journal = []

    def jr(what, key, value, extra="", kind=""):
        if value:
            journal.append({"what": what, "key": key, "kind": kind, "hash": str(value)[:12], "extra": extra})

    gvm = (n.get("grade_verdict") or {}).get("main") or {}
    jr("Тест на грейд — итоговый прогон", "grade_verdict.main.bank_content_hash",
       gvm.get("bank_content_hash"), kind="банк заданий", extra=f"N{NBSP}={NBSP}{fint(gvm['n'])}" if gvm.get("n") else "")
    mt_ = n.get("matching") or {}
    jr("Подбор — отложенные миры", "matching.freeze_sha256", mt_.get("freeze_sha256"), kind="FREEZE")
    jr("Вакансии hh.ru — второй отложенный набор", "hh_match.manifest_sha256",
       (n.get("hh_match") or {}).get("manifest_sha256"), kind="список вакансий")
    jr("Чужой открытый генератор — один в один", "external_benchmarks.devdev_1to1.condition_ru",
       "515460d3" if "FREEZE 515460d3" in (ext.get("condition_ru") or "") else None,
       kind="FREEZE", extra="пересчёт в чистой копии — 0 расхождений" if "0 расхождений" in (ext.get("checked_by") or "") else "")
    dj = ((n.get("external_benchmarks") or {}).get("djinni") or {}).get("freeze") or {}
    jr("Открытый набор вакансий и резюме", "external_benchmarks.djinni.freeze.bench_sha256",
       dj.get("bench_sha256"), kind="набор")
    ah = (n.get("anticheat") or {}).get("holdout_offline") or {}
    jr("Защита проверки ответов — набор атак", "anticheat.holdout_offline.dataset_sha256",
       ah.get("dataset_sha256") if ah.get("single_pass") else None, kind="набор атак", extra="один проход")
    oa = (n.get("fsp_protocols") or {}).get("ocr_audit") or {}
    jr("Протоколы ФСП — ручная сверка", "fsp_protocols.ocr_audit.sample_sha256", oa.get("sample_sha256"), kind="выборка",
       extra=f"{fint(oa['pages_checked'])} страниц" if oa.get("pages_checked") else "")

    # ---------- пары «стандартные условия / проверка на прочность» ----------
    pairs = build_pairs(n, F.facts)

    # ---------- описательные сведения из репозитория ----------
    desc = describe_repo()
    return {
        "source": "docs/NUMBERS.json",
        "numbers_generated_at": n.get("generated_at"),
        "numbers_git_commit": n.get("git_commit"),
        "recompute_all": n.get("recompute_all"),
        "facts": F.facts,
        "missing": F.missing,
        "pairs": pairs,
        "journal": journal,
        "repo": desc,
    }


def _fmt_val(v, fmt: str):
    """Значение из NUMBERS.json любого из принятых видов → (текст, число, «k из n», ДИ)."""
    if isinstance(v, dict):
        if v.get("value") is not None:
            num = v["value"]
            kn = f"{fint(v['k'])} из {fint(v['n'])}" if v.get("k") is not None and v.get("n") else ""
            ci = ""
            if v.get("ci95"):
                lo, hi = v["ci95"]
                ci = (f"95{NBSP}% ДИ {fdec(lo * 100, 1)}–{fpct(hi)}" if fmt == "pct" else f"95{NBSP}% ДИ {fdec(lo)}–{fdec(hi)}")
        elif v.get("mean") is not None:
            num, kn = v["mean"], ""
            ci = ""
            if v.get("lo") is not None:
                ci = (f"95{NBSP}% ДИ {fdec(v['lo'] * 100, 1)}–{fpct(v['hi'])}" if fmt == "pct"
                      else f"95{NBSP}% ДИ {fdec(v['lo'])}–{fdec(v['hi'])}")
        else:
            return None
    elif isinstance(v, (int, float)):
        num, kn, ci = v, "", ""
    else:
        return None
    return {"text": fpct(num) if fmt == "pct" else fdec(num), "value": num, "kn": kn, "ci": ci}


def _meta_cond(m: dict) -> str:
    """Условие прогона одной строкой из блока top5_meta.* (А4)."""
    if not isinstance(m, dict):
        return ""
    parts = []
    if isinstance(m.get("population"), str):
        parts.append(str(m["population"]))
    if m.get("n"):
        parts.append(f"N{NBSP}={NBSP}{fint(m['n'])}")
    if m.get("seeds"):
        parts.append(f"зёрна {m['seeds']}")
    if m.get("bank_content_hash"):
        parts.append(f"банк {str(m['bank_content_hash'])[:8]}")
    if m.get("date"):
        parts.append(date_ru(m["date"]))
    return "; ".join(parts)


def _side(n: dict, facts: dict, spec: dict | None, fmt: str):
    if not spec:
        return None
    paths = spec.get("paths") or ([spec["path"]] if spec.get("path") else [])
    for pth in paths:
        v = get(n, pth)
        out = _fmt_val(v, fmt) if v is not None else None
        if not out:
            continue
        cond = ""
        if isinstance(v, dict) and v.get("condition_ru"):
            cond = str(v["condition_ru"])
        for cp in ([spec["cond"]] if isinstance(spec.get("cond"), str) else spec.get("cond") or []):
            c = get(n, cp)
            if c and not cond:
                cond = str(c)
        if spec.get("meta") and not cond:  # условие самой строки (condition_ru) точнее сводки прогона
            cond = _meta_cond(get(n, spec["meta"])) or cond
        rc = (v.get("recompute") if isinstance(v, dict) else None) or (get(n, spec["meta"] + ".command") if spec.get("meta") else None)
        out.update(key=pth, cond=cond, recompute=rc or "")
        if spec.get("no_kn"):
            out["kn"] = ""  # для каппы «k из n» — не доля, не показываем
        return out
    if spec.get("fact") and spec["fact"] in facts:
        f = facts[spec["fact"]]
        return {"text": f["text"], "value": f["value"], "kn": f["kn"], "ci": f["ci"], "key": f["key"], "cond": f["cond"],
                "recompute": f["recompute"]}
    return None


def build_pairs(n: dict, facts: dict) -> dict:
    cfg_p = ROOT / "docs/submission/numbers_pairs.json"
    if not cfg_p.exists():
        return {"pairs": [], "real": []}
    cfg = json.loads(cfg_p.read_text(encoding="utf-8"))
    out = {"pairs": [], "real": []}
    for p in cfg.get("pairs", []):
        nk = {"no_kn": True} if p.get("no_kn") else {}
        out["pairs"].append({"id": p["id"], "label": p["label"], "hint": p.get("hint", ""),
                             "standard": _side(n, facts, {**(p.get("standard") or {}), **nk} if p.get("standard") else None, p.get("fmt", "pct")),
                             "hard": _side(n, facts, {**(p.get("hard") or {}), **nk} if p.get("hard") else None, p.get("fmt", "pct"))})
    for r in cfg.get("real", []):
        out["real"].append({"id": r["id"], "label": r["label"], "value": _side(n, facts, r, r.get("fmt", "pct"))})
    return out


def describe_repo() -> dict:
    out: dict = {}
    cfg = (ROOT / "backend/app/core/config.py").read_text(encoding="utf-8")
    for k in ("grade_change_interval_days", "retake_same_grade_days", "invitation_cooldown_days", "probe_time_limit_s"):
        mm = re.search(rf"^\s*{k}: int = ([0-9 *]+)", cfg, re.M)
        if mm:
            out[k] = int(eval(mm.group(1), {"__builtins__": {}}))  # «15 * 60» — простое выражение из конфигурации
    if "probe_time_limit_s" in out:
        out["probe_minutes"] = out["probe_time_limit_s"] // 60
    rk = ROOT / "backend/app/modules/matching/ranking.py"
    if rk.exists():
        mm = re.search(r"^WEIGHTS\s*=\s*(\{[^}]*\})", rk.read_text(encoding="utf-8"), re.M)
        if mm:
            import ast
            w = ast.literal_eval(mm.group(1))
            out["w"] = {k: round(v * 100) for k, v in w.items()}  # доли скора подбора, % (из кода ranking.py)
            for k, v in out["w"].items():
                out[f"w_{k}"] = v
    sp = ROOT / "backend/app/modules/assessment/sprt.py"
    if sp.exists():
        mm = re.search(r"^DEFAULT_ALPHA\s*(?::\s*float)?\s*=\s*([0-9.]+)", sp.read_text(encoding="utf-8"), re.M)
        if mm:
            out["sprt_alpha_pct"] = f"{fdec(float(mm.group(1)) * 100, 0)}{NBSP}%"  # уровень ошибки ранней остановки (код)
    oa = ROOT / "docs/api/openapi.json"
    if oa.exists():
        d = json.loads(oa.read_text(encoding="utf-8"))
        out["api_paths"] = len(d.get("paths", {}))
        ops = [(o.get("tags") or ["—"])[0] for p in d.get("paths", {}).values() for m, o in p.items()
               if m in ("get", "post", "put", "patch", "delete")]
        out["api_operations"] = len(ops)
        desc = {t["name"]: t.get("description", "") for t in d.get("tags", [])}
        cnt: dict[str, int] = {}
        for t in ops:
            cnt[t] = cnt.get(t, 0) + 1
        out["api_tags"] = [{"tag": t, "ops": c, "description": desc.get(t, "")} for t, c in
                           sorted(cnt.items(), key=lambda x: -x[1])]
        out["api_tag_count"] = len(cnt)
        out["api_version"] = d.get("info", {}).get("version", "")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--numbers", default=str(ROOT / "docs" / "NUMBERS.json"))
    ap.add_argument("--out", default=str(OUT / "facts.json"))
    a = ap.parse_args()
    numbers = json.loads(Path(a.numbers).read_text(encoding="utf-8"))
    res = build(numbers)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"фактов: {len(res['facts'])}, нет в NUMBERS.json: {', '.join(res['missing']) or '—'} → {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
