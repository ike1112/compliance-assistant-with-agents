"""review_gate is not pip-installed (it is tooling, not the product wheel),
so make the repo root importable for these tests explicitly."""
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))