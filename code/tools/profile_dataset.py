"""Profile every evidence file and system_activity.csv resource_id prefix.

Phase 1 task 5 support tool. Produces the raw facts that
code/evaluation/profile_report.md is written from: resource_id prefixes,
SQL topology/schema, JSON record shapes, log line families, PDF text-layer
presence, image counts, the text record, an approximate per-file count of
how many request emails appear, and the manifest-vs-internal timestamp
agreement check (a [CALIBRATE] question, reported but not decided here).

No model calls. No OCR. Deterministic. Read-only.

Usage: python code/tools/profile_dataset.py
"""

import csv
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CODE_DIR = REPO_ROOT / "code"
sys.path.insert(0, str(CODE_DIR))

from audit import loaders  # noqa: E402
from audit.evidence.sql_sandbox import load_sql_file, SqlSandboxError  # noqa: E402

DATASET_DIR = REPO_ROOT / "dataset"
EVIDENCE_DIR = DATASET_DIR / "evidence"

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
RESOURCE_ID_RE = re.compile(r"\b([a-z]+(?:_[a-z]+)*)_([0-9]{1,6})\b")


def build_known_emails():
    """All current + historical case emails, lowercased, plus their sha256 hashes."""
    emails = set()
    for req in loaders.load_deletion_requests():
        emails.add(req.email)
    for req in loaders.load_sample_deletion_requests():
        emails.add(req.email)
    for ident in loaders.load_user_identities():
        emails.add(ident.email)
    for entry in loaders.load_user_audit_log():
        if entry.field_name == "email":
            emails.add(entry.old_value.strip().lower())
            emails.add(entry.new_value.strip().lower())
    hashes = {hashlib.sha256(e.encode("utf-8")).hexdigest(): e for e in emails}
    return emails, hashes


def count_known_emails_in_text(text: str, known_emails: set, known_hashes: dict) -> int:
    text_lower = text.lower()
    found = set()
    for email in known_emails:
        if email in text_lower:
            found.add(email)
    for h in known_hashes:
        if h in text_lower:
            found.add(known_hashes[h])
    return len(found)


def profile_resource_id_prefixes():
    print("\n" + "=" * 70)
    print("1. RESOURCE_ID PREFIXES in system_activity.csv")
    print("=" * 70)
    counts = Counter()
    systems = defaultdict(set)
    for a in loaders.load_system_activity():
        m = re.match(r"^([a-z]+(?:_[a-z]+)*)_[0-9]+$", a.resource_id)
        prefix = (m.group(1) + "_") if m else a.resource_id
        counts[prefix] += 1
        systems[prefix].add(a.source_system)
        systems[prefix].add(a.target_system)
    for p, c in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {p}: {c} activity rows, systems={sorted(systems[p])}")


def profile_sql_files():
    print("\n" + "=" * 70)
    print("2. SQL SNAPSHOTS (dataset/evidence/databases/*.sql)")
    print("=" * 70)
    results = []
    for ev in sorted(loaders.load_evidence_files(), key=lambda e: e.file_path):
        if not ev.file_path.endswith(".sql"):
            continue
        path = DATASET_DIR / ev.file_path
        try:
            snap = load_sql_file(path)
        except SqlSandboxError as e:
            print(f"  REJECTED {ev.file_id} {ev.file_path}: {e}")
            continue
        tables = snap.tables()
        counts = {t: snap.row_count(t) for t in tables}
        internal_captured_at = []
        if "Captured at" in snap.header:
            internal_captured_at.append(("header", snap.header["Captured at"]))
        if "snapshot_scope" in tables:
            rows = snap.query("SELECT origin_system, captured_at FROM snapshot_scope")
            for origin, cap in rows:
                internal_captured_at.append((f"snapshot_scope[{origin}]", cap))
        replica_tables = [t for t in tables if "replica" in t.lower()]
        results.append(
            {
                "file_id": ev.file_id,
                "path": ev.file_path,
                "manifest_captured_at": ev.captured_at.isoformat(),
                "topology": snap.header.get("Database topology", "n/a (inventory-style)"),
                "tables": counts,
                "replica_tables": replica_tables,
                "internal_timestamps": internal_captured_at,
            }
        )
        snap.close()

    for r in results:
        print(f"\n  {r['file_id']} {r['path']}")
        print(f"    manifest captured_at: {r['manifest_captured_at']}")
        print(f"    topology: {r['topology']}")
        print(f"    tables: {r['tables']}")
        if r["replica_tables"]:
            print(f"    replica tables: {r['replica_tables']}")
        print(f"    internal timestamp(s): {r['internal_timestamps']}")
    return results


