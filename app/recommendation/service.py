from app.recommendation.messages import (
    build_course_recommendations,
    build_place_recommendations,
    build_recommendation_message,
)
from app.recommendation.profile import build_user_profile
from app.recommendation.repository import load_recommendation_dataset
from app.recommendation.utils import (
    MAX_CURRENT_LOCATION_DISTANCE_METERS,
    RELATED_CATEGORY_IDS,
    calculate_popularity_score,
    distance_meters,
    rank_score,
)


# =========================
# 업체 추천 점수
# =========================

def calculate_place_score(place, profile, current_region_id, user_lat, user_lng):
    score = 0
    reasons = []

    if not place["isActive"]:
        return None

    # 1. 현재 지역 일치
    if current_region_id and place["regionId"] == current_region_id:
        score += 3
        reasons.append("현재 지역 일치 +3")

    # 2. 사용자가 자주 방문한 지역
    region_score = rank_score(
        place["regionId"],
        profile["topRegionIds"],
        [5, 3, 1],
    )

    if region_score > 0:
        score += region_score
        reasons.append(f"자주 방문한 지역 +{region_score}")

    address_prefix = " ".join(place["address"].split()[:2])
    address_score = rank_score(
        address_prefix, profile["topAddressPrefixes"], [6, 3, 1]
    )
    if address_score > 0:
        score += address_score
        reasons.append(f"자주 방문한 구/군 +{address_score}")

    # 3. 선호 카테고리 / 유사 카테고리
    category_added = False

    for category_id in place["categoryIds"]:
        category_score = rank_score(
            category_id,
            profile["topCategoryIds"],
            [5, 3, 1],
        )

        if category_score > 0:
            score += category_score
            reasons.append(f"선호 카테고리 +{category_score}")
            category_added = True
            break

    if not category_added:
        for preferred_category_id in profile["topCategoryIds"]:
            related_ids = RELATED_CATEGORY_IDS.get(preferred_category_id, [])

            if any(category_id in related_ids for category_id in place["categoryIds"]):
                score += 2
                reasons.append("유사 카테고리 +2")
                break

    # 4. GPS 거리 점수
    if user_lat is not None and user_lng is not None:
        distance = distance_meters(
            user_lat,
            user_lng,
            place["lat"],
            place["lng"],
        )
        if distance > MAX_CURRENT_LOCATION_DISTANCE_METERS:
            return None

        if distance <= 300:
            score += 8
            reasons.append("300m 이내 +8")
        elif distance <= 1000:
            score += 5
            reasons.append("1km 이내 +5")
        elif distance <= 3000:
            score += 2
            reasons.append("3km 이내 +2")

    # 5. 방문 이력 감점
    place_id = place["placeId"]

    if place_id in profile["recentVisitedPlaceIds"]:
        score -= 12
        reasons.append("최근 방문 업체 -12")
    elif place_id in profile["visitedPlaceIds"]:
        score -= 6
        reasons.append("방문 이력 있음 -6")

    popularity_score = calculate_popularity_score(
        place.get("stampCount", 0), place.get("ratingAverage", 0)
    )

    if popularity_score > 0:
        score += popularity_score
        reasons.append(f"인기 지표 +{popularity_score}")

    return {
        "placeId": place["placeId"],
        "name": place["name"],
        "address": place["address"],
        "score": score,
        "reasons": reasons,
    }


# =========================
# 코스 추천 점수
# =========================

def calculate_course_score(course, profile, current_region_id, user_lat, user_lng):
    score = 0
    reasons = []

    if not course["isActive"]:
        return None

    course_place_ids = course["placeIds"]

    if len(course_place_ids) == 0:
        return None

    visited_count = len([
        place_id for place_id in course_place_ids
        if place_id in profile["visitedPlaceIds"]
    ])

    visited_ratio = visited_count / len(course_place_ids)

    # 코스는 이미 다 방문했으면 추천에서 제외
    if visited_ratio >= 1:
        return None

    # 1. 현재 지역 일치
    if current_region_id and course["regionId"] == current_region_id:
        score += 3
        reasons.append("현재 지역 일치 +3")

    # 2. 자주 방문한 지역
    region_score = rank_score(
        course["regionId"],
        profile["topRegionIds"],
        [5, 3, 1],
    )

    if region_score > 0:
        score += region_score
        reasons.append(f"자주 방문한 지역 +{region_score}")

    # 3. 선호 카테고리
    for category_id in course["categoryIds"]:
        category_score = rank_score(
            category_id,
            profile["topCategoryIds"],
            [5, 3, 1],
        )

        if category_score > 0:
            score += category_score
            reasons.append(f"선호 카테고리 +{category_score}")
            break

    # 4. 코스 내 일부 방문 감점
    if visited_ratio >= 0.5:
        score -= 10
        reasons.append("코스 절반 이상 방문 -10")
    elif visited_ratio > 0:
        score -= 3
        reasons.append("코스 일부 방문 -3")

    # 5. GPS 기준 가까운 코스 보정
    if user_lat is not None and user_lng is not None:
        distances = []

        for coordinate in course["placeCoordinates"]:
            distances.append(
                distance_meters(
                    user_lat,
                    user_lng,
                    coordinate["lat"],
                    coordinate["lng"],
                )
            )

        if len(distances) > 0:
            if (nearest_distance := min(distances)) > MAX_CURRENT_LOCATION_DISTANCE_METERS:
                return None

            if nearest_distance <= 1000:
                score += 5
                reasons.append("코스 내 업체 1km 이내 +5")
            elif nearest_distance <= 3000:
                score += 2
                reasons.append("코스 내 업체 3km 이내 +2")

    return {
        "courseId": course["courseId"],
        "title": course["title"],
        "score": score,
        "visitedRatio": visited_ratio,
        "reasons": reasons,
    }


# =========================
# 추천 API 진입점
# =========================

def recommend(
    userId: str,
    currentRegionId: str | None = None,
    userLat: float | None = None,
    userLng: float | None = None,
):
    dataset = load_recommendation_dataset(
        user_id=userId,
        current_region_id=currentRegionId,
    )
    places = dataset["places"]
    courses = dataset["courses"]
    places_by_id = {place["placeId"]: place for place in places}
    profile = build_user_profile(
        userId,
        dataset["stamps"],
        places_by_id,
    )

    place_results = []

    for place in places:
        result = calculate_place_score(
            place=place,
            profile=profile,
            current_region_id=currentRegionId,
            user_lat=userLat,
            user_lng=userLng,
        )

        if result is not None:
            place_results.append(result)

    place_results.sort(key=lambda x: x["score"], reverse=True)

    course_results = []

    for course in courses:
        result = calculate_course_score(
            course=course,
            profile=profile,
            current_region_id=currentRegionId,
            user_lat=userLat,
            user_lng=userLng,
        )

        if result is not None:
            course_results.append(result)

    course_results.sort(key=lambda x: x["score"], reverse=True)

    messages = build_recommendation_message(
        place_results=place_results,
        course_results=course_results,
    )

    return {
        "userId": userId,
        "currentRegionId": currentRegionId,
        "userLat": userLat,
        "userLng": userLng,
        "message": messages,
        "placeRecommendations": build_place_recommendations(place_results),
        "courseRecommendations": build_course_recommendations(course_results),
    }
