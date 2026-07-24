import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from firebase_admin import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from gifticon_purchase import ensure_firebase_app


logger = logging.getLogger(__name__)

_KST = timezone(timedelta(hours=9))
_PERIOD_CONDITION_TYPES = (
    "weekly_stamp",
    "monthly_stamp",
    "yearly_stamp",
)
_TRANSACTION_CHUNK_SIZE = 400


def grant_earned_badges_safely(
    *,
    user_id: str,
    road_id: str | None,
) -> dict[str, Any]:
    failed_conditions: list[str] = []
    try:
        new_badges = grant_earned_badges(
            user_id=user_id,
            road_id=road_id,
            _failed_conditions=failed_conditions,
        )
        return {
            "status": "partial" if failed_conditions else "completed",
            "newBadges": new_badges,
            "failedConditions": failed_conditions,
        }
    except Exception:
        logger.exception(
            "스탬프 발행 후 뱃지 지급 중 오류가 발생했습니다: "
            "user_id=%s, road_id=%s",
            user_id,
            road_id,
        )
        return {
            "status": "failed",
            "newBadges": [],
            "failedConditions": failed_conditions,
        }


def grant_earned_badges(
    *,
    user_id: str,
    road_id: str | None,
    now: datetime | None = None,
    _failed_conditions: list[str] | None = None,
) -> list[dict[str, Any]]:
    normalized_user_id = user_id.strip()
    normalized_road_id = (road_id or "").strip() or None
    if not normalized_user_id:
        raise ValueError("user_id가 비어 있습니다.")

    ensure_firebase_app()
    database = firestore.client()
    badge_collection = database.collection("badge")
    current_time = _as_utc(now or datetime.now(timezone.utc))
    earned_candidates: dict[str, dict[str, Any]] = {}
    failed_conditions = (
        _failed_conditions
        if _failed_conditions is not None
        else []
    )

    try:
        stamp_count_badges = _active_badges_by_condition(
            badge_collection,
            "stamp_count",
        )
        if stamp_count_badges:
            total_stamp_count = _count_stamps(
                database,
                user_id=normalized_user_id,
            )
            _collect_met_count_badges(
                earned_candidates,
                stamp_count_badges,
                current_count=total_stamp_count,
            )
    except Exception:
        failed_conditions.append("stamp_count")
        logger.exception(
            "누적 스탬프 뱃지 검사 실패: user_id=%s",
            normalized_user_id,
        )

    for condition_type in _PERIOD_CONDITION_TYPES:
        try:
            period_badges = _active_badges_by_condition(
                badge_collection,
                condition_type,
            )
            if not period_badges:
                continue
            period_stamp_count = _count_stamps(
                database,
                user_id=normalized_user_id,
                issued_at_from=_period_start(
                    current_time,
                    condition_type,
                ),
            )
            _collect_met_count_badges(
                earned_candidates,
                period_badges,
                current_count=period_stamp_count,
            )
        except Exception:
            failed_conditions.append(condition_type)
            logger.exception(
                "기간 뱃지 검사 실패: user_id=%s, condition_type=%s",
                normalized_user_id,
                condition_type,
            )

    if normalized_road_id is not None:
        try:
            road_badges = _active_road_badges(
                badge_collection,
                normalized_road_id,
            )
            if road_badges:
                road_progress = _road_progress_percent(
                    database,
                    user_id=normalized_user_id,
                    road_id=normalized_road_id,
                )
                for badge_id, badge_data in road_badges:
                    required_percent = _as_non_negative_float(
                        badge_data.get("requiredPercent"),
                        default=100.0,
                    )
                    if road_progress >= required_percent:
                        earned_candidates[badge_id] = badge_data
        except Exception:
            failed_conditions.append("road_progress")
            logger.exception(
                "로드 진행도 뱃지 검사 실패: user_id=%s, road_id=%s",
                normalized_user_id,
                normalized_road_id,
            )

    if not earned_candidates:
        return []

    already_earned_ids = _find_already_earned_badges(
        database,
        user_id=normalized_user_id,
        badge_ids=list(earned_candidates),
    )
    new_candidates = [
        (badge_id, badge_data)
        for badge_id, badge_data in earned_candidates.items()
        if badge_id not in already_earned_ids
    ]
    if not new_candidates:
        return []

    granted_ids = _grant_badge_documents(
        database,
        user_id=normalized_user_id,
        candidates=new_candidates,
    )
    return [
        _public_badge(badge_id, badge_data)
        for badge_id, badge_data in new_candidates
        if badge_id in granted_ids
    ]


