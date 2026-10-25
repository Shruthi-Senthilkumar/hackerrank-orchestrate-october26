"""F13 intent classifier (PRD 8.1, Phase 4, D10).

Pipeline per request (see classify_all()):
  (a) a deterministic multilingual rule layer (rule_layer_classify)
      built from the language families actually found in
      dataset/deletion_requests.csv's request_text (surveyed directly:
      English, Spanish, French, Portuguese, Japanese, Korean);
  (b) Qwen (code/audit/llm/client.py), batched
      config.INTENT_BATCH_SIZE at a time, temperature 0;
  (c) agreement between (a) and (b) -> accept Qwen's answer (the rule
      layer has no opinion -- RULE_UNSURE -- defers to Qwen without
      counting as a disagreement); a genuine conflict (rule says
      DELETE, Qwen says NOT_DELETE, or vice versa), Qwen saying
      UNCLEAR, or an invalid evidence_phrase substring -> one extra
      single-text Qwen pass; still unresolved -> default NOT_APPLICABLE
      (D10: never assume authorization) and flag it;
  (d) a visible CLASSIFY_REQUEST activity for one of the case's own
      ALREADY-LINKED resources (never looked up by a guessed resource
      id) is logged as corroboration only, in case_runner.py, after
      linking -- never as authority, never consulted here.

C1: this module only classifies; it never decides a case's deletion
status. C4: every text is run through code/audit/security/sanitize.py
before it reaches a model.
"""

import re
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import config
    from audit.llm import client, replay
    from audit.security import sanitize
else:
    import config
    from .llm import client, replay
    from .security import sanitize

RULE_DELETE = "DELETE"
RULE_NOT_DELETE = "NOT_DELETE"
RULE_UNSURE = "UNSURE"

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "intent_v1.md"

# --- deterministic multilingual rule layer ------------------------------

# Deletion-verb word roots, one list per language family found in the
# data (see module docstring). Regex fragments, not whole words, so
# they match any inflection (delete/deleting/deleted, elimino/eliminar/
# eliminación, ...).
_DELETION_VERB_ROOTS = {
    "en": [r"delet", r"eras", r"remov", r"clos\w*\s+(the|my|this)?\s*account", r"permanently\s+delet"],
    "es": [r"elimin", r"borr", r"suprim", r"cerrar\s+\w*\s*cuenta"],
    "fr": [r"suppr", r"effac", r"fermer\s+\w*\s*compte"],
    "pt": [r"exclu", r"apag", r"encerrar\s+\w*\s*conta"],
    "ja": [r"削除", r"消去"],
    "ko": [r"삭제", r"제거"],
}

# Negation trigger words, space-delimited languages only (en/es/fr/pt);
# combined with the verb roots above into windowed patterns in both
# orders ("do not delete" and "delete ... without"). ja/ko use their
# own hand-written compound phrases below instead, since word-boundary
# regex does not meaningfully apply to those scripts.
_NEGATION_WORDS = {
    "en": [r"not", r"never", r"don'?t", r"do\s+not", r"without"],
    "es": [r"no", r"sin", r"nunca"],
    "fr": [r"pas", r"sans", r"jamais"],
    "pt": [r"não", r"sem", r"nunca"],
}

# Hedge phrases that contain the word "not" but do not negate the
# deletion verb itself (e.g. "I'm not sure it went through" is hedging
# about whether something happened, not asking that it NOT happen).
# Masked out before negation matching only -- never affects has_verb
# or the language guess.
_HEDGE_RE = re.compile(r"\bnot\s+(sure|certain|100%\s+sure)\b", re.IGNORECASE)

_NEGATION_COMPOUND_JA_KO = [
    r"削除(では|しない|せず|しないで)",
    r"削除.{0,10}(ではなく|しないで)",
    r"삭제.{0,10}(가\s*아니|하지\s*마|말고)",
]

