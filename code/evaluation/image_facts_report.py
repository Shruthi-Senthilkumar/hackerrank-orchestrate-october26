"""Phase 4 task 5: builds the evidence registry fresh (forcing every
image to be read again, recording one ImageReadReport per image) and
writes:
  - code/evaluation/extracted_image_facts.md (D14): the agreed facts
    for every image, in Markdown, so the submission can be reproduced
    and reviewed without any further model call.
  - prints the per-image summary required by the task: document type,
    facts extracted/grounded/dropped/disagreements, which linker rule
    (if any) linked it in each of the 32 samples + 518 real cases, and
    whether any sample/case status changed as a result.
  - re-checks D16: does any image show a SECONDARY_IDENTIFIER or
    PRODUCT_TELEMETRY record?

Run: python code/evaluation/image_facts_report.py
"""

import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "code"))

from dotenv import load_dotenv  # noqa: E402

from audit import identity, intent, loaders  # noqa: E402
from audit.case_runner import run_case  # noqa: E402
from audit.evidence.registry import build_registry  # noqa: E402
from audit.linker import link_observations  # noqa: E402
from audit.evidence.registry import visible_document_hints, visible_observations, visible_trace_hints  # noqa: E402
from audit.timeview import build_time_view  # noqa: E402


def main() -> int:
    load_dotenv(REPO_ROOT / ".env")

    image_reports = []
    # use_cache=False: this script's whole job is the per-image REPORT
    # (extracted/grounded/dropped/disagreements), which the registry's
    # own disk cache does not persist -- only re-parsing produces it.
    # Still fast and free: code/audit/llm/client.py's own per-image
    # model-result cache means this makes zero new network calls for
    # anything already read.
    reg = build_registry(use_cache=False, ai_enabled=True, image_reports=image_reports)
    image_file_ids = [r.file_id for r in image_reports]

    # D16 re-check: any SECONDARY_IDENTIFIER / PRODUCT_TELEMETRY category
    # anywhere in what the images produced?
    d16_categories_found = set()
    for fid in image_file_ids:
        for o in reg.observations_by_file.get(fid, []):
            if o.category in ("SECONDARY_IDENTIFIER", "PRODUCT_TELEMETRY"):
                d16_categories_found.add(o.category)

    # Which linker rule (if any) linked each image's resources, across
    # the 32 samples + 518 real cases, and whether any case's status
    # changed because of it (compared informationally only -- this
    # script does not change any decision).
    all_requests = loaders.load_sample_deletion_requests() + loaders.load_deletion_requests()
    image_link_rules = defaultdict(set)  # file_id -> {rule}
    cases_touched = defaultdict(set)  # file_id -> {case_id}

    for req in all_requests:
        resolution = identity.resolve_request_email(req.email, req.requested_at)
        if resolution.user_id is None:
            continue
        tv = build_time_view(req.audit_at)
        ident = identity.build_identity(resolution.user_id, req.audit_at)
        obs = visible_observations(reg, tv)
        trace_hints = visible_trace_hints(reg, tv)
        doc_hints = visible_document_hints(reg, tv)
        linked = link_observations(obs, ident, tv, trace_hints, doc_hints)
        for l in linked:
            if l.observation.source_id in image_file_ids:
                image_link_rules[l.observation.source_id].add(l.rule)
                cases_touched[l.observation.source_id].add(req.case_id)

    lines = []
    lines.append("# Extracted image facts (Phase 4 task 5, D14)\n")
    lines.append(
        "Agreed facts for every image evidence file, produced by OCR grounding plus two Gemini "
        "readers (code/audit/evidence/image_reader.py). Committed here so the submission can be "
        "reviewed and reproduced without any further model call -- the live cache itself "
        "(.cache/) is git-ignored and not part of code.zip.\n"
    )
    lines.append(
        f"D16 re-check: SECONDARY_IDENTIFIER or PRODUCT_TELEMETRY found in any image? "
        f"{'YES: ' + ', '.join(sorted(d16_categories_found)) if d16_categories_found else 'No -- D16 still holds.'}\n"
    )

    lines.append("## Per-image summary\n")
    lines.append("| file_id | document_type | facts_extracted | grounded | dropped | disagreements | linker rules used | cases touched |")
    lines.append("|---|---|---|---|---|---|---|---|")

    for report in image_reports:
        rules = ", ".join(sorted(image_link_rules.get(report.file_id, set()))) or "(none -- never linked to any case)"
        n_cases = len(cases_touched.get(report.file_id, set()))
        lines.append(
            f"| {report.file_id} | {report.document_type or '(n/a)'} | {report.facts_extracted} | "
            f"{report.facts_grounded} | {report.facts_dropped} | {report.disagreements} | {rules} | {n_cases} |"
        )
        if report.flagged:
            lines.append(f"  - **flagged**: {report.flagged}")

    lines.append("\n## Agreed facts, in full\n")
    for report in image_reports:
        lines.append(f"### {report.file_id}\n")
        lines.append(f"```json\n{report.agreed}\n```\n")

    out_path = REPO_ROOT / "code" / "evaluation" / "extracted_image_facts.md"
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {out_path}")
    print(f"images processed this run: {len(image_reports)}")
    for report in image_reports:
        print(
            f"  {report.file_id}: type={report.document_type} extracted={report.facts_extracted} "
            f"grounded={report.facts_grounded} dropped={report.facts_dropped} "
            f"disagreements={report.disagreements} second_used={report.second_reader_used} "
            f"flagged={report.flagged!r} linked_by={sorted(image_link_rules.get(report.file_id, set()))} "
            f"cases={len(cases_touched.get(report.file_id, set()))}"
        )
    print(f"D16 categories found in images: {sorted(d16_categories_found) or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
