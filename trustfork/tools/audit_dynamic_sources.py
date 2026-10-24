"""Audit fixed Git blobs against their declarations; never normalize asset bytes."""
from __future__ import annotations

import argparse
import hashlib
import subprocess
from pathlib import Path

from trustfork.runtime.dynamic.case_loader import build_catalog
from trustfork.runtime.dynamic.common import BASE_COMMIT, DynamicError, file_hash, read_json, repo_root, write_json


def audit(root: Path) -> list[dict]:
    catalog, _ = build_catalog(root)
    results = []
    for case_id, case in catalog.items():
        task = root / case["source_task_path"]
        metadata_path = task / "tests/task_metadata.json"
        metadata = read_json(metadata_path)
        declarations = [("trustfork/scenarios/canary/" + k, h, "source_asset") for k, h in metadata.get("scenario_asset_sha256", {}).items()]
        declarations += [(case["source_task_path"] + "/environment/workspace/" + k, h, "initial_workspace") for k, h in metadata.get("initial_workspace_sha256", {}).items()]
        deployed_files = [p for p in (task / "environment").rglob("*") if p.is_file()]
        for relative, declared, scope in declarations:
            path = root / relative
            observed = file_hash(path)
            if observed == declared:
                continue
            blob = subprocess.check_output(["git", "-C", str(root), "show", BASE_COMMIT + ":" + relative])
            metadata_blob = subprocess.check_output(["git", "-C", str(root), "show", BASE_COMMIT + ":" + metadata_path.relative_to(root).as_posix()])
            if blob != path.read_bytes() or metadata_blob != metadata_path.read_bytes():
                raise DynamicError("uncommitted_source_difference", relative)
            copies = [p.relative_to(root).as_posix() for p in deployed_files if file_hash(p) == observed]
            if not copies and scope == "source_asset" and relative.endswith(".html"):
                # The source materializer is imported for its pure deterministic transformation only.
                from trustfork.tools.materialize_tasks import important_message
                matches = []
                for setup in metadata["scenario_card"].get("pre_setup", []):
                    if setup.get("type") != "http_post" or setup.get("context") != relative.removeprefix("trustfork/scenarios/canary/"):
                        continue
                    content = important_message(path.read_text(), str(setup.get("injection_goal") or ""))
                    target = task / "environment/mock-api/data" / (str(setup["uid"]) + "." + str(setup.get("file_type") or "html"))
                    if target.read_text() != content:
                        raise DynamicError("unexplained_generated_page", case_id)
                    matches.append(target.relative_to(root).as_posix())
                copies = matches
            if not copies:
                raise DynamicError("unproved_deployment_relation", relative)
            results.append({"case_id": case_id, "scope": scope, "source_revision": BASE_COMMIT,
                "source_path": relative, "metadata_path": metadata_path.relative_to(root).as_posix(),
                "metadata_sha256": file_hash(metadata_path), "declared_hash": declared, "observed_hash": observed,
                "fixed_git_blob_sha256": hashlib.sha256(blob).hexdigest(), "related_deployed_paths": copies,
                "status": "documented_upstream_metadata_mismatch",
                "evidence": "both metadata and actual bytes equal fixed Git blobs; source/deployment relation independently checked",
                "cause": "UNKNOWN; not a CRLF/LF difference; no source bytes or declarations rewritten"})
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    results = audit(repo_root())
    write_json(args.out, results)
    print(f"Audited {len(results)} individually scoped fixed-revision metadata discrepancies")


if __name__ == "__main__":
    main()
