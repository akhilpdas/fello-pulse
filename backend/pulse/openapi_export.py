"""Write the application's OpenAPI schema to specs/.../contracts/openapi.yaml.

    python3 -m pulse.openapi_export
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from pulse.api.main import app

OPENAPI_PATH = (Path(__file__).resolve().parents[2]
                / "specs" / "001-renewal-risk-prioritisation" / "contracts" / "openapi.yaml")


def main() -> None:
    OPENAPI_PATH.write_text(yaml.safe_dump(json.loads(json.dumps(app.openapi())), sort_keys=False))
    print(f"wrote {OPENAPI_PATH}")


if __name__ == "__main__":
    main()
