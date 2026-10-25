# Usage report

Both providers are used on their free tiers in this project; the `estimated cost` columns are list-price estimates (see code/config.py's PRICING_PER_MILLION_TOKENS), not actual billed amounts. `cache hits` are logical requests served from code/audit/llm/cache.py with zero network calls.

## Per-model totals

| provider | model | calls (logical) | live calls | cache hits | input tokens | output tokens | thinking tokens | errors | est. cost (USD) |
|---|---|---|---|---|---|---|---|---|---|
| gemini | gemini-3.1-flash-lite | 24 | 20 | 4 | 17049 | 2598 | 0 | 16 | $0.0082 |
| gemini | gemini-3.8-flash | 11 | 9 | 2 | 6714 | 720 | 915 | 8 | $0.0077 |
| groq | qwen/qwen3.8-27b | 117 | 80 | 37 | 203670 | 34057 | 0 | 0 | $0.2992 |

## Overall totals

- Total logical requests: 152
- Live calls: 109
- Cache hits: 43
- Total input tokens: 227433
- Total output tokens: 37375
- Total thinking tokens: 915
- Total tokens: 265723
- Average tokens per logical request: 1748.2
- Estimated total cost (list price): $0.3151
- Estimated average cost per request (list price): $0.002073
- Actual incurred cost (both providers on free tier for this run): $0.00
