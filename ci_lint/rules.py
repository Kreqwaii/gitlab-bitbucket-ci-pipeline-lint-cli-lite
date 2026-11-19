"""Linting rules for GitLab CI (.gitlab-ci.yml) and Bitbucket Pipelines (bitbucket-pipelines.yml)."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from .yaml_subset import load_yaml_subset

SEVERITY_ORDER = {"error": 3, "warning": 2, "info": 1}

SECRET_TOKEN_PATTERNS = [
    ("GitLab PAT", re.compile(r"glpat-[A-Za-z0-9_\-]{12,}")),
    ("GitHub PAT", re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}")),
    ("AWS Access Key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("Bitbucket App Password", re.compile(r"ATBB[A-Za-z0-9]{16,}")),
    ("Slack Token", re.compile(r"xox[baprs]-[A-Za-z0-9\-]{10,}")),
]

SENSITIVE_VAR_NAME = re.compile(
    r"(PASSWORD|PASSWD|SECRET|TOKEN|API_KEY|PRIVATE_KEY|ACCESS_KEY)", re.IGNORECASE
)

PIPE_TO_SHELL_RE = re.compile(
    r"\b(curl|wget)\b[^|\n]*\|\s*(sudo\s+)?(sh|bash|zsh|ash)\b", re.IGNORECASE
)

COMMIT_VAR_RE = re.compile(
    r"\$\{?(CI_COMMIT_MESSAGE|CI_COMMIT_TITLE|CI_COMMIT_DESCRIPTION|BITBUCKET_COMMIT_MESSAGE)\}?"
)

GITLAB_RESERVED_TOP_KEYS = {
    "stages",
    "variables",
    "image",
    "services",
    "before_script",
    "after_script",
    "cache",
    "include",
    "default",
    "workflow",
    "pages",
}


@dataclass
class Finding:
    rule_id: str
    severity: str
    message: str
    location: str
    line: Optional[int] = None
    platform: str = "generic"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def detect_platform(file_path: Optional[str], data: Any) -> str:
    if file_path:
        name = Path(file_path).name.lower()
        if "bitbucket" in name:
            return "bitbucket"
        if "gitlab" in name:
            return "gitlab"
    if isinstance(data, dict):
        if "pipelines" in data:
            return "bitbucket"
        if any(k in data for k in ("stages", "workflow", "before_script", "default")):
            return "gitlab"
    return "gitlab"


def _find_line(raw_lines: List[str], needle: str) -> Optional[int]:
    for idx, line in enumerate(raw_lines, start=1):
        if needle in line:
            return idx
    return None


def _check_secrets_in_text(
    raw_lines: List[str], platform: str, findings: List[Finding]
) -> None:
    for idx, line in enumerate(raw_lines, start=1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        for label, pattern in SECRET_TOKEN_PATTERNS:
            if pattern.search(line):
                findings.append(
                    Finding(
                        rule_id="CI001",
                        severity="error",
                        message=f"Hardcoded {label} detected.",
                        location=f"line {idx}",
                        line=idx,
                        platform=platform,
                    )
                )


def _check_sensitive_variables(
    variables: Any, location: str, raw_lines: List[str], platform: str, findings: List[Finding]
) -> None:
    if not isinstance(variables, dict):
        return
    for key, val in variables.items():
        if not isinstance(key, str) or not isinstance(val, str):
            continue
        if SENSITIVE_VAR_NAME.search(key):
            trimmed = val.strip()
            if trimmed and not trimmed.startswith("$") and trimmed not in ("", "null"):
                findings.append(
                    Finding(
                        rule_id="CI001",
                        severity="error",
                        message=f"Sensitive variable '{key}' has a hardcoded value instead of CI/CD secret reference.",
                        location=location,
                        line=_find_line(raw_lines, key),
                        platform=platform,
                    )
                )


def _extract_image_name(image_val: Any) -> Optional[str]:
    if isinstance(image_val, str):
        return image_val.strip()
    if isinstance(image_val, dict) and isinstance(image_val.get("name"), str):
        return image_val["name"].strip()
    return None


def _check_docker_image(
    image_val: Any, location: str, raw_lines: List[str], platform: str, findings: List[Finding]
) -> None:
    name = _extract_image_name(image_val)
    if not name or name.startswith("$"):
        return
    if "@sha256:" in name:
        return
    last_segment = name.rsplit("/", 1)[-1]
    if ":" not in last_segment or last_segment.endswith(":latest"):
        findings.append(
            Finding(
                rule_id="CI002",
                severity="warning",
                message=f"Docker image '{name}' is unpinned (uses :latest or no tag). Pin a specific version or digest.",
                location=location,
                line=_find_line(raw_lines, name),
                platform=platform,
            )
        )


def _has_dind_service(services: Any) -> bool:
    if not isinstance(services, list):
        return False
    for svc in services:
        name = _extract_image_name(svc)
        if name and "docker:" in name and "dind" in name:
            return True
    return False


def _check_dind_tls(
    services: Any,
    variables: Any,
    location: str,
    raw_lines: List[str],
    platform: str,
    findings: List[Finding],
) -> None:
    if not _has_dind_service(services):
        return
    tls_dir = None
    if isinstance(variables, dict) and "DOCKER_TLS_CERTDIR" in variables:
        tls_dir = variables["DOCKER_TLS_CERTDIR"]
    if tls_dir is None or str(tls_dir).strip() == "":
        findings.append(
            Finding(
                rule_id="CI003",
                severity="error",
                message="docker:dind service used without TLS (DOCKER_TLS_CERTDIR is empty or unset).",
                location=location,
                line=_find_line(raw_lines, "dind"),
                platform=platform,
            )
        )


def _is_var_quoted(line: str, match_start: int, match_end: int) -> bool:
    before = line[:match_start]
    after = line[match_end:]
    if before.count('"') % 2 == 1 and after.count('"') % 2 == 1:
        return True
    return False


def _check_script_lines(
    script: Any, location: str, raw_lines: List[str], platform: str, findings: List[Finding]
) -> None:
    if isinstance(script, str):
        commands = script.splitlines()
    elif isinstance(script, list):
        commands = [str(item) for item in script if item is not None]
    else:
        return

    for cmd in commands:
        if PIPE_TO_SHELL_RE.search(cmd):
            findings.append(
                Finding(
                    rule_id="CI004",
                    severity="error",
                    message=f"Insecure pipe-to-shell command detected: '{cmd.strip()}'.",
                    location=location,
                    line=_find_line(raw_lines, cmd.strip()[:40]),
                    platform=platform,
                )
            )
        for m in COMMIT_VAR_RE.finditer(cmd):
            if not _is_var_quoted(cmd, m.start(), m.end()):
                findings.append(
                    Finding(
                        rule_id="CI008",
                        severity="error",
                        message=f"Unquoted commit variable '{m.group(0)}' in script can lead to command injection.",
                        location=location,
                        line=_find_line(raw_lines, m.group(0)),
                        platform=platform,
                    )
                )


def _lint_gitlab(
    data: Dict[str, Any], raw_lines: List[str], findings: List[Finding]
) -> None:
    platform = "gitlab"
    global_vars = data.get("variables")
    _check_sensitive_variables(global_vars, "variables", raw_lines, platform, findings)

    if "image" in data:
        _check_docker_image(data["image"], "image", raw_lines, platform, findings)

    default_block = data.get("default") if isinstance(data.get("default"), dict) else {}
    if "image" in default_block:
        _check_docker_image(default_block["image"], "default.image", raw_lines, platform, findings)

    global_services = data.get("services") or default_block.get("services")
    _check_dind_tls(global_services, global_vars, "services", raw_lines, platform, findings)

    for hook in ("before_script", "after_script"):
        if hook in data:
            _check_script_lines(data[hook], hook, raw_lines, platform, findings)
        if hook in default_block:
            _check_script_lines(default_block[hook], f"default.{hook}", raw_lines, platform, findings)

    global_cache = data.get("cache") or default_block.get("cache")
    global_timeout = default_block.get("timeout")
    has_any_cache = global_cache is not None

    for key, val in data.items():
        if key in GITLAB_RESERVED_TOP_KEYS or key.startswith(".") or not isinstance(val, dict):
            continue
        job_name = key
        if "image" in val:
            _check_docker_image(val["image"], f"{job_name}.image", raw_lines, platform, findings)

        job_vars = {}
        if isinstance(global_vars, dict):
            job_vars.update(global_vars)
        if isinstance(val.get("variables"), dict):
            _check_sensitive_variables(
                val["variables"], f"{job_name}.variables", raw_lines, platform, findings
            )
            job_vars.update(val["variables"])

        if "services" in val:
            _check_dind_tls(
                val["services"], job_vars, f"{job_name}.services", raw_lines, platform, findings
            )

        for script_key in ("before_script", "script", "after_script"):
            if script_key in val:
                _check_script_lines(
                    val[script_key], f"{job_name}.{script_key}", raw_lines, platform, findings
                )

        if "timeout" not in val and global_timeout is None:
            findings.append(
                Finding(
                    rule_id="CI005",
                    severity="warning",
                    message=f"Job '{job_name}' has no 'timeout' configured.",
                    location=job_name,
                    line=_find_line(raw_lines, f"{job_name}:"),
                    platform=platform,
                )
            )

        artifacts = val.get("artifacts")
        if isinstance(artifacts, dict) and "expire_in" not in artifacts:
            findings.append(
                Finding(
                    rule_id="CI006",
                    severity="warning",
                    message=f"Job '{job_name}' defines 'artifacts' without 'expire_in'.",
                    location=f"{job_name}.artifacts",
                    line=_find_line(raw_lines, "artifacts:"),
                    platform=platform,
                )
            )

        if "cache" in val:
            has_any_cache = True

    if not has_any_cache:
        findings.append(
            Finding(
                rule_id="CI007",
                severity="info",
                message="Pipeline has no 'cache' configuration; builds may be slower.",
                location="pipeline",
                line=1,
                platform=platform,
            )
        )


def _iter_bitbucket_steps(pipelines: Dict[str, Any]) -> List[tuple[str, Dict[str, Any]]]:
    steps: List[tuple[str, Dict[str, Any]]] = []

    def walk(node: Any, prefix: str) -> None:
        if isinstance(node, list):
            for idx, item in enumerate(node):
                if isinstance(item, dict) and isinstance(item.get("step"), dict):
                    step_name = item["step"].get("name") or f"step[{idx}]"
                    steps.append((f"{prefix}.{step_name}", item["step"]))
                elif isinstance(item, dict) and isinstance(item.get("parallel"), list):
                    walk(item["parallel"], f"{prefix}.parallel[{idx}]")
                elif isinstance(item, dict):
                    walk(item, f"{prefix}[{idx}]")
        elif isinstance(node, dict):
            for k, v in node.items():
                walk(v, f"{prefix}.{k}" if prefix else k)

    walk(pipelines, "pipelines")
    return steps


def _lint_bitbucket(
    data: Dict[str, Any], raw_lines: List[str], findings: List[Finding]
) -> None:
    platform = "bitbucket"
    if "image" in data:
        _check_docker_image(data["image"], "image", raw_lines, platform, findings)

    options = data.get("options") if isinstance(data.get("options"), dict) else {}
    global_max_time = options.get("max-time")
    has_any_cache = False

    pipelines = data.get("pipelines")
    if isinstance(pipelines, dict):
        for loc, step in _iter_bitbucket_steps(pipelines):
            if "image" in step:
                _check_docker_image(step["image"], f"{loc}.image", raw_lines, platform, findings)
            if "script" in step:
                _check_script_lines(step["script"], f"{loc}.script", raw_lines, platform, findings)
            if "after-script" in step:
                _check_script_lines(
                    step["after-script"], f"{loc}.after-script", raw_lines, platform, findings
                )
            if "max-time" not in step and global_max_time is None:
                findings.append(
                    Finding(
                        rule_id="CI005",
                        severity="warning",
                        message=f"Step '{loc}' has no 'max-time' timeout configured.",
                        location=loc,
                        line=_find_line(raw_lines, "step:"),
                        platform=platform,
                    )
                )
            if "caches" in step:
                has_any_cache = True

    if not has_any_cache:
        findings.append(
            Finding(
                rule_id="CI007",
                severity="info",
                message="Bitbucket pipeline has no 'caches' configured.",
                location="pipelines",
                line=1,
                platform=platform,
            )
        )


def lint_content(
    content: str, file_path: Optional[str] = None, platform: str = "auto"
) -> List[Finding]:
    """Lint YAML content and return a list of Findings."""
    raw_lines = content.splitlines()
    data = load_yaml_subset(content)
    resolved_platform = (
        detect_platform(file_path, data) if platform == "auto" else platform
    )

    findings: List[Finding] = []
    _check_secrets_in_text(raw_lines, resolved_platform, findings)

    if isinstance(data, dict):
        if resolved_platform == "bitbucket":
            _lint_bitbucket(data, raw_lines, findings)
        else:
            _lint_gitlab(data, raw_lines, findings)

    return findings
