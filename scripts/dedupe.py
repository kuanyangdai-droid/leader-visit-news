from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any, Dict, Iterable, List, Tuple


Record = Dict[str, Any]


def normalize_name(value: str | None) -> str:
    text = (value or "").strip().lower()
    text = re.sub(r"\b(president|prime minister|premier|chancellor|minister|foreign minister|secretary|king|queen)\b", "", text)
    text = re.sub(r"[\W_]+", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def names_match(left: str | None, right: str | None, threshold: float = 0.86) -> bool:
    a = normalize_name(left)
    b = normalize_name(right)
    if not a or not b:
        return False
    if a == b:
        return True
    return SequenceMatcher(None, a, b).ratio() >= threshold


def published_date(record: Record) -> str:
    value = str(record.get("published_at") or "")
    return value[:10] if len(value) >= 10 else ""


def dedupe_key(record: Record) -> Tuple[str, str, str]:
    leader = normalize_name(record.get("leader_name"))
    visit_date = str(record.get("visit_date") or "").strip()
    destination = str(record.get("destination") or "").strip().lower()
    if leader and visit_date:
        return ("leader_visit_date", leader, visit_date)
    if leader and destination:
        return ("leader_destination_publish_date", leader, f"{destination}|{published_date(record)}")
    return ("source_url", str(record.get("source_url") or record.get("id") or ""))


def is_duplicate(existing: Record, candidate: Record) -> bool:
    existing_date = str(existing.get("visit_date") or "").strip()
    candidate_date = str(candidate.get("visit_date") or "").strip()
    if existing_date and candidate_date and existing_date == candidate_date:
        if normalize_name(existing.get("leader_name")) == normalize_name(candidate.get("leader_name")):
            return True
        if names_match(existing.get("leader_name"), candidate.get("leader_name")):
            return True

    if not candidate_date:
        same_publish_day = published_date(existing) == published_date(candidate)
        same_destination = str(existing.get("destination") or "").strip().lower() == str(candidate.get("destination") or "").strip().lower()
        if same_publish_day and same_destination and names_match(existing.get("leader_name"), candidate.get("leader_name")):
            return True

    if existing.get("source_url") and existing.get("source_url") == candidate.get("source_url"):
        return True
    return False


def completeness_score(record: Record) -> int:
    important_fields = (
        "leader_name",
        "leader_title",
        "country",
        "visit_date",
        "event_type",
        "destination",
        "summary",
        "source_url",
        "published_at",
    )
    return sum(1 for field in important_fields if record.get(field))


def merge_record(existing: Record, candidate: Record) -> Record:
    merged = dict(existing)
    candidate_score = completeness_score(candidate)
    existing_score = completeness_score(existing)

    for key, value in candidate.items():
        if key == "created_at":
            continue
        if value in (None, "", []):
            continue
        if not merged.get(key):
            merged[key] = value
        elif candidate_score > existing_score and key in {"summary", "source_url", "source_name", "destination", "event_type"}:
            merged[key] = value

    merged["updated_at"] = candidate.get("updated_at") or existing.get("updated_at")
    return merged


def dedupe_records(existing_records: Iterable[Record], new_records: Iterable[Record]) -> List[Record]:
    result: List[Record] = [dict(item) for item in existing_records if isinstance(item, dict)]

    for candidate in new_records:
        if not isinstance(candidate, dict):
            continue
        match_index = next((idx for idx, item in enumerate(result) if is_duplicate(item, candidate)), None)
        if match_index is None:
            result.append(dict(candidate))
        else:
            result[match_index] = merge_record(result[match_index], candidate)

    result.sort(key=lambda item: str(item.get("published_at") or item.get("updated_at") or ""), reverse=True)
    return result
