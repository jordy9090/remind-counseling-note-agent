"""Safety contracts for the disposable runner; no database or Docker calls."""
import importlib.util
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


RUNNER = Path(__file__).resolve().parents[1] / "run_poc_database.py"
sys.path.insert(0, str(RUNNER.parent))
spec = importlib.util.spec_from_file_location("poc_database_runner", RUNNER)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class RunnerSafetyTests(unittest.TestCase):
    def test_credentials_and_remote_docker_configuration_are_not_inherited(self):
        with patch.dict(os.environ, {"PGHOST": "remote.invalid", "PGPASSWORD": "synthetic",
            "DOCKER_HOST": "tcp://remote.invalid:2375", "DOCKER_CONTEXT": "remote",
            "SUPABASE_URL": "https://remote.invalid", "OPENAI_API_KEY": "synthetic",
            "HTTPS_PROXY": "https://remote.invalid"}):
            env = runner.clean_environment("synthetic-scratch")
        for name in ("PGHOST", "PGPASSWORD", "DOCKER_HOST", "DOCKER_CONTEXT", "SUPABASE_URL", "OPENAI_API_KEY", "HTTPS_PROXY"):
            self.assertNotIn(name, env)
        self.assertEqual("synthetic-scratch", env["DOCKER_CONFIG"])
        self.assertEqual(["docker", "--host=unix:///var/run/docker.sock"], runner.DOCKER)

    def test_preflight_accepts_only_the_empty_marked_fixture(self):
        valid = {"database": runner.DATABASE, "user": runner.ADMIN, "marker": runner.MARKER,
                 "version": 150020, "user_tables": 0, "custom_schemas": 0, "fixture_roles": 0}
        runner.verify_preflight(valid)
        for key, bad in (("database", "postgres"), ("user", "postgres"), ("marker", None),
                         ("version", 160000), ("user_tables", 1), ("custom_schemas", 1), ("fixture_roles", 1)):
            with self.subTest(field=key), self.assertRaises(RuntimeError):
                runner.verify_preflight({**valid, key: bad})

    def test_no_endpoint_or_existing_container_arguments_are_accepted(self):
        for option in ("--host", "--port", "--database-url", "--container", "--psql", "--project-ref"):
            with self.subTest(option=option), patch("sys.argv", [str(RUNNER), "--static", option, "synthetic"]), \
                    patch.object(runner, "run_disposable") as start, patch("sys.stderr"), self.assertRaises(SystemExit) as rejected:
                runner.main()
            self.assertEqual(2, rejected.exception.code)
            start.assert_not_called()

    def test_forged_parent_probes_are_negative_and_transactional(self):
        sql = runner.build_sql()
        self.assertTrue(sql.startswith("begin;"))
        self.assertTrue(sql.endswith("rollback;\n"))
        for table in runner.TABLES:
            if table not in {"cases", "counseling_drafts", "document_exports", "retrieval_logs"}:
                self.assertIn(f"A:{table}:forged_case_insert", sql)
                self.assertIn(f"B:{table}:forged_case_update", sql)
        helper = (runner.PACK / "assertions.sql").read_text(encoding="utf-8")
        self.assertIn("errcode = 'P9001'", helper, "Successful attacks must roll back before recording failure")
        self.assertNotIn("security definer", helper.lower())

    def test_permission_matrix_covers_each_table_and_privileged_entry(self):
        sql = runner.build_permission_sql()
        self.assertTrue(sql.startswith("begin;"))
        self.assertTrue(sql.endswith("rollback;\n"))
        for table in runner.TABLES:
            for status in ("missing", "withdrawn", "expired", "wrong_policy", "wrong_provider", "generation_only", "policy_missing", "policy_replaced", "beta_withdrawn"):
                for action in ("select", "update", "delete", "insert"):
                    self.assertIn(f"{status}:{table}:{action}", sql)
            for role in ("anon", "service_role"):
                self.assertIn(f"{role}:{table}:select", sql)
        self.assertIn("private_body:processing_authorization.check_permission_unlocked", sql)


if __name__ == "__main__":
    unittest.main()
