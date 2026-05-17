# AgentCore Runtime container for the compliance crew.
#
# AgentCore Runtime requires linux/arm64 images; the platform is pinned
# explicitly so a build on an amd64 host still produces a runnable image.
# The image serves the AgentCore HTTP service contract on port 8080
# (runtime/server.py: /ping, /invocations, /status). Built and pushed by
# the operator at the HUMAN-GATE — never built during `cdk synth`.
FROM --platform=linux/arm64 python:3.12-slim

WORKDIR /app

# Install the crew from its own project metadata so the runtime closure
# is exactly the crew's deps (boto3 included) — no CDK toolchain, no
# extra runtime dependency for the shim itself.
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .

# The async service-contract shim. `runtime` is a top-level package in
# the image (WORKDIR /app is on sys.path), matching how the offline test
# imports `runtime.server`.
COPY infra/runtime ./runtime

EXPOSE 8080
CMD ["python", "-m", "runtime.server"]
