"""Read C v0.3 batches without rewriting C's facts or granting source trust.

This adapter validates transport/provenance, then runs B's existing conservative
review. A successful replay proves interface compatibility, not source truth.
"""

from dataclasses import fields as dataclass_fields, replace
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from .b_io import competition_from_dict
from .evidence_verifier import normalized_value, verify_competition
from .field_catalog import CATALOG_VERSION, build_policy, expected_scope
from .query_planner import plan_queries
from .return_contract import build_return, validate_return
from .source_review import ApprovedSource, SourceSnapshot, review_competition


DATA_KIND = "real_candidate_interface_replay"
NOTICE = (
    "真实候选接口回放：只核验随包资料并生成后续任务，未联网补搜。"
    "来源只使用B单独提供的批准清单；C的来源声明不构成批准。"
    "引文与快照一致仅证明包内追溯关系，不证明快照就是未经改写的网页原文。"
)
_FILES = {
    "candidates": "c_to_b_contests.json",
    "research": "research_batch.json",
    "contexts": "candidate_contexts.json",
    "provenance": "evidence_provenance.json",
    "requirements": "核验条件_基础22字段.json",
}
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
             *(f"LPT{i}" for i in range(1, 10))}


def _load_file(path: Path) -> tuple[Any, bytes]:
    raw = path.read_bytes()
    try:
        return json.loads(raw.decode("utf-8-sig")), raw
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid UTF-8 JSON: {path.name}: {exc}") from exc


def _unique_file(root: Path, name: str) -> Path:
    matches = list(root.rglob(name))
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one {name}, found {len(matches)}")
    path = matches[0].resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"Input file escapes package directory: {name}")
    return path


def _identifier(value: Any, label: str, *, filename: bool = False) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a nonempty string")
    if filename and (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,119}", value)
                     or value.endswith((".", " "))
                     or value.split(".", 1)[0].upper() in _RESERVED):
        raise ValueError(f"Unsafe candidate ID for output filename: {value!r}")
    return value


def _requirements(raw: Any):
    if not isinstance(raw, dict) or set(raw) - {"hard_constraints", "extra_required_fields"}:
        raise ValueError("Base requirements must contain only hard_constraints and extra_required_fields")
    for key, value in raw.items():
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ValueError(f"Requirements {key} must be a list of strings")
    return build_policy(profile="student", **raw)


def _sources(raw: Any) -> tuple[dict, list[SourceSnapshot]]:
    if not isinstance(raw, dict) or not isinstance(raw.get("sources"), list):
        raise ValueError("research_batch.sources must be a list")
    sources, urls, snapshots = {}, set(), []
    for item in raw["sources"]:
        if not isinstance(item, dict):
            raise ValueError("Every research source must be an object")
        source_id = _identifier(item.get("source_id"), "source_id")
        url = normalized_value("url", item.get("url"))
        if url is None:
            raise ValueError(f"Invalid URL for source {source_id}")
        if source_id in sources or url in urls:
            raise ValueError(f"Duplicate source ID or URL: {source_id}")
        if not isinstance(item.get("content"), str) or not item["content"].strip():
            raise ValueError(f"Source {source_id} content must be nonempty text")
        fetched_at = item.get("fetched_at")
        if fetched_at is not None and not isinstance(fetched_at, str):
            raise ValueError(f"Source {source_id} fetched_at must be string or null")
        sources[source_id] = item
        urls.add(url)
        snapshots.append(SourceSnapshot(url=item["url"], text=item["content"], retrieved_at=fetched_at, source_id=source_id))
    return sources, snapshots


def _contexts(raw: Any, candidates: dict, sources: dict) -> dict:
    if not isinstance(raw, list):
        raise ValueError("candidate_contexts must be a list")
    contexts = {}
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("Every candidate context must be an object")
        contest_id = item.get("contest_id")
        if not isinstance(contest_id, str) or contest_id not in candidates or contest_id in contexts:
            raise ValueError(f"Unknown or duplicate context contest_id: {contest_id!r}")
        refs = item.get("source_ids")
        if not isinstance(refs, list) or any(not isinstance(ref, str) or ref not in sources for ref in refs):
            raise ValueError(f"Invalid context source references: {contest_id}")
        if len(refs) != len(set(refs)):
            raise ValueError(f"Duplicate context source references: {contest_id}")
        context = item.get("context")
        if not isinstance(context, dict) or any(not isinstance(key, str) or not isinstance(value, str)
                                                for key, value in context.items()):
            raise ValueError(f"Context must map text keys to text values: {contest_id}")
        contexts[contest_id] = item
    if set(contexts) != set(candidates):
        raise ValueError("Every candidate needs exactly one context record")
    return contexts


