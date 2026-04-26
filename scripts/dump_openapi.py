"""
Export the auto-generated OpenAPI spec to ``openapi.json`` (UTF-8) so you can
upload it to RapidAPI.

Usage (from the project root):

    py scripts/dump_openapi.py
    # writes ./openapi.json

Or pass an explicit output path:

    py scripts/dump_openapi.py path/to/spec.json

RapidAPI accepts this file in: My APIs → <your API> → Definition → Import.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.main import app  # noqa: E402


def main() -> None:
    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "openapi.json"
    spec = app.openapi()
    out_path.write_text(json.dumps(spec, indent=2, ensure_ascii=False), encoding="utf-8")
    paths = len(spec.get("paths", {}))
    print(
        f"Wrote {out_path} — OpenAPI {spec['openapi']}, "
        f"{spec['info']['title']} v{spec['info']['version']}, {paths} paths"
    )


if __name__ == "__main__":
    main()
