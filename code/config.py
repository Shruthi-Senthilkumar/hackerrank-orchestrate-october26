"""Non-secret configuration for the Ghost Data Still Exists pipeline.

No API keys live here. Keys are read from environment variables (.env) only,
in code/audit/llm/client.py (Phase 4), never in this file.

Model IDs actually called so far (see log.txt and DECISIONS.md D1, D2, D10):
qwen/qwen3.8-27b (Groq, intent), gemini-3.8-flash (Gemini, ad hoc smoke
test only), gemini-3.1-flash-lite (Gemini, ad hoc smoke test only). The
PRD's original intent models (qwen/qwen3-32b and the comparison candidate
qwen/qwen3.6-27b) do not exist on this Groq key; the user chose
qwen/qwen3.8-27b as the replacement and rejected any second Groq model
(D10), so there is no INTENT_MODEL_FALLBACK. gemini-3.1-flash-lite is the
primary vision reader (fast, large daily budget); gemini-3.8-flash is used
rarely and only within its small daily budget (D2, D9, D11).
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATASET_DIR = REPO_ROOT / "dataset"
EVIDENCE_DIR = DATASET_DIR / "evidence"
CACHE_DIR = REPO_ROOT / ".cache"
OUTPUT_PATH = REPO_ROOT / "output.csv"

# --- Model IDs: confirmed against the live Groq / Gemini accounts (Phase 0) ---
INTENT_MODEL = "qwen/qwen3.8-27b"  # user-confirmed replacement for qwen/qwen3-32b (not available)
EXTRACT_MODEL = "gemini-3.1-flash-lite"  # Gemini primary image/PDF reader (D2, D11)
EXTRACT_MODEL_RARE = "gemini-3.8-flash"  # Gemini second reader, rare and budgeted (D2, D9, D11)

# --- Rate limits and batching ---
# Groq qwen/qwen3.8-27b, from Groq's official rate-limits docs (console-confirmed
# numbers pending; the docs table does not say which plan it describes).
GROQ_REQUESTS_PER_MINUTE = 30
GROQ_TOKENS_PER_MINUTE = 8000
GROQ_REQUESTS_PER_DAY = 1000
GROQ_TOKENS_PER_DAY = 200000

# Gemini: RPM/TPM unknown for both models; conservative placeholders, TODO-VERIFY
# in aistudio.google.com. Per-day request budgets are NOT official (Google's docs
# page no longer publishes free-tier figures); these come from third-party reports
# and a Google AI forum thread (see DECISIONS.md D9), TODO-VERIFY in AI Studio.
GEMINI_REQUESTS_PER_MINUTE = 10  # TODO-VERIFY in aistudio.google.com
GEMINI_TOKENS_PER_MINUTE = 100000  # TODO-VERIFY in aistudio.google.com
GEMINI_FLASH_LITE_REQUESTS_PER_DAY = 500  # TODO-VERIFY in aistudio.google.com
GEMINI_FLASH_REQUESTS_PER_DAY = 20  # TODO-VERIFY in aistudio.google.com

INTENT_BATCH_SIZE = 8  # TODO-VERIFY: tune once rate limits are confirmed
MAX_TOKENS_PER_CALL = 2000  # TODO-VERIFY: hard budget guard

PROMPT_VERSION = "v0"  # bumped whenever a prompt file changes
