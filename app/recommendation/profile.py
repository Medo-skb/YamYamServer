from collections import Counter
from collections.abc import Mapping

from app.recommendation.models import PlaceRecord, StampRecord, UserProfile
from app.recommendation.utils import is_recent_date


def build_user_profile(
    user_id: str,
    stamps: list[StampRecord],
    places_by_id: Mapping[str, PlaceRecord],
) -> UserProfile:
    user_stamps = [stamp for stamp in stamps if stamp["userId"] == user_id]
    visited_place_ids: list[str] = []
    recent_visited_place_ids: list[str] = []
    region_counter: Counter[str] = Counter()
    address_prefix_counter: Counter[str] = Counter()
    category_counter: Counter[str] = Counter()

    for stamp in user_stamps:
        place_id = stamp["placeId"]
        place = places_by_id.get(place_id)
        if place is None:
            continue

        visited_place_ids.append(place_id)
        region_counter[place["regionId"]] += 1
        address_parts = place["address"].split()
        if len(address_parts) >= 2:
            address_prefix_counter[" ".join(address_parts[:2])] += 1
        for category_id in place["categoryIds"]:
            category_counter[category_id] += 1
        if is_recent_date(stamp["issuedAt"]):
            recent_visited_place_ids.append(place_id)

    return {
        "visitedPlaceIds": visited_place_ids,
        "recentVisitedPlaceIds": recent_visited_place_ids,
        "topRegionIds": [
            region_id for region_id, _ in region_counter.most_common(3)
        ],
        "topAddressPrefixes": [
            prefix for prefix, _ in address_prefix_counter.most_common(3)
        ],
        "topCategoryIds": [
            category_id for category_id, _ in category_counter.most_common(3)
        ],
    }