def _active_badges_by_condition(
    badge_collection,
    condition_type: str,
) -> list[tuple[str, dict[str, Any]]]:
    query = badge_collection.where(
        filter=FieldFilter("conditionType", "==", condition_type)
    )
    return _active_badges(query.stream())


def _active_road_badges(
    badge_collection,
    road_id: str,
) -> list[tuple[str, dict[str, Any]]]:
    query = badge_collection.where(
        filter=FieldFilter("targetRoadId", "==", road_id)
    )
    return [
        (badge_id, badge_data)
        for badge_id, badge_data in _active_badges(query.stream())
        if badge_data.get("conditionType") == "road_progress"
    ]


def _active_badges(
    documents: Iterable,
) -> list[tuple[str, dict[str, Any]]]:
    active_badges: list[tuple[str, dict[str, Any]]] = []
    for document in documents:
        data = document.to_dict() or {}
        if data.get("isActive") is True:
            active_badges.append((document.id, data))
    return active_badges


def _collect_met_count_badges(
    destination: dict[str, dict[str, Any]],
    badges: list[tuple[str, dict[str, Any]]],
    *,
    current_count: int,
) -> None:
    for badge_id, badge_data in badges:
        required_count = _as_non_negative_int(
            badge_data.get("requiredStampCount"),
            default=9999,
        )
        if current_count >= required_count:
            destination[badge_id] = badge_data


def _count_stamps(
    database,
    *,
    user_id: str,
    issued_at_from: datetime | None = None,
) -> int:
    query = database.collection("stamp").where(
        filter=FieldFilter("userId", "==", user_id)
    )
    if issued_at_from is not None:
        query = query.where(
            filter=FieldFilter(
                "issuedAt",
                ">=",
                issued_at_from,
            )
        )
    results = list(query.count().get())
    if not results:
        return 0
    first_row = results[0]
    first_result = (
        first_row[0]
        if isinstance(first_row, (tuple, list))
        else first_row
    )
    return _as_non_negative_int(getattr(first_result, "value", 0))


def _road_progress_percent(
    database,
    *,
    user_id: str,
    road_id: str,
) -> float:
    road_snapshot = database.collection("road").document(road_id).get()
    if not road_snapshot.exists:
        return 0.0

    road_data = road_snapshot.to_dict() or {}
    place_ids = _road_place_ids(road_data)
    if place_ids:
        stamp_query = (
            database.collection("stamp")
            .where(filter=FieldFilter("userId", "==", user_id))
            .where(filter=FieldFilter("roadId", "==", road_id))
        )
        visited_place_ids = {
            str((snapshot.to_dict() or {}).get("placeId") or "").strip()
            for snapshot in stamp_query.stream()
        }
        visited_place_ids.discard("")
        completed_count = len(visited_place_ids.intersection(place_ids))
        return min((completed_count / len(place_ids)) * 100.0, 100.0)

    total_stamp_count = _as_non_negative_int(
        road_data.get("totalStampCount"),
    )
    if total_stamp_count <= 0:
        return 0.0
    completed_count = _count_road_stamps(
        database,
        user_id=user_id,
        road_id=road_id,
    )
    return min((completed_count / total_stamp_count) * 100.0, 100.0)


def _count_road_stamps(
    database,
    *,
    user_id: str,
    road_id: str,
) -> int:
    query = (
        database.collection("stamp")
        .where(filter=FieldFilter("userId", "==", user_id))
        .where(filter=FieldFilter("roadId", "==", road_id))
    )
    results = list(query.count().get())
    if not results:
        return 0
    first_row = results[0]
    first_result = (
        first_row[0]
        if isinstance(first_row, (tuple, list))
        else first_row
    )
    return _as_non_negative_int(getattr(first_result, "value", 0))