# Deletion-verb-near-scoped-object: the verb's object is something
# OTHER than the account/profile/data itself (marketing, a newsletter,
# a subscription) -- e.g. "remove me from marketing lists only". A
# deletion verb near one of these, with no account/data word also
# nearby, is a scoped request, not an account-deletion request.
_SCOPED_AWAY_OBJECTS = {
    "en": [r"marketing", r"newsletter", r"promotional", r"mailing\s+list", r"subscription"],
    "es": [r"marketing", r"public\w*", r"lista\s+de\s+correo"],
    "fr": [r"marketing", r"publicit\w*", r"liste\s+de\s+diffusion"],
    "pt": [r"marketing", r"publicidad\w*", r"lista\s+de\s+e-?mails"],
    "ja": [r"マーケティング", r"ニュースレター"],
    "ko": [r"마케팅", r"뉴스레터"],
}


def _compile_all(fragments: list[str]) -> list[re.Pattern]:
    return [re.compile(p, re.IGNORECASE) for p in fragments]


_VERB_PATTERNS = {lang: _compile_all(roots) for lang, roots in _DELETION_VERB_ROOTS.items()}
_SCOPED_PATTERNS = {lang: _compile_all(objs) for lang, objs in _SCOPED_AWAY_OBJECTS.items()}
_NEGATION_COMPOUND_PATTERNS = _compile_all(_NEGATION_COMPOUND_JA_KO)

_NEGATION_WINDOW_PATTERNS: list[re.Pattern] = []
for lang, neg_words in _NEGATION_WORDS.items():
    verb_roots = _DELETION_VERB_ROOTS[lang]
    neg_alt = "|".join(neg_words)
    verb_alt = "|".join(verb_roots)
    _NEGATION_WINDOW_PATTERNS.append(re.compile(rf"\b({neg_alt})\b[^.!?]{{0,40}}\b({verb_alt})", re.IGNORECASE))
    _NEGATION_WINDOW_PATTERNS.append(re.compile(rf"\b({verb_alt})[a-z]*\b[^.!?]{{0,40}}\b({neg_alt})\b", re.IGNORECASE))


def _script_language_guess(text: str) -> str:
    if any("가" <= ch <= "힣" for ch in text):
        return "ko"
    if any(("぀" <= ch <= "ヿ") or ("一" <= ch <= "鿿") for ch in text):
        return "ja"
    for lang in ("pt", "es", "fr"):
        if any(p.search(text) for p in _VERB_PATTERNS[lang]):
            return lang
    return "en"


def _has_scoped_away_verb(text: str) -> bool:
    """A deletion verb whose nearby object (±30 chars) is a
    marketing/newsletter/subscription word, not the account/data
    itself."""
    for lang, verb_patterns in _VERB_PATTERNS.items():
        for vp in verb_patterns:
            for m in vp.finditer(text):
                window = text[max(0, m.start() - 30) : min(len(text), m.end() + 30)]
                for scoped_patterns in _SCOPED_PATTERNS.values():
                    if any(sp.search(window) for sp in scoped_patterns):
                        return True
    return False


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?。！？])\s+")


def _sentence_verdict(sentence: str) -> str:
    """One sentence's own verdict, ignoring every other sentence. A
    negation elsewhere in the text (e.g. an injected second sentence
    trying to neutralize a genuine request in the first one) must
    never suppress a clean, unnegated ask in THIS sentence -- see
    rule_layer_classify's module-level note."""
    negation_scan_text = _HEDGE_RE.sub("XHEDGEX", sentence)
    negated = any(p.search(negation_scan_text) for p in _NEGATION_WINDOW_PATTERNS) or any(
        p.search(negation_scan_text) for p in _NEGATION_COMPOUND_PATTERNS
    )
    if negated:
        return RULE_NOT_DELETE

    has_verb = any(p.search(sentence) for patterns in _VERB_PATTERNS.values() for p in patterns)
    if has_verb and _has_scoped_away_verb(sentence):
        return RULE_NOT_DELETE
    if has_verb:
        return RULE_DELETE
    return RULE_UNSURE


