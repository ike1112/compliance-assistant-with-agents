# The container artifact for the AgentCore Runtime host. `server` is the
# AgentCore HTTP service-contract shim; it is the deploy-time image's
# entry module and is unit-tested offline. Importable as `runtime.server`
# (infra/ is on sys.path via infra/conftest.py; /app in the image).