def _road_place_ids(road_data: dict[str, Any]) -> set[str]:
    raw_places = road_data.get("placeIds")
    if not isinstance(raw_places, list):
        raw_places = road_data.get("roadPlace")
    if not isinstance(raw_places, list):
        return set()

    place_ids: set[str] = set()
    for item in raw_places:
        if isinstance(item, dict):
            value = item.get("placeId") or item.get("id")
        else:
            value = item
        normalized = str(value or "").strip()
        if normalized:
            place_ids.add(normalized)
    return place_ids


def _find_already_earned_badges(
    database,
    *,
    user_id: str,
    badge_ids: list[str],
) -> set[str]:
    user_badges = (
        database.collection("users")
        .document(user_id)
        .collection("users_badge")
    )
    earned_ids: set[str] = set()

    for badge_id_chunk in _chunks(badge_ids, 100):
        references = [
            user_badges.document(badge_id)
            for badge_id in badge_id_chunk
        ]
        for snapshot in database.get_all(references):
            if snapshot.exists:
                earned_ids.add(snapshot.id)

    # 기존 Flutter 서비스가 자동 문서 ID로 저장한 데이터와도 호환한다.
    for badge_id in badge_ids:
        if badge_id in earned_ids:
            continue
        legacy_query = (
            user_badges.where(
                filter=FieldFilter("badgeId", "==", badge_id)
            )
            .limit(1)
        )
        if list(legacy_query.stream()):
            earned_ids.add(badge_id)

    return earned_ids


def _grant_badge_documents(
    database,
    *,
    user_id: str,
    candidates: list[tuple[str, dict[str, Any]]],
) -> set[str]:
    user_badges = (
        database.collection("users")
        .document(user_id)
        .collection("users_badge")
    )
    granted_ids: set[str] = set()

    for candidate_chunk in _chunks(candidates, _TRANSACTION_CHUNK_SIZE):
        transaction = database.transaction()

        @firestore.transactional
        def grant_chunk(current_transaction):
            missing: list[tuple[str, Any]] = []
            for badge_id, _ in candidate_chunk:
                badge_ref = user_badges.document(badge_id)
                snapshot = badge_ref.get(transaction=current_transaction)
                if not snapshot.exists:
                    missing.append((badge_id, badge_ref))

            for badge_id, badge_ref in missing:
                current_transaction.set(
                    badge_ref,
                    {
                        "badgeId": badge_id,
                        "earnedAt": firestore.SERVER_TIMESTAMP,
                        "isSelected": False,
                    },
                )
            return [badge_id for badge_id, _ in missing]

        granted_ids.update(grant_chunk(transaction))

    return granted_ids


def _period_start(
    now: datetime,
    condition_type: str,
) -> datetime:
    local_now = _as_utc(now).astimezone(_KST)
    if condition_type == "weekly_stamp":
        start = datetime(
            local_now.year,
            local_now.month,
            local_now.day,
            tzinfo=_KST,
        ) - timedelta(days=local_now.weekday())
    elif condition_type == "monthly_stamp":
        start = datetime(
            local_now.year,
            local_now.month,
            1,
            tzinfo=_KST,
        )
    elif condition_type == "yearly_stamp":
        start = datetime(local_now.year, 1, 1, tzinfo=_KST)
    else:
        raise ValueError(f"지원하지 않는 기간 조건입니다: {condition_type}")
    return start.astimezone(timezone.utc)


def _public_badge(
    badge_id: str,
    badge_data: dict[str, Any],
) -> dict[str, Any]:
    return {
        "badgeId": badge_id,
        "name": str(badge_data.get("name") or "뱃지"),
        "imageUrl": str(badge_data.get("imageUrl") or ""),
        "conditionType": str(badge_data.get("conditionType") or ""),
    }


def _chunks(values: list[Any], size: int) -> Iterable[list[Any]]:
    for index in range(0, len(values), size):
        yield values[index : index + size]


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _as_non_negative_int(
    value: Any,
    default: int = 0,
) -> int:
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return default


def _as_non_negative_float(
    value: Any,
    default: float = 0.0,
) -> float:
    try:
        return max(float(value), 0.0)
    except (TypeError, ValueError):
        return default