def rule_layer_classify(text: str) -> tuple[str, str]:
    """Returns (verdict, language_guess). verdict is RULE_DELETE,
    RULE_NOT_DELETE, or RULE_UNSURE (no opinion -- defers to Qwen).

    Evaluated per sentence, not over the whole text at once: a text
    with ANY sentence that cleanly, unambiguously asks for deletion
    (no negation, not scoped away) is DELETE, even if another sentence
    elsewhere is negated or unrelated -- this is what keeps an injected
    sentence (e.g. "...without deleting anything") from retroactively
    flipping a genuine, separate deletion request earlier in the same
    text (found via I5 security testing, Phase 4 task 6). Only when NO
    sentence is a clean DELETE does a negated/scoped sentence make the
    whole text NOT_DELETE; with neither, the text is UNSURE."""
    normalized = unicodedata.normalize("NFKC", text)
    lang = _script_language_guess(normalized)

    sentences = _SENTENCE_SPLIT_RE.split(normalized) or [normalized]
    verdicts = [_sentence_verdict(s) for s in sentences if s.strip()]

    if RULE_DELETE in verdicts:
        return RULE_DELETE, lang
    if RULE_NOT_DELETE in verdicts:
        return RULE_NOT_DELETE, lang
    return RULE_UNSURE, lang


# --- full pipeline (rule layer + Qwen + escalation) ---------------------


@dataclass
class IntentResult:
    case_id: str
    final_intent: str  # "DELETE" or "NOT_APPLICABLE"
    rule_verdict: str
    qwen_intent: Optional[str]
    qwen_language: Optional[str]
    qwen_evidence_phrase: Optional[str]
    escalated: bool
    resolution: str  # "agreement" | "escalation_agreement" | "unresolved_default"
    flagged: bool
    sanitize_flags: list = field(default_factory=list)


def _load_system_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def _valid_substring(evidence_phrase: str, original_text: str) -> bool:
    return bool(evidence_phrase) and evidence_phrase in original_text


def _replay_to_result(case_id: str, replayed: dict, sanitize_flags: list) -> "IntentResult":
    return IntentResult(
        case_id=case_id, final_intent=replayed["final_intent"], rule_verdict=replayed["rule_verdict"],
        qwen_intent=replayed["qwen_intent"], qwen_language=replayed["qwen_language"],
        qwen_evidence_phrase=replayed["qwen_evidence_phrase"], escalated=replayed["escalated"],
        resolution=replayed["resolution"], flagged=replayed["flagged"], sanitize_flags=sanitize_flags,
    )


def _flagged_unresolved(case_id: str, rule_verdict: str, sanitize_flags: list) -> "IntentResult":
    """Final-phase task 1: a missing replay/.cache entry with no keys
    (or ai disabled) must NEVER raise -- D10's safe default applies and
    the case is flagged, but the run continues."""
    return IntentResult(
        case_id=case_id, final_intent="NOT_APPLICABLE", rule_verdict=rule_verdict,
        qwen_intent=None, qwen_language=None, qwen_evidence_phrase=None, escalated=False,
        resolution="unresolved_no_entry", flagged=True, sanitize_flags=sanitize_flags,
    )


