"""Unit tests for ci_lint (yaml_subset, rules, and CLI)."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from ci_lint.cli import format_json, format_table, main
from ci_lint.rules import detect_platform, lint_content
from ci_lint.yaml_subset import YamlParseError, load_yaml_subset


class TestYamlSubset(unittest.TestCase):
    def test_empty_document(self) -> None:
        self.assertEqual(load_yaml_subset(""), {})
        self.assertEqual(load_yaml_subset("# comment only\n   \n"), {})

    def test_scalars_and_types(self) -> None:
        doc = "a: 42\nb: 3.14\nc: true\nd: false\ne: null\nf: 'hello'\ng: \"world\"\n"
        parsed = load_yaml_subset(doc)
        self.assertEqual(parsed["a"], 42)
        self.assertEqual(parsed["b"], 3.14)
        self.assertIs(parsed["c"], True)
        self.assertIs(parsed["d"], False)
        self.assertIsNone(parsed["e"])
        self.assertEqual(parsed["f"], "hello")
        self.assertEqual(parsed["g"], "world")

    def test_nested_dicts_and_lists(self) -> None:
        doc = (
            "stages:\n"
            "  - build\n"
            "  - test\n"
            "job:\n"
            "  script:\n"
            "    - echo ok\n"
        )
        parsed = load_yaml_subset(doc)
        self.assertEqual(parsed["stages"], ["build", "test"])
        self.assertEqual(parsed["job"]["script"], ["echo ok"])

    def test_inline_list_and_dict(self) -> None:
        doc = "tags: [docker, linux]\nmeta: {env: prod, retries: 2}\n"
        parsed = load_yaml_subset(doc)
        self.assertEqual(parsed["tags"], ["docker", "linux"])
        self.assertEqual(parsed["meta"], {"env": "prod", "retries": 2})

    def test_multiline_scalar_pipe(self) -> None:
        doc = "script: |\n  echo one\n  echo two\n"
        parsed = load_yaml_subset(doc)
        self.assertEqual(parsed["script"], "echo one\necho two")

    def test_list_of_dicts(self) -> None:
        doc = "steps:\n  - step:\n      name: Build\n      script:\n        - make\n"
        parsed = load_yaml_subset(doc)
        self.assertEqual(parsed["steps"][0]["step"]["name"], "Build")

    def test_invalid_indentation_raises(self) -> None:
        with self.assertRaises(YamlParseError):
            load_yaml_subset("a: 1\n  b: 2\n")


class TestRulesGitLab(unittest.TestCase):
    def test_detect_platform_by_filename(self) -> None:
        self.assertEqual(detect_platform(".gitlab-ci.yml", {}), "gitlab")
        self.assertEqual(detect_platform("bitbucket-pipelines.yml", {}), "bitbucket")

    def test_detect_platform_by_content(self) -> None:
        self.assertEqual(detect_platform(None, {"pipelines": {}}), "bitbucket")
        self.assertEqual(detect_platform(None, {"stages": ["test"]}), "gitlab")

    def test_ci001_gitlab_pat_detected(self) -> None:
        yml = "variables:\n  TOKEN: glpat-abcdefghijkl123456\n"
        rules = [f.rule_id for f in lint_content(yml, platform="gitlab")]
        self.assertIn("CI001", rules)

    def test_ci001_aws_key_detected(self) -> None:
        yml = "variables:\n  AWS_ACCESS_KEY_ID: AKIAIOSFODNN7EXAMPLE\n"
        rules = [f.rule_id for f in lint_content(yml, platform="gitlab")]
        self.assertIn("CI001", rules)

    def test_ci001_var_reference_not_flagged(self) -> None:
        yml = "variables:\n  API_TOKEN: $CI_JOB_TOKEN\n"
        rules = [f.rule_id for f in lint_content(yml, platform="gitlab")]
        self.assertNotIn("CI001", rules)

    def test_ci002_latest_image_flagged(self) -> None:
        yml = "image: python:latest\n"
        rules = [f.rule_id for f in lint_content(yml, platform="gitlab")]
        self.assertIn("CI002", rules)

    def test_ci002_untagged_image_flagged(self) -> None:
        yml = "image: alpine\n"
        rules = [f.rule_id for f in lint_content(yml, platform="gitlab")]
        self.assertIn("CI002", rules)

    def test_ci002_pinned_image_ok(self) -> None:
        yml = "image: python:3.11-slim\n"
        rules = [f.rule_id for f in lint_content(yml, platform="gitlab")]
        self.assertNotIn("CI002", rules)

    def test_ci002_digest_image_ok(self) -> None:
        yml = "image: python@sha256:abcdef123456\n"
        rules = [f.rule_id for f in lint_content(yml, platform="gitlab")]
        self.assertNotIn("CI002", rules)

    def test_ci003_dind_without_tls(self) -> None:
        yml = "variables:\n  DOCKER_TLS_CERTDIR: \"\"\nservices:\n  - docker:dind\n"
        rules = [f.rule_id for f in lint_content(yml, platform="gitlab")]
        self.assertIn("CI003", rules)

    def test_ci003_dind_with_tls_ok(self) -> None:
        yml = "variables:\n  DOCKER_TLS_CERTDIR: \"/certs\"\nservices:\n  - docker:24.0-dind\n"
        rules = [f.rule_id for f in lint_content(yml, platform="gitlab")]
        self.assertNotIn("CI003", rules)

    def test_ci004_curl_pipe_sh(self) -> None:
        yml = "build:\n  script:\n    - curl -fsSL https://x.test/i.sh | sh\n"
        rules = [f.rule_id for f in lint_content(yml, platform="gitlab")]
        self.assertIn("CI004", rules)

    def test_ci004_wget_pipe_bash(self) -> None:
        yml = "build:\n  script:\n    - wget -qO- https://x.test/i.sh | bash\n"
        rules = [f.rule_id for f in lint_content(yml, platform="gitlab")]
        self.assertIn("CI004", rules)

    def test_ci005_missing_timeout(self) -> None:
        yml = "test_job:\n  script:\n    - pytest\n"
        rules = [f.rule_id for f in lint_content(yml, platform="gitlab")]
        self.assertIn("CI005", rules)

    def test_ci005_with_timeout_ok(self) -> None:
        yml = "test_job:\n  timeout: 15m\n  script:\n    - pytest\n"
        rules = [f.rule_id for f in lint_content(yml, platform="gitlab")]
        self.assertNotIn("CI005", rules)

    def test_ci006_artifacts_without_expire_in(self) -> None:
        yml = "build:\n  timeout: 10m\n  artifacts:\n    paths:\n      - dist/\n"
        rules = [f.rule_id for f in lint_content(yml, platform="gitlab")]
        self.assertIn("CI006", rules)

    def test_ci007_missing_cache(self) -> None:
        yml = "build:\n  timeout: 10m\n  script:\n    - echo hi\n"
        rules = [f.rule_id for f in lint_content(yml, platform="gitlab")]
        self.assertIn("CI007", rules)

    def test_ci008_unquoted_commit_message(self) -> None:
        yml = "build:\n  script:\n    - echo $CI_COMMIT_MESSAGE\n"
        rules = [f.rule_id for f in lint_content(yml, platform="gitlab")]
        self.assertIn("CI008", rules)

    def test_ci008_quoted_commit_message_ok(self) -> None:
        yml = "build:\n  script:\n    - echo \"$CI_COMMIT_MESSAGE\"\n"
        rules = [f.rule_id for f in lint_content(yml, platform="gitlab")]
        self.assertNotIn("CI008", rules)


class TestRulesBitbucket(unittest.TestCase):
    def test_bitbucket_rules_triggered(self) -> None:
        yml = (
            "image: node:latest\n"
            "pipelines:\n"
            "  default:\n"
            "    - step:\n"
            "        name: Build\n"
            "        script:\n"
            "          - curl https://x.test/s.sh | sh\n"
            "          - echo $BITBUCKET_COMMIT_MESSAGE\n"
        )
        findings = lint_content(yml, file_path="bitbucket-pipelines.yml", platform="bitbucket")
        rules = {f.rule_id for f in findings}
        self.assertIn("CI002", rules)
        self.assertIn("CI004", rules)
        self.assertIn("CI005", rules)
        self.assertIn("CI007", rules)
        self.assertIn("CI008", rules)


class TestCLI(unittest.TestCase):
    def test_format_table_empty(self) -> None:
        out = format_table([], file_label="a.yml")
        self.assertIn("No issues found", out)

    def test_format_json_structure(self) -> None:
        findings = lint_content("image: python:latest\n", platform="gitlab")
        parsed = json.loads(format_json(findings, file_label=".gitlab-ci.yml"))
        self.assertEqual(parsed["file"], ".gitlab-ci.yml")
        self.assertEqual(parsed["count"], len(findings))
        self.assertIsInstance(parsed["findings"], list)

    def test_cli_exit_code_1_on_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / ".gitlab-ci.yml"
            p.write_text("image: python:latest\njob:\n  script:\n    - curl https://a.b | sh\n", encoding="utf-8")
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = main([str(p), "--format", "json"])
            self.assertEqual(rc, 1)
            data = json.loads(buf.getvalue())
            self.assertGreaterEqual(data["count"], 1)

    def test_cli_exit_code_0_clean_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / ".gitlab-ci.yml"
            p.write_text(
                "image: python:3.11-slim\ncache:\n  paths:\n    - .cache/\ntest:\n  timeout: 10m\n  script:\n    - pytest\n",
                encoding="utf-8",
            )
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = main([str(p)])
            self.assertEqual(rc, 0)
            self.assertIn("No issues found", buf.getvalue())

    def test_cli_missing_file_returns_2(self) -> None:
        rc = main(["non_existent_ci_file_12345.yml"])
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
