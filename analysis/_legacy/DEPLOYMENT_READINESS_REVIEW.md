# Deployment Readiness Review

## Verdict

This project is not deployment-ready yet. It is a useful local sample, but several deployment, security, reproducibility, and operational gaps should be addressed before it is used in a real environment.

## Findings

### High: `.env` is present but not ignored

`.gitignore` ignores `.venv`, `uv.lock`, and `report.md`, but it does not ignore `.env`.

The current `.env` contains placeholders, but in a deployment workflow this creates a high risk of accidentally committing Bedrock, AWS, or other sensitive configuration values.

Recommended fix:

- Add `.env` to `.gitignore`.
- Add a safe `.env.example` file with placeholder values.
- Ensure real secrets and deployment-specific values are supplied by the deployment environment or secret manager.

### High: runtime configuration is not validated enough

`src/compliance_assistant/main.py` only checks that `TOPIC` exists.

`src/compliance_assistant/crew.py` initializes `BedrockInvokeAgentTool` with `AGENT_ID` and `AGENT_ALIAS_ID`, but does not validate whether those values are missing, empty, or still set to placeholder strings.

This means the application can start with invalid configuration and fail later during a Bedrock agent invocation.

Recommended fix:

- Validate all required environment variables at startup.
- Fail fast with clear error messages.
- Reject placeholder values such as `replace-with-your-amazon-bedrock-Agent-id`.

### High: `.env` loading is ambiguous

The README instructs users to define values in `.env`, but the application does not explicitly load `.env`.

The console scripts in `pyproject.toml` call `compliance_assistant.main:run`. Unless the launcher loads `.env`, `main.py` will not see those values.

Recommended fix:

- Either document that `crewai run` loads `.env` and make that the only supported launch path, or add explicit `.env` loading with `python-dotenv`.
- Prefer explicit startup behavior for deployment.

### High: dependencies are not reproducible

`pyproject.toml` uses broad dependency ranges:

```toml
dependencies = [
    "bandit>=1.8.3",
    "boto3>=1.37.6",
    "crewai[tools]>=0.105.0,<1.0.0"
]
```

At the same time, `.gitignore` ignores `uv.lock`.

This means production installs may receive different package versions over time, which is especially risky for CrewAI and tool integrations.

Recommended fix:

- Commit `uv.lock` or another lockfile.
- Build deployments from the lockfile.
- Consider separating runtime dependencies from development/security tools such as `bandit`.

### Medium: no deployment artifact or operational wrapper

I found no Dockerfile, Docker Compose file, Procfile, service definition, CI workflow, Terraform, CDK, CloudFormation, Kubernetes manifest, health check, logging config, or runtime environment contract.

The current project is a local CLI sample, not a deployable service.

Recommended fix:

- Decide the deployment target.
- Add the appropriate deployment artifact.
- Define required environment variables, IAM permissions, region, model access, output handling, and operational run commands.

### Medium: no tests

There are no unit or integration tests in the repository.

The Python source files parse successfully, but I could not run the actual application because `crewai` and `crewai_tools` are not installed in this environment.

Recommended fix:

- Add unit tests for configuration validation.
- Add smoke tests for crew construction.
- Add an integration test path that can be run against a configured Bedrock test environment.

### Medium: production logs may expose sensitive compliance context

All agents and the crew are configured with `verbose=True`.

For compliance workloads, verbose traces may expose prompts, retrieved policy content, regulatory analysis, generated recommendations, or other sensitive internal context.

Recommended fix:

- Disable verbose logging by default in production.
- Make verbosity controlled by an environment variable.
- Redact sensitive values before logging.

### Medium: compliance output lacks evidence requirements

The task configuration asks agents to find current regulatory information, but the expected outputs do not require citations, source dates, confidence levels, assumptions, or human-review flags.

That is risky for a compliance assistant because users may treat generated output as authoritative.

Recommended fix:

- Require citations and source dates in task outputs.
- Require explicit assumptions and uncertainty notes.
- Add a human-review disclaimer or review workflow before using generated recommendations operationally.

## Checks Performed

- Reviewed repository structure.
- Reviewed `README.md`.
- Reviewed `pyproject.toml`.
- Reviewed `src/compliance_assistant/main.py`.
- Reviewed `src/compliance_assistant/crew.py`.
- Reviewed `src/compliance_assistant/config/agents.yaml`.
- Reviewed `src/compliance_assistant/config/tasks.yaml`.
- Reviewed `.gitignore`.
- Reviewed `.env` contents.
- Ran a Python AST parse check successfully.
- Checked local dependency availability.

## Local Environment Notes

The current folder is not a Git repository, so I could not verify tracked versus untracked files.

Installed dependency check results:

- `boto3`: installed
- `crewai`: not installed
- `crewai_tools`: not installed
- `bandit`: not installed

Python version:

- Python 3.12.8

## Minimum Work Before Deployment

Before deploying, address at least the following:

1. Add `.env` to `.gitignore`.
2. Add `.env.example`.
3. Validate all required runtime configuration at startup.
4. Commit and deploy from a lockfile.
5. Add unit and smoke tests.
6. Add a deployment artifact for the chosen platform.
7. Disable or gate verbose logging.
8. Require citations, source dates, assumptions, and human review in compliance outputs.
9. Document required AWS IAM permissions, Bedrock model access, region configuration, and Bedrock agent setup.