def classify_all(requests: list, ai_enabled: bool) -> dict:
    """requests: list of objects with .case_id and .request_text
    (loaders.DeletionRequest, or anything with those two attributes).
    Returns {case_id: IntentResult}. Lookup order: code/replay/ ->
    .cache/ (inside client.py) -> a live call only if ai_enabled. A
    request missing everywhere never raises; it is flagged instead."""
    system_prompt = _load_system_prompt()
    rule_results: dict[str, tuple[str, str]] = {}
    sanitize_flags_by_case: dict[str, list] = {}
    sanitized_text_by_case: dict[str, str] = {}
    out: dict[str, IntentResult] = {}
    replayed_ids: set[str] = set()

    for req in requests:
        masked, flags = sanitize.sanitize(req.request_text)
        sanitize_flags_by_case[req.case_id] = flags
        sanitized_text_by_case[req.case_id] = masked
        rule_results[req.case_id] = rule_layer_classify(req.request_text)

        replayed = replay.get_intent(req.request_text)
        if replayed is not None:
            out[req.case_id] = _replay_to_result(req.case_id, replayed, flags)
            replayed_ids.add(req.case_id)

    order = [req.case_id for req in requests if req.case_id not in replayed_ids]
    text_by_case = {req.case_id: req.request_text for req in requests}

    qwen_by_case: dict[str, dict] = {}
    unresolved_batches: set[str] = set()
    batch: list[str] = []
    batch_ids: list[str] = []

    def flush_batch():
        if not batch:
            return
        try:
            results = client.intent_classify_batch(batch, ai_enabled, system_prompt)
            for cid, r in zip(batch_ids, results):
                qwen_by_case[cid] = r
        except client.AIDisabledError:
            unresolved_batches.update(batch_ids)

    for case_id in order:
        batch.append(sanitized_text_by_case[case_id])
        batch_ids.append(case_id)
        if len(batch) == config.INTENT_BATCH_SIZE:
            flush_batch()
            batch, batch_ids = [], []
    flush_batch()

    for case_id in order:
        if case_id in unresolved_batches:
            out[case_id] = _flagged_unresolved(case_id, rule_results[case_id][0], sanitize_flags_by_case[case_id])
            continue
        rule_verdict, _rule_lang = rule_results[case_id]
        qwen = qwen_by_case[case_id]
        original_text = text_by_case[case_id]
        valid_sub = _valid_substring(qwen["evidence_phrase"], original_text)

        agree = (
            valid_sub
            and qwen["intent"] != "UNCLEAR"
            and (rule_verdict == RULE_UNSURE or qwen["intent"] == rule_verdict)
        )

        if agree:
            final = "DELETE" if qwen["intent"] == "DELETE" else "NOT_APPLICABLE"
            out[case_id] = IntentResult(
                case_id=case_id, final_intent=final, rule_verdict=rule_verdict,
                qwen_intent=qwen["intent"], qwen_language=qwen["language"],
                qwen_evidence_phrase=qwen["evidence_phrase"], escalated=False,
                resolution="agreement", flagged=False, sanitize_flags=sanitize_flags_by_case[case_id],
            )
            continue

        # Escalate: one more single-text Qwen pass.
        try:
            escalated_qwen = client.intent_classify_single(sanitized_text_by_case[case_id], ai_enabled, system_prompt)
        except client.AIDisabledError:
            out[case_id] = _flagged_unresolved(case_id, rule_verdict, sanitize_flags_by_case[case_id])
            continue
        escalated_valid = _valid_substring(escalated_qwen["evidence_phrase"], original_text)
        escalated_agree = escalated_valid and escalated_qwen["intent"] != "UNCLEAR" and (
            rule_verdict == RULE_UNSURE or escalated_qwen["intent"] == rule_verdict
        )
        if escalated_agree:
            final = "DELETE" if escalated_qwen["intent"] == "DELETE" else "NOT_APPLICABLE"
            out[case_id] = IntentResult(
                case_id=case_id, final_intent=final, rule_verdict=rule_verdict,
                qwen_intent=escalated_qwen["intent"], qwen_language=escalated_qwen["language"],
                qwen_evidence_phrase=escalated_qwen["evidence_phrase"], escalated=True,
                resolution="escalation_agreement", flagged=False, sanitize_flags=sanitize_flags_by_case[case_id],
            )
            continue

        # Still unresolved: D10 default -- never assume authorization.
        out[case_id] = IntentResult(
            case_id=case_id, final_intent="NOT_APPLICABLE", rule_verdict=rule_verdict,
            qwen_intent=escalated_qwen["intent"], qwen_language=escalated_qwen["language"],
            qwen_evidence_phrase=escalated_qwen["evidence_phrase"], escalated=True,
            resolution="unresolved_default", flagged=True, sanitize_flags=sanitize_flags_by_case[case_id],
        )

    return out
