"""Offline checks for optional per-vacancy persistence; no network or credentials."""
import importlib.util
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("bench_needs_under_test", HERE / "bench_needs.py")
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)


class PredictionExportTest(unittest.TestCase):
    def setUp(self):
        self.row = json.loads((bench.ROOT / "docs/realdata/vacancies_50.json").read_text())["vacancies"][0]
        self.req = json.loads((bench.ROOT / "docs/realdata/rules_predictions.json").read_text())[0]
        self.out = [{
            "id": self.row["id"], "ok": True, "error": None, "latency_ms": 42,
            "requirements": self.req, "llm_only": self.req,
            "call_settings": {"func": "parse_need", "max_tokens": 2500},
        }]

    def test_export_preserves_tags_requirements_and_grounding(self):
        with TemporaryDirectory() as tmp, patch.object(bench.llm, "reasoning_for", return_value="low"):
            target = Path(tmp) / "predictions.json"
            bench.save_predictions(target, "openrouter", "anthropic/claude-sonnet-5.5", [self.row], self.out)
            result = json.loads(target.read_text())
        self.assertEqual(result["reasoning"], "low")
        row = result["per_text"][0]
        self.assertEqual(row["id"], self.row["id"])
        self.assertEqual(row["text_sha256"], self.row["text_sha256"])
        self.assertEqual(row["stack_required"], [i["tag"] for i in self.req["stack_required"]])
        self.assertEqual(row["stack_desired"], [i["tag"] for i in self.req["stack_desired"]])
        self.assertEqual(row["requirements"], self.req)
        self.assertEqual(row["call_settings"]["max_tokens"], 2500)

    def test_export_does_not_serialize_environment_secrets(self):
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {"OPENROUTER_API_KEY": "never-save-test-token"}):
            target = Path(tmp) / "predictions.json"
            bench.save_predictions(target, "openrouter", "test-model", [self.row], self.out)
            content = target.read_text()
        self.assertNotIn("never-save-test-token", content)
        self.assertNotIn("OPENROUTER_API_KEY", content)
        self.assertNotIn("Authorization", content)

    def test_run_model_records_settings_and_exports_once(self):
        calls = []

        def fake_parse(text):
            calls.append(text)
            bench._tl.res = SimpleNamespace(ok=True, data={}, error=None, latency_ms=42, usage={})
            bench._tl.call_kwargs = {"func": "parse_need", "max_tokens": 2500}
            return self.req

        with TemporaryDirectory() as tmp, patch.object(bench.NP, "parse_need", side_effect=fake_parse), \
                patch.object(bench.NP, "_llm_requirements", return_value=(self.req, [])), \
                patch.object(bench.NP, "normalize", return_value=self.req), \
                patch.object(bench.NP, "_with_quotes_from_original", return_value=self.req), \
                patch.object(bench.llm, "reasoning_for", return_value="low"):
            target = Path(tmp) / "predictions.json"
            result = bench.run_model("openrouter=test-model", [self.row], 1, target)
            recorded = json.loads(target.read_text())
        self.assertEqual(len(calls), 1)
        self.assertEqual(result["calls"], 1)
        self.assertEqual(result["ok"], 1)
        self.assertEqual(recorded["per_text"][0]["call_settings"]["max_tokens"], 2500)
        self.assertEqual(set(result["per_text"][0]), {"id", "ok", "error", "latency_ms"})


if __name__ == "__main__":
    unittest.main()
