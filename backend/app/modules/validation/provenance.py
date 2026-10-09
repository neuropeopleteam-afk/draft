"""Ф6 (Н7, Н8): честные подписи /validation и экрана старта теста из одного источника — без пересчёта чисел.

- Банк сейчас — манифест синхронизации банка (assessment_bank/BANK_SYNC.json): число семейств, hash, коммит, дата.
- Отчёт симуляции (data/report.json, ``make validate``) — его дата, банк, на котором он посчитан, и совпадает ли
  этот банк с текущим. Если не совпадает, числа отчёта — исторические и подписываются датой, а не «сейчас».
- Калибровка параметров — на панели МОДЕЛЕЙ (не людей): сколько семейств из текущего банка она покрывает.
- Длина теста — из конфигурации и итогов симуляции того же отчёта (синтетические кандидаты, модель ответов);
  время симуляции на людей не переносится: людям показываются только лимиты (минуты) и доля дотестирования в модели.
"""
from __future__ import annotations

from app.modules.assessment.bank_engine import bank_manifest
from app.modules.validation.signature import git_commit


def provenance(report: dict) -> dict:
    m = bank_manifest()
    rb = report.get("bank") or {}
    cal = report.get("calibration") or {}
    now_n = m.get("n_families")
    same = bool(m.get("content_hash")) and m.get("content_hash") == rb.get("content_hash")
    return {
        "bank_now": {"n_families": now_n, "content_hash": m.get("content_hash"), "commit": m.get("commit"),
                     "synced_at": m.get("synced_at")},
        "report": {"generated_at": report.get("generated_at"), "bank_n_families": rb.get("n_families"),
                   "bank_hash": rb.get("content_hash"), "bank_commit": rb.get("commit"),
                   "bank_synced_at": rb.get("synced_at"), "same_bank": same,
                   "n_per_direction": report.get("n_per_direction")},
        "calibration": {"source": "model_panel", "status": cal.get("status"), "panel": cal.get("panel"),
                        "n_families": cal.get("n_families"), "of_families": now_n, "humans": False,
                        "used_in_decision": False},
        "code_commit": git_commit(),
    }


def length_info(report: dict) -> dict:
    """Длина теста для экрана старта: лимиты конфигурации + среднее и доля дотестирования в симуляции отчёта."""
    sim = report.get("simulation") or {}
    cfg, mean = sim.get("config") or {}, sim.get("mean") or {}
    if not cfg or report.get("missing"):
        return {"missing": True}
    return {
        "min_items": cfg.get("min_items"), "max_items": cfg.get("max_items"), "max_minutes": cfg.get("max_minutes"),
        "ext_items": cfg.get("ext_items"), "ext_minutes": cfg.get("ext_minutes"),
        "sim_mean_items": mean.get("mean_items"), "sim_extension_share": mean.get("extension_share"),
        "sim_n_per_direction": report.get("n_per_direction"), "sim_directions": len(sim.get("directions") or {}),
        "generated_at": report.get("generated_at"),
        "world": "симуляция на синтетических кандидатах (модель ответов), не замер на людях",
    }
