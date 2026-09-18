"""Export the FastAPI contract deterministically from the real application."""

import json
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_ROOT))

from app.main import app  # noqa: E402


def main() -> None:
    output = API_ROOT / "openapi.json"
    document = json.dumps(app.openapi(), indent=2, sort_keys=True, ensure_ascii=False)
    output.write_text(f"{document}\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