def profile_json_records(known_emails, known_hashes):
    print("\n" + "=" * 70)
    print("3. JSON / TEXT RECORD FILES (dataset/evidence/records/*)")
    print("=" * 70)
    results = []
    for ev in sorted(loaders.load_evidence_files(), key=lambda e: e.file_path):
        if "/records/" not in ev.file_path:
            continue
        path = DATASET_DIR / ev.file_path
        text = path.read_text(encoding="utf-8")
        email_count = count_known_emails_in_text(text, known_emails, known_hashes)

        if path.suffix == ".txt":
            snapshot_line = None
            for line in text.splitlines()[:5]:
                if "snapshot" in line.lower() or "captured" in line.lower():
                    snapshot_line = line.strip()
                    break
            print(f"\n  {ev.file_id} {ev.file_path} (TEXT)")
            print(f"    manifest captured_at: {ev.captured_at.isoformat()}")
            print(f"    internal timestamp line: {snapshot_line!r}")
            print(f"    known-email matches (approx): {email_count}")
            results.append(
                {"file_id": ev.file_id, "path": ev.file_path, "format": "text", "email_count": email_count}
            )
            continue

        data = json.loads(text)
        top_keys = sorted(data.keys()) if isinstance(data, dict) else ["<list>"]
        internal_ts = []
        collections = Counter()
        if isinstance(data, dict):
            if "exported_at" in data:
                internal_ts.append(("exported_at", data["exported_at"]))
            if "captured_at" in data:
                internal_ts.append(("captured_at", data["captured_at"]))
            if "snapshots" in data:
                for snap in data["snapshots"]:
                    internal_ts.append((f"snapshot:{snap.get('collection')}", snap.get("captured_at")))
                    collections[snap.get("collection")] += len(snap.get("records", []))
            if "records" in data and "collection" in data:
                collections[data["collection"]] += len(data["records"])
            if "records" in data and "collection" not in data:
                # connector_configurations / export_manifest / security_audit_ledger style
                for rec in data["records"]:
                    rt = rec.get("record_type") or rec.get("system") or "unknown"
                    collections[rt] += 1
            if "service_exports" in data:
                for svc, sub in data["service_exports"].items():
                    for coll, items in sub.items():
                        n = len(items) if isinstance(items, list) else 1
                        collections[f"{svc}.{coll}"] += n

        print(f"\n  {ev.file_id} {ev.file_path}")
        print(f"    manifest captured_at: {ev.captured_at.isoformat()}")
        print(f"    top-level keys: {top_keys}")
        print(f"    internal timestamp(s): {internal_ts[:6]}{' ...' if len(internal_ts) > 6 else ''}")
        print(f"    collections/record counts: {dict(collections)}")
        print(f"    known-email matches (approx): {email_count}")
        results.append(
            {
                "file_id": ev.file_id,
                "path": ev.file_path,
                "format": "json",
                "top_keys": top_keys,
                "collections": dict(collections),
                "email_count": email_count,
            }
        )
    return results


