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
MAX_TOKENS_PER_RUN = 2_000_000  # hard budget guard for one `python code/main.py` run

# --- Phase 4: AI layer limits (D9, D11) ---
LLM_CALL_TIMEOUT_S = 90  # hard per-call timeout
LLM_RETRY_CAP = 1  # at most one retry, with exponential backoff + jitter, on 429/5xx

CACHE_DIR_LLM = CACHE_DIR / "llm_cache"
USAGE_LEDGER_PATH = CACHE_DIR / "usage_ledger.jsonl"
GEMINI_FLASH_DAILY_BUDGET_PATH = CACHE_DIR / "gemini_flash_daily_budget.json"

# --- List prices, USD per 1M tokens (for usage_report.md cost estimates only;
# both providers are used on free tiers here, so actual incurred cost is $0) ---
# Gemini prices: PRD 8.5. Groq qwen/qwen3.8-27b: Groq's self-serve preview
# catalog price as of 2026-08-27 (see https://www.usagepricing.com/blueprint/activity/groq-2026-08-27-qwen-self-serve-pricing);
# it is a preview model Groq may discontinue or re-price at short notice.
PRICING_PER_MILLION_TOKENS = {
    "qwen/qwen3.8-27b": {"input": 0.80, "output": 4.00},
    "gemini-3.1-flash-lite": {"input": 0.25, "output": 1.50},
    "gemini-3.8-flash": {"input": 0.75, "output": 3.75},
}

INTENT_PROMPT_VERSION = "v1"  # bumped whenever code/prompts/intent_v1.md changes
# Deliberately NOT bumped for the vision_v1.md wording clarification
# (resource_ids must match lowercase_word_digits): the actual fix for
# the garbage-resource-id problem (e.g. "Delivery tracking") is the
# code-level shape check in code/audit/evidence/image_reader.py's
# ground_resource_ids(), which filters the model's ALREADY-cached raw
# response -- it needs no new model call to take effect. Bumping this
# would force re-reading all 11 images with the slow, budget-limited
# second reader for no benefit.
VISION_PROMPT_VERSION = "v1"