def _provenance(raw: Any, candidates: dict, contexts: dict, sources: dict) -> dict:
    if not isinstance(raw, list):
        raise ValueError("evidence_provenance must be a list")
    evidence = {}
    for candidate in candidates.values():
        for item in candidate.evidence:
            key = candidate.id, item.id
            if key in evidence or not item.id.strip():
                raise ValueError(f"Duplicate or empty evidence ID: {candidate.id}/{item.id}")
            evidence[key] = item
    mapped = {contest_id: [] for contest_id in candidates}
    seen = set()
    for row in raw:
        if not isinstance(row, dict):
            raise ValueError("Every provenance record must be an object")
        contest_id, evidence_id = row.get("contest_id"), row.get("evidence_id")
        if not isinstance(contest_id, str) or not isinstance(evidence_id, str):
            raise ValueError("Provenance contest_id and evidence_id must be strings")
        key = contest_id, evidence_id
        if key not in evidence or key in seen:
            raise ValueError(f"Unknown or duplicate provenance evidence: {key}")
        item = evidence[key]
        candidate = candidates[contest_id]
        source_id = row.get("source_id")
        if not isinstance(source_id, str) or source_id not in sources or source_id not in contexts[contest_id]["source_ids"]:
            raise ValueError(f"Invalid provenance source reference: {key}")
        source = sources[source_id]
        for field, expected in (("field", item.field), ("edition", item.edition), ("scope", item.scope)):
            if row.get(field) != expected:
                raise ValueError(f"Provenance {field} mismatch: {key}")
        if item.edition != candidate.edition or item.scope != expected_scope(candidate, item.field):
            raise ValueError(f"Evidence edition/scope does not match candidate target: {key}")
        urls = [normalized_value("url", value) for value in (row.get("url"), item.url, source["url"])]
        if None in urls or len(set(urls)) != 1:
            raise ValueError(f"Provenance URL mismatch: {key}")
        start, end = row.get("start_char"), row.get("end_char")
        content = source["content"]
        if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(content):
            raise ValueError(f"Invalid provenance quote span: {key}")
        if content[start:end] != item.quote:
            raise ValueError(f"Provenance quote span does not match evidence: {key}")
        if row.get("content_sha256") != hashlib.sha256(content.encode("utf-8")).hexdigest():
            raise ValueError(f"Provenance content SHA256 mismatch: {key}")
        seen.add(key)
        mapped[contest_id].append(row)
    if seen != set(evidence):
        raise ValueError("Every evidence record needs exactly one provenance record")
    return mapped


def _annotations(contexts: dict, contexts_file: Path, root: Path) -> tuple[dict, list]:
    """Preserve only explicitly referenced context annotations, without edits."""
    preserved, records = {}, []
    seen = set()
    reserved = {filename.casefold() for filename in _FILES.values()} | {"b_context_holds.json"}
    for item in contexts.values():
        if "annotation_file" not in item:
            continue
        reference = item["annotation_file"]
        if not isinstance(reference, str) or not reference.strip():
            raise ValueError("Context annotation_file must be a nonempty relative path")
        relative = Path(reference)
        if relative.is_absolute() or relative.drive or ".." in relative.parts:
            raise ValueError(f"Unsafe context annotation_file: {reference!r}")
        path = (contexts_file.parent / relative).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError(f"Missing or escaped context annotation_file: {reference!r}")
        destination = f"inputs/{relative.as_posix()}"
        folded = relative.as_posix().casefold()
        if folded in reserved:
            raise ValueError(f"Context annotation_file collides with preserved JSON: {reference!r}")
        if folded in seen:
            continue
        seen.add(folded)
        content = path.read_bytes()
        preserved[destination] = content
        records.append({"path": str(path.relative_to(root)), "preserved_file": destination,
                        "sha256": hashlib.sha256(content).hexdigest()})
    return preserved, records


