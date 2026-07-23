from math import radians, sin, cos, sqrt, atan2
from datetime import datetime, timedelta
from collections import Counter

def build_place_message(place_results):
    if len(place_results) == 0:
        return {
            "recommend": None,
            "reasons": ["지금 추천할 만한 업체를 찾지 못했어요."]
        }

    top_place = place_results[0]
    reasons = top_place["reasons"]

    reason_texts = []

    if any("현재 지역" in reason for reason in reasons):
        reason_texts.append("지금 있는 지역과 가까워요.")

    if any("자주 방문한 지역" in reason for reason in reasons):
        reason_texts.append("평소 자주 가던 지역에 있어요.")

    if any("선호 카테고리" in reason for reason in reasons):
        reason_texts.append("선호하는 메뉴와 잘 맞아요.")

    if any("유사 카테고리" in reason for reason in reasons):
        reason_texts.append("이전에 좋아한 메뉴와 비슷한 계열이에요.")

    if any("300m" in reason or "1km" in reason for reason in reasons):
        reason_texts.append("거리도 부담이 적어요.")

    if len(reason_texts) == 0:
        reason_texts.append("전체 추천 점수가 가장 높아요.")

    return {
        "recommend": top_place["name"],
        "reasons": reason_texts[:3],
    }


def build_course_message(course_results):
    if len(course_results) == 0:
        return {
            "recommend": None,
            "reasons": ["지금 추천할 만한 코스를 찾지 못했어요."]
        }

    top_course = course_results[0]
    reasons = top_course["reasons"]

    reason_texts = []

    if any("현재 지역" in reason for reason in reasons):
        reason_texts.append("현재 위치한 지역과 잘 맞는 코스예요.")

    if any("자주 방문한 지역" in reason for reason in reasons):
        reason_texts.append("평소 자주 가던 곳이라 동선이 익숙할 수 있어요.")

    if any("선호 카테고리" in reason for reason in reasons):
        reason_texts.append("선호하는 메뉴 구성이 포함돼 있어요.")

    if any("코스 내 업체" in reason for reason in reasons):
        reason_texts.append("가까운 위치에서 시작하기 좋아요.")

    if len(reason_texts) == 0:
        reason_texts.append("지금 가볍게 둘러보기 좋은 코스에요.")

    return {
        "recommend": top_course["title"],
        "reasons": reason_texts[:3],
    }


def build_recommendation_message(place_results, course_results):
    return {
        "place": build_place_message(place_results),
        "course": build_course_message(course_results),
    }

# =========================
# 임시 데이터
# 나중에 Firestore 조회 결과로 교체할 부분
# =========================

PLACES = [
    {
        "placeId": "place_001",
        "name": "성수 베이커리",
        "regionId": "region_seongsu",
        "categoryIds": ["bakery"],
        "lat": 37.5447,
        "lng": 127.0557,
        "isActive": True,
    },
    {
        "placeId": "place_002",
        "name": "성수 카페",
        "regionId": "region_seongsu",
        "categoryIds": ["cafe"],
        "lat": 37.5452,
        "lng": 127.0571,
        "isActive": True,
    },
    {
        "placeId": "place_003",
        "name": "홍대 디저트",
        "regionId": "region_hongdae",
        "categoryIds": ["dessert"],
        "lat": 37.5563,
        "lng": 126.9220,
        "isActive": True,
    },
    {
        "placeId": "place_004",
        "name": "강남 베이커리",
        "regionId": "region_gangnam",
        "categoryIds": ["bakery", "cafe"],
        "lat": 37.4979,
        "lng": 127.0276,
        "isActive": True,
    },
]

COURSES = [
    {
        "courseId": "course_001",
        "title": "성수 디저트 코스",
        "regionId": "region_seongsu",
        "categoryIds": ["bakery", "cafe"],
        "isActive": True,
    },
    {
        "courseId": "course_002",
        "title": "홍대 디저트 코스",
        "regionId": "region_hongdae",
        "categoryIds": ["dessert", "cafe"],
        "isActive": True,
    },
]

