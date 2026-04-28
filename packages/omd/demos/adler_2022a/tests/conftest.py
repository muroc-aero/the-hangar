"""Make the demo directory importable as `sweep`/`retry_failed`/etc."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def pytest_addoption(parser):
    parser.addoption(
        "--paper-rel-tol",
        action="store",
        default="0.20",
        help="Relative tolerance for paper-vs-reproduced parity tests "
             "(default 0.20 = smoke mesh; use 0.05 for paper-spec mesh).",
    )
