"""Банк (А3, 21.10): публичный вид варианта не раскрывает ключ и механику, в условии нет грейда.

Проверка 20.10 нашла: поле ``sim_effect`` у действий инцидента раскрывало ключ шага, в условиях было
«Уровень Senior — …», «Вы — главный инженер (Principal)». Тест идёт по ВСЕМ семействам выдачи на 3 seed;
полный прогон на 20 seed — ``tools/bank_audit.py`` (docs/bank/audit_2110.json).
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from assessment_bank.registry import generate, load_specs
from assessment_bank.schema import public_incident

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("bank_audit", ROOT / "tools" / "bank_audit.py")
bank_audit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bank_audit)  # type: ignore[union-attr]

FIDS = sorted(load_specs())
SEEDS = (1, 2, 3)


def test_bank_has_families():
    assert len(FIDS) >= 1500


@pytest.mark.parametrize("chunk", range(8))
def test_public_view_has_no_secret_fields_and_no_grade(chunk):
    bad_leak, bad_grade = [], []
    for fid in FIDS[chunk::8]:
        for s in SEEDS:
            v = generate(fid, s)
            pv = v.public_view()
            lk = bank_audit._walk_keys({k: pv[k] for k in pv if k != "meta"}) + bank_audit._walk_keys(pv["meta"], ".meta")
            if lk:
                bad_leak.append((fid, s, lk[:3]))
            if bank_audit.GRADE_RX.search(bank_audit._public_text(pv)):
                bad_grade.append((fid, s))
            # ключ не уходит в браузер ни в каком виде
            assert "answer_key" not in pv and "rubric" not in pv and "checks" not in json.dumps(pv["meta"])
    assert not bad_leak, bad_leak[:10]
    assert not bad_grade, bad_grade[:10]


def test_public_incident_strips_effects_recursively():
    inc = {"title": "Пул соединений", "actions": [
        {"id": "a1", "text": "Перезапустить", "sim_effect": "recovered", "helpful": True},
        {"id": "a2", "text": "Увеличить пул", "opt_score": 3, "nested": {"trap": True, "label": "x"}}]}
    pub = public_incident(inc)
    s = json.dumps(pub, ensure_ascii=False)
    for k in ("sim_effect", "helpful", "opt_score", "trap", "recovered"):
        assert k not in s
    assert pub["actions"][1]["nested"] == {"label": "x"}


def test_retired_lp_v2_not_in_live_pool():
    assert not [f for f in FIDS if "_v2." in f]
