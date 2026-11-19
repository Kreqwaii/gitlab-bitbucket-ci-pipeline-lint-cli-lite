# GitLab & Bitbucket CI Pipeline Lint CLI (Lite)

Zero-dependency offline linter for `.gitlab-ci.yml` and `bitbucket-pipelines.yml` built with pure Python 3.9+ standard library.

## Features (Lite)

- **100% Offline & Zero Dependencies**: Pure Python 3.9+ stdlib (`yaml_subset` parser included).
- **Secret & PAT Detection (`CI001`)**: Catches hardcoded `glpat-`, `ghp_`, `AKIA`, `ATBB`, `xoxb-` tokens and hardcoded sensitive variables (`PASSWORD`, `SECRET`, `TOKEN`, `API_KEY`).
- **Unpinned Docker Images (`CI002`)**: Flags `:latest` or untagged images.
- **`docker:dind` Without TLS (`CI003`)**: Detects `DOCKER_TLS_CERTDIR: ""` or missing TLS configuration.
- **Pipe-to-Shell (`CI004`)**: Flags `curl ... | sh` / `wget ... | bash`.
- **Missing Timeouts (`CI005`)**: Checks for missing `timeout` (GitLab) or `max-time` (Bitbucket).
- **Missing Artifact Expiry (`CI006`)**: Flags `artifacts` without `expire_in` in GitLab CI.
- **Missing Cache (`CI007`)**: Advises when no `cache` / `caches` are configured.
- **Unquoted Commit Variables (`CI008`)**: Detects unquoted `$CI_COMMIT_MESSAGE`, `$CI_COMMIT_TITLE`, `$BITBUCKET_COMMIT_MESSAGE` in scripts.
- **Table & JSON Output**: `--format table` (default) or `--format json`.

## Installation

```bash
pip install .
```

Or run directly without installation:

```bash
python -m ci_lint.cli examples/.gitlab-ci.yml
```

## Usage Examples

```bash
# Lint a GitLab CI file (table output)
ci-lint .gitlab-ci.yml

# Lint a Bitbucket Pipelines file with JSON output
ci-lint bitbucket-pipelines.yml --platform bitbucket --format json

# Fail on warnings as well as errors
ci-lint .gitlab-ci.yml --fail-on warning
```

## Lite vs Pro Comparison

| Feature | Lite (Open Source) | Pro |
| :--- | :---: | :---: |
| Offline `.gitlab-ci.yml` & `bitbucket-pipelines.yml` lint | Yes | Yes |
| Secrets, `:latest`, `dind` TLS, `curl \| sh`, timeouts, cache | Yes | Yes |
| Table & JSON output | Yes | Yes |
| **DAG Critical Path & Bottleneck Analyzer** | - | **Yes** |
| **Pipeline Version Diff (Semantic YAML Diff)** | - | **Yes** |
| **SARIF & Interactive HTML Reports** | - | **Yes** |
| **Web UI Dashboard** | - | **Yes** |

Get **Pro** here: [https://funpay.com/users/20096179/](https://funpay.com/users/20096179/)

---

## Документация (RU)

Оффлайн-линтер для `.gitlab-ci.yml` и `bitbucket-pipelines.yml` без внешних зависимостей (чистый Python 3.9+ stdlib).

### Что проверяет:
- Утечки секретов и PAT-токенов (`glpat-`, `ghp_`, `AKIA`, `ATBB`, хардкод в `variables`).
- Незафиксированные Docker-образы (`:latest` или без тега).
- `docker:dind` без TLS (`DOCKER_TLS_CERTDIR: ""`).
- Опасные конструкции `curl | sh` / `wget | bash`.
- Отсутствие `timeout` / `max-time`, `expire_in` для артефактов, `cache`.
- Неэкранированные переменные коммита (`$CI_COMMIT_MESSAGE` и др.) в скриптах.

### Запуск:
```bash
python -m ci_lint.cli examples/.gitlab-ci.yml --format table
python -m ci_lint.cli examples/.gitlab-ci.yml --format json
```

В **Pro-версии** доступны: анализ критического пути DAG, семантический diff двух версий пайплайна, экспорт в SARIF/HTML и Web UI — [https://funpay.com/users/20096179/](https://funpay.com/users/20096179/).

## License

MIT
