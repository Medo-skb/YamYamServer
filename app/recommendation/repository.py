from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from firebase_admin import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from app.core.firebase import ensure_firebase_app
from app.recommendation.course_repository import load_courses
from app.recommendation.models import (
    PlaceRecord,
    RecommendationDataset,
    StampRecord,
)


MAX_STAMP_HISTORY: Final = 200
MAX_PLACE_CANDIDATES: Final = 120
MAX_CATEGORY_CANDIDATES: Final = 60
DISTRICT_CANDIDATE_LIMITS: Final = (60, 40, 20)


@dataclass(frozen=True, slots=True)
class _CandidateSelection:
    region_ids: tuple[str, ...]
    category_ids: tuple[str, ...]
    address_prefixes: tuple[str, ...]


def load_recommendation_dataset(
    *,
    user_id: str,
    current_region_id: str | None,
) -> RecommendationDataset:
    ensure_firebase_app()
    database = firestore.client()

    stamps = _load_stamps(database, user_id)
    visited_place_ids = list(dict.fromkeys(stamp["placeId"] for stamp in stamps))
    visited_places = _load_places_by_ids(database, visited_place_ids)

    region_counter: Counter[str] = Counter(
        place["regionId"] for place in visited_places
    )
    category_counter: Counter[str] = Counter(
        category_id
        for place in visited_places
        for category_id in place["categoryIds"]
    )
    address_prefix_counter: Counter[str] = Counter()
    for place in visited_places:
        address_parts = place["address"].split()
        if len(address_parts) >= 2:
            address_prefix_counter[" ".join(address_parts[:2])] += 1

    normalized_region_id = (current_region_id or "").strip()
    if normalized_region_id and normalized_region_id != "전체":
        candidate_region_ids = [normalized_region_id]
    else:
        candidate_region_ids = [
            region_id for region_id, _ in region_counter.most_common(3)
        ]
    top_category_ids = [
        category_id for category_id, _ in category_counter.most_common(3)
    ]
    address_prefixes = (
        ()
        if normalized_region_id and normalized_region_id != "전체"
        else tuple(
            prefix for prefix, _ in address_prefix_counter.most_common(3)
        )
    )

    candidates = _load_candidate_places(
        database,
        _CandidateSelection(
            region_ids=tuple(candidate_region_ids),
            category_ids=tuple(top_category_ids),
            address_prefixes=address_prefixes,
        ),
    )
    places_by_id = {
        place["placeId"]: place for place in [*candidates, *visited_places]
    }

    return {
        "places": list(places_by_id.values()),
        "courses": load_courses(database),
        "stamps": stamps,
    }


def _load_stamps(database, user_id: str) -> list[StampRecord]:
    snapshots = (
        database.collection("stamp")
        .where(filter=FieldFilter("userId", "==", user_id))
        .limit(MAX_STAMP_HISTORY)
        .stream()
    )
    stamps = [
        stamp
        for snapshot in snapshots
        if (stamp := _snapshot_to_stamp(snapshot, user_id)) is not None
    ]
    stamps.sort(key=lambda stamp: stamp["issuedAt"], reverse=True)
    return stamps


def _load_places_by_ids(database, place_ids: list[str]) -> list[PlaceRecord]:
    places: list[PlaceRecord] = []
    for start in range(0, len(place_ids), 100):
        references = [
            database.collection("place").document(place_id)
            for place_id in place_ids[start : start + 100]
        ]
        places.extend(
            place
            for snapshot in database.get_all(references)
            if (place := _snapshot_to_place(snapshot)) is not None
        )
    return places


def _load_candidate_places(
    database,
    selection: _CandidateSelection,
) -> list[PlaceRecord]:
    snapshots_by_id = {}

    if selection.address_prefixes:
        for index, prefix in enumerate(selection.address_prefixes):
            address_query = (
                database.collection("place")
                .where(filter=FieldFilter("address", ">=", prefix))
                .where(filter=FieldFilter("address", "<", f"{prefix}\uf8ff"))
            )
            limit = DISTRICT_CANDIDATE_LIMITS[index]
            for snapshot in address_query.limit(limit).stream():
                snapshots_by_id[snapshot.id] = snapshot
    elif selection.region_ids:
        region_query = database.collection("place").where(
            filter=FieldFilter("regionId", "in", list(selection.region_ids[:10]))
        )
        for snapshot in region_query.limit(MAX_PLACE_CANDIDATES).stream():
            snapshots_by_id[snapshot.id] = snapshot

    if selection.category_ids and not selection.address_prefixes:
        category_query = database.collection("place").where(
            filter=FieldFilter(
                "categoryIds",
                "array_contains_any",
                list(selection.category_ids[:10]),
            )
        )
        for snapshot in category_query.limit(MAX_CATEGORY_CANDIDATES).stream():
            snapshots_by_id[snapshot.id] = snapshot

    if not snapshots_by_id:
        fallback_query = database.collection("place").order_by(
            "stampCount",
            direction=firestore.Query.DESCENDING,
        )
        for snapshot in fallback_query.limit(MAX_CATEGORY_CANDIDATES).stream():
            snapshots_by_id[snapshot.id] = snapshot

    return [
        place
        for snapshot in snapshots_by_id.values()
        if (place := _snapshot_to_place(snapshot)) is not None
        and place["isActive"]
    ]


def _snapshot_to_place(snapshot) -> PlaceRecord | None:
    if not snapshot.exists:
        return None
    data = snapshot.to_dict() or {}
    name = str(data.get("name") or "").strip()
    region_id = str(data.get("regionId") or "").strip()
    lat = _as_float(data.get("lat"))
    lng = _as_float(data.get("lng"))
    if not name or not region_id or lat is None or lng is None:
        return None

    return {
        "placeId": snapshot.id,
        "name": name,
        "address": str(data.get("address") or "").strip(),
        "regionId": region_id,
        "categoryIds": _as_string_list(data.get("categoryIds")),
        "lat": lat,
        "lng": lng,
        "ratingAverage": _as_float(data.get("ratingAverage")) or 0.0,
        "stampCount": _as_non_negative_int(data.get("stampCount")),
        "isActive": data.get("isActive") is not False,
    }


def _snapshot_to_stamp(snapshot, user_id: str) -> StampRecord | None:
    data = snapshot.to_dict() or {}
    place_id = str(data.get("placeId") or "").strip()
    if not place_id:
        return None
    issued_at = data.get("issuedAt")
    return {
        "stampId": snapshot.id,
        "userId": user_id,
        "placeId": place_id,
        "courseId": _as_nullable_string(
            data.get("roadId") or data.get("courseId")
        ),
        "issuedAt": (
            issued_at.date().isoformat()
            if isinstance(issued_at, datetime)
            else str(issued_at or "")
        ),
    }


def _as_string_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        text
        for item in value
        if (text := str(item).strip())
    ]


def _as_nullable_string(value) -> str | None:
    text = str(value or "").strip()
    return text or None


def _as_float(value) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    try:
        return float(str(value))
    except ValueError:
        return None


def _as_non_negative_int(value) -> int:
    if isinstance(value, bool):
        return 0
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0
