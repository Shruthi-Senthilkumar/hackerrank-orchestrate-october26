"""Print only whether required API keys are present, never their values.

Usage: python code/tools/check_keys.py
"""

import os
from pathlib import Path

from dotenv import load_dotenv

REQUIRED_KEYS = ["GROQ_API_KEY", "GEMINI_API_KEY"]


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent.parent
    load_dotenv(repo_root / ".env")

    all_set = True
    for key in REQUIRED_KEYS:
        value = os.environ.get(key, "")
        status = "set" if value.strip() else "missing"
        if status == "missing":
            all_set = False
        print(f"{key}: {status}")

    return 0 if all_set else 1


if __name__ == "__main__":
    raise SystemExit(main())
