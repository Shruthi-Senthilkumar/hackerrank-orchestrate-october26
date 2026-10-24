"""Ghost Data Still Exists - deletion audit pipeline entry point.

Phase 0 stub: prints the planned pipeline and exits. No audit logic yet.
"""

import argparse


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Ghost Data Still Exists - deletion audit pipeline",
    )
    parser.add_argument(
        "--cases",
        default=None,
        help="Comma-separated case_id list to run instead of the full dataset "
        "(debug only; never used to change logic by ID).",
    )
    parser.add_argument(
        "--no-ai",
        action="store_true",
        help="Run the rules-only baseline with no model calls.",
    )
    return parser


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()

    print("Ghost Data Still Exists - deletion audit pipeline (Phase 0 skeleton)")
    print(f"  cases filter : {args.cases or 'ALL (dataset/deletion_requests.csv)'}")
    print(f"  mode         : {'no-ai (rules-only baseline)' if args.no_ai else 'full (rules + AI layer)'}")
    print("  status       : no audit logic implemented yet (Phase 0 scope only)")
    print("  planned steps: loaders -> timeview -> identity -> linker -> policy ->")
    print("                 detectors -> decision -> planner -> validator -> writer")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
