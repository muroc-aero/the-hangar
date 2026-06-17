"""Put the example root on sys.path so ``oracle`` imports in the parity tests."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
