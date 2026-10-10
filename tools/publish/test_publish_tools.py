"""Тесты инструментов подготовки публикации (tools/publish): python3 -m unittest discover -s tools/publish -p 'test_*.py'."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))

import gen_numbers  # noqa: E402


def run(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, *args], cwd=cwd, capture_output=True, text=True)


def make_repo(files: dict[str, str]) -> Path:
    d = Path(tempfile.mkdtemp(prefix="pubtools_"))
    subprocess.run(["git", "init", "-q", str(d)], check=True)
    for name, text in files.items():
        (d / name).parent.mkdir(parents=True, exist_ok=True)
        (d / name).write_text(text, encoding="utf-8")
    subprocess.run(["git", "-C", str(d), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(d), "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "t"], check=True)
    return d


class CheckPublicTree(unittest.TestCase):
    def test_clean_tree_passes(self) -> None:
        d = make_repo({"README.md": "Обычный текст\n", "a.py": "print(1)\n"})
        r = run(str(HERE / "check_public_tree.py"), "--repo", str(d))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_internal_markers_found(self) -> None:
        d = make_repo({"x.md": "см. /home/user/workspace/x\n", "y.md": "отчёт reports_0910/a.md\n", "z.md": "решение штаба\n"})
        r = run(str(HERE / "check_public_tree.py"), "--repo", str(d))
        self.assertEqual(r.returncode, 1)
        self.assertIn("x.md:1", r.stdout)
        self.assertIn("y.md:1", r.stdout)
        self.assertIn("z.md:1", r.stdout)

    def test_value_from_file_found_without_printing_it(self) -> None:
        secret = "Zq9-test-value-123456"
        d = make_repo({"cfg.txt": f"token={secret}\n"})
        vf = d / "values.txt"
        vf.write_text(json.dumps({"v": secret, "src": "test"}) + "\n", encoding="utf-8")
        r = run(str(HERE / "check_public_tree.py"), "--repo", str(d), "--values", str(vf))
        self.assertEqual(r.returncode, 1)
        self.assertNotIn(secret, r.stdout + r.stderr)

    def test_public_ip_found_private_ignored(self) -> None:
        d = make_repo({"a.md": "сервер 203.0.113.9 и 8.8.8.8 и 93.184.216.34\n"})
        r = run(str(HERE / "check_public_tree.py"), "--repo", str(d))
        self.assertEqual(r.returncode, 1)
        self.assertIn("нарушений: 1", r.stdout)  # только 93.184.216.34; частные, документационные и 8.8.8.8 не считаются


class ScanHistoryValues(unittest.TestCase):
    def test_found_in_old_version_and_never_printed(self) -> None:
        secret = "Qw8-hist-value-654321"
        d = make_repo({"f.txt": f"{secret}\n"})
        (d / "f.txt").write_text("пусто\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(d), "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-qam", "убрали"], check=True)
        vf = d.parent / (d.name + "_values.txt")
        vf.write_text(json.dumps({"v": secret, "src": "test"}) + "\n", encoding="utf-8")
        r = run(str(HERE / "scan_history_values.py"), "--values", str(vf), "--repo", str(d), "--all")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertNotIn(secret, r.stdout + r.stderr)

    def test_absent_value_passes(self) -> None:
        d = make_repo({"f.txt": "ничего\n"})
        vf = d.parent / (d.name + "_values.txt")
        vf.write_text(json.dumps({"v": "NoSuchValue-777777", "src": "test"}) + "\n", encoding="utf-8")
        r = run(str(HERE / "scan_history_values.py"), "--values", str(vf), "--repo", str(d), "--all")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


class Numbers(unittest.TestCase):
    def test_replace_block_is_idempotent_and_keeps_text(self) -> None:
        t = "до\n<!-- numbers:begin -->\nстарое\n<!-- numbers:end -->\nпосле\n"
        a, found = gen_numbers.replace_block(t, "numbers", "новое")
        b, _ = gen_numbers.replace_block(a, "numbers", "новое")
        self.assertTrue(found)
        self.assertEqual(a, b)
        self.assertIn("до\n", a)
        self.assertIn("после\n", a)
        self.assertIn("новое", a)

    def test_parse_log(self) -> None:
        p = Path(tempfile.mkdtemp()) / "pytest.log"
        p.write_text("....\nRequired test coverage of 80.0% reached. Total coverage: 91.88%\n1222 passed, 2 skipped, 9 warnings in 321.76s (0:05:21)\nEXIT=0\n", encoding="utf-8")
        r = gen_numbers.parse_log(p)
        self.assertEqual((r["passed"], r["skipped"], r["failed"], r["coverage_pct"], r["exit"]), (1222, 2, 0, 91.9, 0))

    def test_repo_numbers_in_sync(self) -> None:
        r = run(str(HERE / "gen_numbers.py"), "--check", cwd=ROOT)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_limits_match_compose(self) -> None:
        n = gen_numbers.static_numbers()
        self.assertEqual(n["memory_limits_mib"]["api"], 1536)
        self.assertEqual(len(n["migrations"]["heads"]), 1)


class ThirdParty(unittest.TestCase):
    def test_third_party_in_sync(self) -> None:
        r = run(str(HERE / "gen_third_party.py"), "--check", cwd=ROOT)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

class ServerEnvValues(unittest.TestCase):
    ENV = ("##FILE secrets/llm.env\nLLM_API_KEY=abcDEF123456\nLLM_BASE_URL=https://api.example.invalid/v1\nLLM_MODEL=short\n"
           "##FILE app/.env\n# комментарий\nJWT_SECRET=\nPOSTGRES_PASSWORD=pg-пароль-1234\nVAPID_PUBLIC_KEY=pubpubpubpub\nAPP_PORT=8141\n"
           "##FILE secrets/stand.pw\nstand-pass-777\n")

    def test_parse_takes_secret_keys_only(self) -> None:
        sys.path.insert(0, str(HERE))
        import server_env_values as sev

        got = sev.parse(self.ENV)
        self.assertEqual(set(got), {"abcDEF123456", "pg-пароль-1234", "stand-pass-777"})
        self.assertEqual(got["abcDEF123456"], "server:secrets/llm.env:LLM_API_KEY")
        self.assertEqual(got["stand-pass-777"], "server:secrets/stand.pw")
        variants = sev.with_variants(got)
        self.assertGreater(len(variants), len(got))  # URL, JSON и Basic-варианты
        self.assertTrue(any(src.endswith("+basic") for src in variants.values()))

    def test_stdout_is_json_lines_and_terminal_is_refused(self) -> None:
        r = subprocess.run([sys.executable, str(HERE / "server_env_values.py")], input=self.ENV, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        rows = [json.loads(x) for x in r.stdout.splitlines()]
        self.assertTrue(all({"v", "src"} <= set(x) for x in rows))
        self.assertNotIn("abcDEF123456", r.stderr)  # значения не попадают в сообщения
        empty = subprocess.run([sys.executable, str(HERE / "server_env_values.py")], input="нет значений\n", capture_output=True, text=True)
        self.assertEqual(empty.returncode, 2)


if __name__ == "__main__":
    unittest.main()
