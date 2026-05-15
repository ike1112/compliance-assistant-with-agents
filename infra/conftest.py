# Makes `stacks` importable when pytest runs from the repo root.
# pytest prepends the directory containing this conftest to sys.path,
# which matches how `cdk` runs `app.py` from inside infra/.