def profile_logs(known_emails, known_hashes):
    print("\n" + "=" * 70)
    print("4. LOG FILES (dataset/evidence/logs/*.log)")
    print("=" * 70)
    family_re = re.compile(r"^(.*?)(?:_[0-9]{8}(?:_[0-9]+)?)?\.log$")
    families = defaultdict(list)
    for ev in sorted(loaders.load_evidence_files(), key=lambda e: e.file_path):
        if not ev.file_path.endswith(".log"):
            continue
        fname = Path(ev.file_path).name
        m = family_re.match(fname)
        family = m.group(1) if m else fname
        families[family].append(ev)

    results = []
    for family, evs in sorted(families.items()):
        ev = evs[0]
        path = DATASET_DIR / ev.file_path
        lines = path.read_text(encoding="utf-8").splitlines()
        sample = lines[min(2, len(lines) - 1)] if lines else ""
        negative_markers = [
            kw
            for kw in ("rows=\"0\"", "rows=0", "result=\"miss\"", "result=miss", "result=\"NOT_FOUND\"", "http_status=\"404\"", "http_status=404")
            if kw in "\n".join(lines[:200])
        ]
        total_email_count = 0
        for ev2 in evs:
            text = (DATASET_DIR / ev2.file_path).read_text(encoding="utf-8")
            total_email_count += count_known_emails_in_text(text, known_emails, known_hashes)
        print(f"\n  family={family} ({len(evs)} file(s): {[e.file_id for e in evs]})")
        print(f"    sample line: {sample[:160]}")
        print(f"    negative-lookup markers seen: {negative_markers}")
        print(f"    total known-email matches across family (approx): {total_email_count}")
        results.append(
            {
                "family": family,
                "file_ids": [e.file_id for e in evs],
                "sample": sample,
                "negative_markers": negative_markers,
                "email_count": total_email_count,
            }
        )
    return results


def profile_pdfs(known_emails, known_hashes):
    print("\n" + "=" * 70)
    print("5. PDFs (dataset/evidence/documents/*.pdf)")
    print("=" * 70)
    import fitz

    results = []
    for ev in sorted(loaders.load_evidence_files(), key=lambda e: e.file_path):
        if not ev.file_path.endswith(".pdf"):
            continue
        path = DATASET_DIR / ev.file_path
        doc = fitz.open(path)
        text = "".join(page.get_text() for page in doc)
        has_text_layer = len(text.strip()) > 20
        email_count = count_known_emails_in_text(text, known_emails, known_hashes)
        print(f"\n  {ev.file_id} {ev.file_path}")
        print(f"    manifest captured_at: {ev.captured_at.isoformat()}")
        print(f"    pages: {doc.page_count}, text layer present: {has_text_layer}, text chars: {len(text)}")
        print(f"    known-email matches (approx): {email_count}")
        results.append(
            {
                "file_id": ev.file_id,
                "path": ev.file_path,
                "pages": doc.page_count,
                "has_text_layer": has_text_layer,
                "email_count": email_count,
            }
        )
        doc.close()
    return results


def profile_images():
    print("\n" + "=" * 70)
    print("6. IMAGES (dataset/evidence/images/*.png) -- count only, no OCR/model")
    print("=" * 70)
    results = []
    for ev in sorted(loaders.load_evidence_files(), key=lambda e: e.file_path):
        if not ev.file_path.endswith(".png"):
            continue
        path = DATASET_DIR / ev.file_path
        size = path.stat().st_size
        print(f"  {ev.file_id} {ev.file_path} manifest captured_at={ev.captured_at.isoformat()} size={size}B")
        results.append({"file_id": ev.file_id, "path": ev.file_path, "size": size})
    return results


def main():
    known_emails, known_hashes = build_known_emails()
    print(f"Known case emails (current + historical): {len(known_emails)}")

    profile_resource_id_prefixes()
    sql_results = profile_sql_files()
    json_results = profile_json_records(known_emails, known_hashes)
    log_results = profile_logs(known_emails, known_hashes)
    pdf_results = profile_pdfs(known_emails, known_hashes)
    image_results = profile_images()

    total_evidence = len(loaders.load_evidence_files())
    print(f"\nTotal evidence files profiled: sql={len(sql_results)} json/text={len(json_results)} "
          f"log_families={len(log_results)} pdf={len(pdf_results)} images={len(image_results)} "
          f"(manifest total={total_evidence})")


if __name__ == "__main__":
    main()
