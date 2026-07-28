from __future__ import annotations

from threading import Lock
from time import monotonic
from typing import Final

from google.cloud.firestore_v1 import GeoPoint

from recommendation_models import CourseCoordinate, CourseRecord


MAX_COURSES: Final = 300
COURSE_CACHE_TTL_SECONDS: Final = 300.0


class _CourseCache:
    """Caches rarely-changing course documents to reduce Firestore reads."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._expires_at = 0.0
        self._courses: tuple[CourseRecord, ...] = ()

    def load(self, database) -> list[CourseRecord]:
        now = monotonic()
        with self._lock:
            if now < self._expires_at:
                return list(self._courses)

            courses = [
                course
                for snapshot in database.collection("road")
                .limit(MAX_COURSES)
                .stream()
                if (course := _snapshot_to_course(snapshot)) is not None
                and course["isActive"]
            ]
            self._courses = tuple(courses)
            self._expires_at = now + COURSE_CACHE_TTL_SECONDS
            return list(courses)


_course_cache = _CourseCache()


def load_courses(database) -> list[CourseRecord]:
    return _course_cache.load(database)


def _snapshot_to_course(snapshot) -> CourseRecord | None:
    data = snapshot.to_dict() or {}
    title = str(data.get("title") or "").strip()
    place_ids = _as_string_list(data.get("roadPlace") or data.get("placeIds"))
    if not title or not place_ids:
        return None

    coordinates: list[CourseCoordinate] = []
    for value in data.get("placeCoordinates") or []:
        if isinstance(value, GeoPoint):
            coordinates.append({"lat": value.latitude, "lng": value.longitude})
            continue
        if not isinstance(value, dict):
            continue
        lat = _as_float(value.get("lat"))
        lng = _as_float(value.get("lng"))
        if lat is not None and lng is not None:
            coordinates.append({"lat": lat, "lng": lng})

    return {
        "courseId": snapshot.id,
        "title": title,
        "regionId": str(
            data.get("regionId") or data.get("region") or "전체"
        ).strip(),
        "categoryIds": _as_string_list(data.get("categoryIds")),
        "placeIds": place_ids,
        "placeCoordinates": coordinates,
        "isActive": data.get("isActive") is not False,
    }


def _as_string_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [text for item in value if (text := str(item).strip())]


def _as_float(value) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    try:
        return float(str(value))
    except ValueError:
        return None