def _approvals(path: Path | None, root: Path, candidates: dict, sources: dict) -> tuple[list, dict | None]:
    if path is None:
        return [], None
    path = Path(path).resolve()
    if path.is_relative_to(root):
        raise ValueError("B approval file must be outside C's incoming package")
    raw, content = _load_file(path)
    if not isinstance(raw, dict) or set(raw) != {"approved_sources"} or not isinstance(raw["approved_sources"], list):
        raise ValueError("B approval file must contain only an approved_sources list")
    allowed = {field.name for field in dataclass_fields(ApprovedSource)}
    source_urls = {normalized_value("url", item["url"]) for item in sources.values()}
    result = []
    for row in raw["approved_sources"]:
        if not isinstance(row, dict) or set(row) != allowed or any(not isinstance(value, str) or not value.strip() for value in row.values()):
            raise ValueError("B approved source must contain all ApprovedSource string fields")
        candidate = candidates.get(row["competition_id"])
        if candidate is None or row["edition"] != candidate.edition:
            raise ValueError("B approval refers to an unknown candidate or edition")
        scopes = {expected_scope(candidate, field) for field in candidate.fields}
        if row["scope"] not in scopes or normalized_value("url", row["url"]) not in source_urls:
            raise ValueError("B approval refers to unknown scope or snapshot URL")
        if row["source_type"] not in {"official", "school", "third_party"}:
            raise ValueError("B approval source_type is invalid")
        result.append(ApprovedSource(**row))
    return result, {"path": str(path), "sha256": hashlib.sha256(content).hexdigest(), "count": len(result)}


def _context_holds(path: Path | None, root: Path, candidates: dict) -> tuple[dict, dict | None, bytes | None]:
    if path is None:
        return {}, None, None
    path = Path(path).resolve()
    if path.is_relative_to(root):
        raise ValueError("B context hold file must be outside C's incoming package")
    raw, content = _load_file(path)
    if isinstance(raw, list):
        raw = {"context_holds": raw}
    if not isinstance(raw, dict) or set(raw) != {"context_holds"} or not isinstance(raw["context_holds"], list):
        raise ValueError("B context hold file must contain only a context_holds list")
    holds = {}
    for item in raw["context_holds"]:
        if not isinstance(item, dict) or set(item) != {"competition_id", "field", "reason"}:
            raise ValueError("Every context hold requires competition_id, field and reason")
        if any(not isinstance(value, str) or not value.strip() for value in item.values()):
            raise ValueError("Context hold values must be nonempty strings")
        key = item["competition_id"], item["field"]
        if key[0] not in candidates or key[1] not in candidates[key[0]].fields or key in holds:
            raise ValueError(f"Unknown or duplicate context hold target: {key}")
        holds[key] = item["reason"]
    return holds, {"path": str(path), "sha256": hashlib.sha256(content).hexdigest(),
                   "holds": raw["context_holds"], "preserved_file": "inputs/b_context_holds.json"}, content


