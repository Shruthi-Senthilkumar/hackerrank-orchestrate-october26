"""link_check.py -- NOT part of the audit pipeline (code/audit/).

For each of the 32 sample cases, runs identity + the evidence registry +
the linker as of that case's audit_at, and compares the linked
(system_id, resource_id) pairs against the pairs appearing in
sample_output.csv's steps for that case. This is the one script allowed
to read sample_output.csv (per the Phase 2 instructions, the audit logic
itself never does).

Runs twice: once with D15's default (a file's manifest captured_at gates
visibility; a JSON bundle's or log line's inner timestamp only decides
recency) and once with the alternative (the inner/observed_at timestamp
also gates visibility), and reports whether the two differ.

Usage: python code/evaluation/link_check.py
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "code"))

from audit import identity, loaders  # noqa: E402
from audit.evidence.registry import build_registry, RegistryResult  # noqa: E402
from audit.linker import link_observations  # noqa: E402
from audit.models import Observation  # noqa: E402
from audit.timeview import TimeView, build_time_view  # noqa: E402


def _expected_pairs(steps: list[dict]) -> set[tuple[str, str]]:
    return {(s["system_id"], s["resource_id"]) for s in steps}


def _visible_observations_strict(reg: RegistryResult, time_view: TimeView) -> list[Observation]:
    """The D15 alternative: a file must be visible by manifest time, AND
    each observation's own observed_at must also be <= audit_at."""
    visible_file_ids = {e.file_id for e in time_view.visible_evidence_files()}
    out = []
    for file_id, obs_list in reg.observations_by_file.items():
        if file_id not in visible_file_ids:
            continue
        for obs in obs_list:
            if time_view.is_visible(obs.observed_at):
                out.append(obs)
    return out


def run_link_check(strict_inner_timestamp: bool) -> dict:
    reg = build_registry()
    sample_requests = {r.case_id: r for r in loaders.load_sample_deletion_requests()}
    sample_output = {r.case_id: r for r in loaders.load_sample_output()}

    per_case = {}
    total_expected = 0
    total_matched = 0
    total_extra = 0
    gap_pairs: list[tuple[str, str, str]] = []  # (case_id, system_id, resource_id)

    for case_id in sorted(sample_requests, key=lambda c: int(c.split("_")[1])):
        req = sample_requests[case_id]
        expected_steps = sample_output[case_id].steps if case_id in sample_output else []
        expected = _expected_pairs(expected_steps)

        resolution = identity.resolve_request_email(req.email, req.requested_at)
        if resolution.user_id is None:
            per_case[case_id] = {"error": "identity did not resolve", "expected": len(expected)}
            continue

        time_view = build_time_view(req.audit_at)
        ident = identity.build_identity(resolution.user_id, req.audit_at)

        if strict_inner_timestamp:
            obs = _visible_observations_strict(reg, time_view)
        else:
            from audit.evidence.registry import visible_observations

            obs = visible_observations(reg, time_view)

        linked = link_observations(obs, ident, time_view)
        linked_pairs = {(l.observation.system_id, l.observation.resource_id) for l in linked}

        matched = linked_pairs & expected
        extra = linked_pairs - expected
        missing = expected - linked_pairs

        # a missing pair is a "gap" if it cannot be reproduced from ANY
        # visible observation at all (not just the linked ones) -- i.e.
        # evidence exists but the linker didn't connect it, vs. no
        # evidence exists for it under this case's audit_at at all.
        all_resource_ids_seen = {o.resource_id for o in obs}
        for sys_id, rid in sorted(missing):
            if rid not in all_resource_ids_seen:
                gap_pairs.append((case_id, sys_id, rid))

        per_case[case_id] = {
            "expected": len(expected),
            "matched": len(matched),
            "extra": sorted(extra),
            "missing": sorted(missing),
            "recall": (len(matched) / len(expected)) if expected else 1.0,
        }
        total_expected += len(expected)
        total_matched += len(matched)
        total_extra += len(extra)

    overall_recall = (total_matched / total_expected) if total_expected else 1.0
    return {
        "per_case": per_case,
        "overall_recall": overall_recall,
        "total_expected": total_expected,
        "total_matched": total_matched,
        "total_extra": total_extra,
        "gap_pairs": gap_pairs,
    }


def main() -> int:
    default_result = run_link_check(strict_inner_timestamp=False)
    strict_result = run_link_check(strict_inner_timestamp=True)

    print("=== D15 default (manifest time gates visibility) ===")
    print(f"overall recall: {default_result['overall_recall']:.3f} "
          f"({default_result['total_matched']}/{default_result['total_expected']}), "
          f"total extra: {default_result['total_extra']}")

    worst = sorted(default_result["per_case"].items(), key=lambda kv: kv[1].get("recall", 0))[:5]
    print("\n5 worst cases by recall:")
    for case_id, info in worst:
        print(f"  {case_id}: {info}")

    print(f"\ngap pairs (not reproducible from any visible evidence, {len(default_result['gap_pairs'])} total):")
    for g in default_result["gap_pairs"][:20]:
        print(" ", g)

    print("\n=== D15 alternative (inner/observed_at timestamp also gates visibility) ===")
    print(f"overall recall: {strict_result['overall_recall']:.3f} "
          f"({strict_result['total_matched']}/{strict_result['total_expected']}), "
          f"total extra: {strict_result['total_extra']}")

    diff = default_result["overall_recall"] - strict_result["overall_recall"]
    print(f"\nrecall difference (default - strict): {diff:+.4f}")
    if default_result["total_matched"] != strict_result["total_matched"]:
        print("The two visibility rules give DIFFERENT linked sets on the samples.")
    else:
        print("The two visibility rules give the SAME linked sets on the samples (D15's default is safe here).")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
