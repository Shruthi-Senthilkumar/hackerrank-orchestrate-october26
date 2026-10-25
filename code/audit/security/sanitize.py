"""S1/S2 input sanitization and untrusted-data wrapping (C4).

Every piece of text that reaches a model (request_text, OCR text,
anything extracted from evidence) goes through `sanitize()` first, then
`wrap_untrusted()`. Flagged spans are masked before the model ever sees
them and are returned so the caller can record them in the case trace
-- this module never decides anything about the case itself, only
about what text is safe to hand to a model.

Languages covered for instruction-phrase detection: English, plus every
language actually found in dataset/deletion_requests.csv's request_text
(surveyed directly, Phase 4): Spanish, French, Portuguese, Japanese,
Korean. The phrase lists below are written by hand, grounded in real
vocabulary for each language, not copied from any dataset record.
"""

import re
import unicodedata

# Zero-width and other invisible characters sometimes used to hide text
# from a casual read while a model's tokenizer still sees it.
_ZERO_WIDTH_RE = re.compile(
    "[​‌‍⁠﻿­᠎⁡⁢⁣⁤]"
)

# Control characters (Unicode category Cc) other than the whitespace
# ones every real request legitimately contains.
_KEEP_CONTROL = {"\n", "\t", "\r"}


def _strip_control(text: str) -> str:
    return "".join(ch for ch in text if ch in _KEEP_CONTROL or unicodedata.category(ch) != "Cc")


# Instruction-like phrases, by language. Matched case-insensitively
# against NFKC-normalized text. Each is a plain substring/regex
# fragment, not an exhaustive NLP classifier -- the goal is to flag
# and mask a plausible injection attempt before it ever reaches a
# model, not to understand language.
_INSTRUCTION_PATTERNS = {
    "en": [
        r"ignore (all |the )?(previous|above|prior)",
        r"disregard (all |the )?(previous|above|prior)",
        r"new instructions?",
        r"system prompt",
        r"you are now",
        r"act as (if|a)",
        r"mark (this|the) (case|request|row)\b.*\b(complete|done)",
        r"delete (other|all) users?",
        r"\bdo not (follow|apply) (the|any) (polic|rule)",
        r"override (the )?(rules?|polic(y|ies))",
        r"forget (your |all )?(previous )?instructions?",
    ],
    "es": [
        r"ignora(r)? (las )?instrucciones (anteriores|previas)",
        r"nuevas instrucciones",
        r"act(ú|u)a como",
        r"marca (este|el) caso como completo",
    ],
    "fr": [
        r"ignore(z)? les instructions (pr(é|e)c(é|e)dentes|ci-dessus)",
        r"nouvelles instructions",
        r"agis (comme|en tant que)",
        r"marque(z)? ce cas comme termin(é|e)",
    ],
    "pt": [
        r"ignore (as )?instru(ç|c)(õ|o)es (anteriores|acima)",
        r"novas instru(ç|c)(õ|o)es",
        r"aja como",
        r"marque este caso como conclu(í|i)do",
    ],
    "ja": [
        r"以前の指示を無視",
        r"指示を無視",
        r"新しい指示",
        r"この(ケース|件)を完了(に|と)(マーク|して)",
    ],
    "ko": [
        r"이전\s*지시(를|사항을)?\s*무시",
        r"새로운\s*지시",
        r"이\s*(케이스|사건)를\s*완료로\s*표시",
    ],
}

_COMPILED_INSTRUCTION_PATTERNS = [
    (lang, re.compile(p, re.IGNORECASE)) for lang, patterns in _INSTRUCTION_PATTERNS.items() for p in patterns
]

# A long run of base64/hex-shaped characters is a plausible encoded
# payload smuggling attempt, not a normal sentence in any of the
# dataset's languages.
_ENCODED_BLOB_RE = re.compile(r"\b[A-Za-z0-9+/]{60,}={0,2}\b|\b[0-9a-fA-F]{80,}\b")


def sanitize(text: str) -> tuple[str, list[dict]]:
    """Returns (sanitized_text, flagged_spans). Each flagged span is
    {"kind": "instruction"|"encoded_blob", "language": "..." or "",
    "original": "<the matched text>", "start": int, "end": int} --
    positions are in the NORMALIZED text (after NFKC + control-char
    stripping), which is also what `sanitized_text` is built from."""
    normalized = unicodedata.normalize("NFKC", text)
    normalized = _ZERO_WIDTH_RE.sub("", normalized)
    normalized = _strip_control(normalized)

    flags: list[dict] = []
    masked = normalized

    for lang, pattern in _COMPILED_INSTRUCTION_PATTERNS:
        for m in pattern.finditer(masked):
            flags.append(
                {"kind": "instruction", "language": lang, "original": m.group(0), "start": m.start(), "end": m.end()}
            )
    for m in _ENCODED_BLOB_RE.finditer(masked):
        flags.append({"kind": "encoded_blob", "language": "", "original": m.group(0), "start": m.start(), "end": m.end()})

    # Mask longest-first, right to left, so earlier spans' positions
    # stay valid as later ones are replaced.
    for flag in sorted(flags, key=lambda f: (-len(f["original"]), -f["start"])):
        placeholder = f"[MASKED:{flag['kind']}]"
        masked = masked[: flag["start"]] + placeholder + masked[flag["end"] :]

    return masked, flags


def wrap_untrusted(text: str, label: str = "DATA") -> str:
    """Wraps text in explicit untrusted-data delimiters the system
    prompt tells the model about (C2). The model is told everything
    between the markers is data to classify/extract from, never an
    instruction, regardless of what it contains."""
    return f"<<<UNTRUSTED_{label}_START>>>\n{text}\n<<<UNTRUSTED_{label}_END>>>"
