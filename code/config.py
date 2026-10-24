"""Non-secret configuration for the Ghost Data Still Exists pipeline.

No API keys live here. Keys are read from environment variables (.env) only,
in code/audit/llm/client.py (Phase 4), never in this file.

Model IDs below were confirmed in Phase 0 against the live provider accounts
(see log.txt). The PRD's original intent models (qwen/qwen3-32b and the
comparison candidate qwen/qwen3.6-27b) do not exist on this Groq key; the
user chose qwen/qwen3.8-27b, the closest available model in the same
family, as the replacement. All four IDs below were smoke-tested
successfully in this session.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATASET_DIR = REPO_ROOT / "dataset"
EVIDENCE_DIR = DATASET_DIR / "evidence"
CACHE_DIR = REPO_ROOT / ".cache"
OUTPUT_PATH = REPO_ROOT / "output.csv"

# --- Model IDs: confirmed against the live Groq / Gemini accounts in Phase 0 ---
INTENT_MODEL = "qwen/qwen3.8-27b"  # user-confirmed replacement for qwen/qwen3-32b (not available)
INTENT_MODEL_FALLBACK = "openai/gpt-oss-20b"  # PRD's own named rate-limit fallback
EXTRACT_MODEL = "gemini-3.8-flash"  # Gemini primary image/PDF reader
EXTRACT_MODEL_2 = "gemini-3.1-flash-lite"  # Gemini second reader

# --- Rate limits and batching: conservative placeholders, TODO-VERIFY in consoles ---
GROQ_REQUESTS_PER_MINUTE = 20  # TODO-VERIFY in console.groq.com
GROQ_TOKENS_PER_MINUTE = 6000  # TODO-VERIFY in console.groq.com
GROQ_REQUESTS_PER_DAY = 800  # TODO-VERIFY in console.groq.com
GROQ_TOKENS_PER_DAY = 150000  # TODO-VERIFY in console.groq.com

GEMINI_REQUESTS_PER_MINUTE = 10  # TODO-VERIFY in aistudio.google.com
GEMINI_TOKENS_PER_MINUTE = 100000  # TODO-VERIFY in aistudio.google.com
GEMINI_REQUESTS_PER_DAY = 200  # TODO-VERIFY in aistudio.google.com

INTENT_BATCH_SIZE = 8  # TODO-VERIFY: tune once rate limits are confirmed
MAX_TOKENS_PER_CALL = 2000  # TODO-VERIFY: hard budget guard

PROMPT_VERSION = "v0"  # bumped whenever a prompt file changes
