import sys
from pathlib import Path

# Make the project root importable as `app.*` regardless of where pytest is invoked.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
