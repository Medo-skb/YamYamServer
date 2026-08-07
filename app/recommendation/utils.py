from datetime import datetime, timedelta
from math import atan2, cos, radians, sin, sqrt
from typing import Final


MAX_CURRENT_LOCATION_DISTANCE_METERS: Final = 10_000.0
RELATED_CATEGORY_IDS: Final = {
    "bakery": ["cafe", "dessert"],
    "cafe": ["bakery", "dessert"],
    "dessert": ["bakery", "cafe"],
}


def distance_meters(lat1, lng1, lat2, lng2):
    earth_radius = 6_371_000
    d_lat = radians(lat2 - lat1)
    d_lng = radians(lng2 - lng1)
    a = (
        sin(d_lat / 2) ** 2
        + cos(radians(lat1))
        * cos(radians(lat2))
        * sin(d_lng / 2) ** 2
    )
    return earth_radius * 2 * atan2(sqrt(a), sqrt(1 - a))


def rank_score(value, ranked_values, scores):
    if value not in ranked_values:
        return 0
    index = ranked_values.index(value)
    return scores[index] if index < len(scores) else 0


def calculate_popularity_score(stamp_count: int, rating_average: float) -> int:
    score = 0
    if stamp_count >= 100:
        score += 3
    elif stamp_count >= 20:
        score += 2
    elif stamp_count >= 5:
        score += 1

    if rating_average >= 4.5:
        score += 2
    elif rating_average >= 4:
        score += 1
    return score


def is_recent_date(date_text, days=30):
    try:
        target_date = datetime.strptime(date_text, "%Y-%m-%d")
    except ValueError:
        return False
    return target_date >= datetime.now() - timedelta(days=days)
