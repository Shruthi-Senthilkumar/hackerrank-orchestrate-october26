# Usage report

Both providers are used on their free tiers in this project; the `estimated cost` columns are list-price estimates (see code/config.py's PRICING_PER_MILLION_TOKENS), not actual billed amounts. `cache hits` are logical requests served from code/audit/llm/cache.py with zero network calls.

## Per-model totals

| provider | model | calls (logical) | live calls | cache hits | input tokens | output tokens | thinking tokens | errors | est. cost (USD) |
|---|---|---|---|---|---|---|---|---|---|
| gemini | gemini-3.1-flash-lite | 11 | 0 | 11 | 25531 | 2739 | 0 | 0 | $0.0105 |
| gemini | gemini-3.8-flash | 2 | 0 | 2 | 0 | 0 | 0 | 0 | $0.0000 |
| groq | qwen/qwen3.8-27b | 398 | 0 | 398 | 765752 | 141688 | 0 | 0 | $1.1794 |

## Overall totals

- Total logical requests: 411
- Live calls: 0
- Cache hits: 411
- Total input tokens: 791283
- Total output tokens: 144427
- Total thinking tokens: 0
- Total tokens: 935710
- Average tokens per logical request: 2276.7
- Estimated total cost (list price): $1.1898
- Estimated average cost per request (list price): $0.002895
- Actual incurred cost (both providers on free tier for this run): $0.00
- Per dataset request (all 518 deletion requests): 1806.4 tokens, $0.002297 estimated list-price cost (intent calls are batched, images are read once, so this is below the per-logical-request average)