def run_batch(package_root, output_dir, approved_sources_path=None, context_holds_path=None) -> dict:
    """Validate a C batch and emit a new B replay directory, with no network.

    The output directory must not exist. Inputs, context, provenance and incoming
    scopes remain unchanged. Approvals are optional, separate B-owned records.
    """
    root, output = Path(package_root).resolve(), Path(output_dir).resolve()
    if not root.is_dir():
        raise ValueError("C package_root must be an existing directory")
    if output.is_relative_to(root):
        raise ValueError("Output directory must be outside the incoming C package")
    if output.exists():
        raise ValueError("Output directory already exists; choose a new directory to preserve previous results")
    loaded, raw_bytes, paths = {}, {}, {}
    for key, filename in _FILES.items():
        paths[key] = _unique_file(root, filename)
        loaded[key], raw_bytes[key] = _load_file(paths[key])
    raw_candidates = loaded["candidates"]
    if not isinstance(raw_candidates, list) or not raw_candidates:
        raise ValueError("c_to_b_contests must be a nonempty array")
    candidates, folded_ids = {}, set()
    for raw in raw_candidates:
        candidate = competition_from_dict(raw)
        _identifier(candidate.id, "candidate ID", filename=True)
        if candidate.id.casefold() in folded_ids:
            raise ValueError(f"Duplicate candidate ID: {candidate.id}")
        folded_ids.add(candidate.id.casefold())
        candidates[candidate.id] = candidate
    policy = _requirements(loaded["requirements"])
    sources, snapshots = _sources(loaded["research"])
    contexts = _contexts(loaded["contexts"], candidates, sources)
    provenance = _provenance(loaded["provenance"], candidates, contexts, sources)
    annotations, annotation_manifest = _annotations(contexts, paths["contexts"], root)
    approvals, approval_manifest = _approvals(approved_sources_path, root, candidates, sources)
    holds, holds_manifest, holds_bytes = _context_holds(context_holds_path, root, candidates)

    outputs, entries = {}, []
    for raw in raw_candidates:
        candidate = candidates[raw["id"]]
        reviewed, reviews = review_competition(candidate, approved_sources=approvals, snapshots=snapshots)
        verification = verify_competition(reviewed, policy)
        for (contest_id, field), reason in holds.items():
            if contest_id != candidate.id:
                continue
            check = verification.fields.get(field)
            if check is None or check.status == "verified":
                raise ValueError(f"Context hold may only route an assessed unresolved field: {contest_id}/{field}")
            check.next_action = "clarify_context"
            check.action_reason = reason
        context = contexts[candidate.id]
        # Context is C's search targeting hint, not a field-level B judgment.
        # Global fields omit campus-only hints to avoid narrowing national queries.
        queries = []
        for query in plan_queries(reviewed, verification):
            hints = {key: value for key, value in context["context"].items()
                     if key in ({"parent_track", "track"} if query.scope == "global"
                                else {"school", "unit", "parent_track", "track", "stage"})}
            if hints:
                suffix = " ".join(f"{key}={value}" for key, value in hints.items())
                query = replace(query, text=f"{query.text} [C提供的检索上下文，未经独立核验：{suffix}]")
            queries.append(query)
        envelope = build_return(reviewed, verification, reviews, queries,
                                data_kind=DATA_KIND, notice=NOTICE)
        receipt = validate_return(envelope, raw)
        # The per-candidate result already preserves the complete payload.
        receipt = {key: value for key, value in receipt.items() if key != "received_payload"}
        relative = f"results/{candidate.id}.json"
        outputs[relative] = envelope
        entries.append({
            "competition_id": candidate.id, "result_file": relative,
            "status": verification.status, "coverage": verification.coverage,
            "required_field_count": len(verification.required_fields),
            "assessed_field_count": len(verification.fields),
            "optional_fields_not_assessed": [name for name in candidate.fields if name not in verification.fields],
            "evidence_count": len(candidate.evidence), "search_request_count": len(queries),
            "source_review_count": len(reviews), "source_verified_count": sum(review.evidence.source_verified for review in reviews),
            "context_record": context, "provenance_records": provenance[candidate.id],
            "contract_check": receipt,
            "scope_policy": "original_scopes_preserved_no_automatic_school_national_correction",
        })
    report = {
        "data_kind": DATA_KIND, "notice": NOTICE, "catalog_version": CATALOG_VERSION,
        "candidate_count": len(candidates), "source_count": len(sources),
        "evidence_count": sum(len(candidate.evidence) for candidate in candidates.values()),
        "source_review_count": sum(entry["source_review_count"] for entry in entries),
        "source_verified_count": sum(entry["source_verified_count"] for entry in entries),
        "contract_checks_passed": len(entries), "c_runtime_executed": False,
        "real_search_executed": False, "required_fields": list(policy.required_fields),
        "promoted_fields": list(policy.promoted_fields),
        "source_approval_mode": "explicit_b_file" if approved_sources_path is not None else "none",
        "context_semantically_verified": False, "snapshot_web_authenticity_verified": False,
        "context_hold_count": len(holds),
        "candidates": [{key: entry[key] for key in (
            "competition_id", "result_file", "status", "coverage", "required_field_count",
            "assessed_field_count", "optional_fields_not_assessed", "evidence_count", "search_request_count",
        )} for entry in entries],
    }
    manifest = {
        "data_kind": DATA_KIND, "package_root": str(root),
        "input_files": {key: {"path": str(paths[key].relative_to(root)),
                              "sha256": hashlib.sha256(raw_bytes[key]).hexdigest(),
                              "preserved_file": f"inputs/{_FILES[key]}"} for key in _FILES},
        "approved_sources": approval_manifest, "context_holds": holds_manifest,
        "input_annotations": annotation_manifest,
        "source_mapping": "content -> text; fetched_at -> retrieved_at",
        "context_policy": "preserved_per_id; query_hints_only; not_independently_verified",
        "provenance_policy": "all_evidence_spans_hashes_references_validated_against_packaged_content",
        "c_runtime_executed": False, "candidates": entries,
    }
    # Serialize all envelopes before creating anything; invalid input leaves no output.
    outputs["manifest.json"], outputs["report.json"] = manifest, report
    serialized = {name: (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
                  for name, value in outputs.items()}
    serialized.update({f"inputs/{_FILES[key]}": content for key, content in raw_bytes.items()})
    serialized.update(annotations)
    if holds_bytes is not None:
        serialized["inputs/b_context_holds.json"] = holds_bytes
    output.mkdir(parents=True, exist_ok=False)
    for name, content in serialized.items():
        path = output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return report