COURSE_PLACES = [
    {"courseId": "course_001", "placeId": "place_001", "order": 1},
    {"courseId": "course_001", "placeId": "place_002", "order": 2},
    {"courseId": "course_002", "placeId": "place_003", "order": 1},
]

STAMPS = [
    {
        "stampId": "stamp_001",
        "userId": "test_user_001",
        "placeId": "place_001",
        "courseId": "course_001",
        "issuedAt": "2026-07-10",
    },
    {
        "stampId": "stamp_002",
        "userId": "test_user_001",
        "placeId": "place_004",
        "courseId": None,
        "issuedAt": "2026-06-20",
    },
]

# 유사 카테고리는 지금 DB에 없으니까 코드에서 임시 관리
RELATED_CATEGORY_IDS = {
    "bakery": ["cafe", "dessert"],
    "cafe": ["bakery", "dessert"],
    "dessert": ["bakery", "cafe"],
}


# =========================
# 공통 유틸
# =========================

def distance_meters(lat1, lng1, lat2, lng2):
    earth_radius = 6371000

    d_lat = radians(lat2 - lat1)
    d_lng = radians(lng2 - lng1)

    a = (
        sin(d_lat / 2) ** 2
        + cos(radians(lat1))
        * cos(radians(lat2))
        * sin(d_lng / 2) ** 2
    )

    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return earth_radius * c


def rank_score(value, ranked_values, scores):
    if value not in ranked_values:
        return 0

    index = ranked_values.index(value)

    if index >= len(scores):
        return 0

    return scores[index]


def get_place(place_id):
    for place in PLACES:
        if place["placeId"] == place_id:
            return place

    return None


def get_course_place_ids(course_id):
    items = [
        item for item in COURSE_PLACES
        if item["courseId"] == course_id
    ]

    items.sort(key=lambda x: x["order"])
    return [item["placeId"] for item in items]


def is_recent_date(date_text, days=30):
    try:
        target_date = datetime.strptime(date_text, "%Y-%m-%d")
    except ValueError:
        return False

    return target_date >= datetime.now() - timedelta(days=days)


# =========================
# 사용자 프로필 계산
# =========================

def build_user_profile(user_id):
    user_stamps = [
        stamp for stamp in STAMPS
        if stamp["userId"] == user_id
    ]

    visited_place_ids = []
    recent_visited_place_ids = []
    region_counter = Counter()
    category_counter = Counter()

    for stamp in user_stamps:
        place_id = stamp["placeId"]
        place = get_place(place_id)

        if place is None:
            continue

        visited_place_ids.append(place_id)
        region_counter[place["regionId"]] += 1

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
        "topCategoryIds": [
            category_id for category_id, _ in category_counter.most_common(3)
        ],
    }


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

        if distance <= 300:
            score += 8
            reasons.append("300m 이내 +8")
        elif distance <= 1000:
            score += 5
            reasons.append("1km 이내 +5")
        elif distance <= 3000:
            score += 2
            reasons.append("3km 이내 +2")
        elif distance >= 10000:
            score -= 3
            reasons.append("10km 이상 -3")

    # 5. 방문 이력 감점
    place_id = place["placeId"]

    if place_id in profile["recentVisitedPlaceIds"]:
        score -= 8
        reasons.append("최근 방문 업체 -8")
    elif place_id in profile["visitedPlaceIds"]:
        score -= 3
        reasons.append("방문 이력 있음 -3")

    return {
        "placeId": place["placeId"],
        "name": place["name"],
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

    course_place_ids = get_course_place_ids(course["courseId"])

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

        for place_id in course_place_ids:
            place = get_place(place_id)

            if place is None:
                continue

            distances.append(
                distance_meters(
                    user_lat,
                    user_lng,
                    place["lat"],
                    place["lng"],
                )
            )

        if len(distances) > 0:
            nearest_distance = min(distances)

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
    profile = build_user_profile(userId)

    place_results = []

    for place in PLACES:
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

    for course in COURSES:
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
        "placeRecommendations": place_results[:5],
        "courseRecommendations": course_results[:5],
    }