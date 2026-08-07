def build_place_reason_texts(reasons):
    reason_texts = []

    if any("현재 지역" in reason for reason in reasons):
        reason_texts.append("지금 있는 지역과 가까워요.")
    if any("자주 방문한 지역" in reason for reason in reasons):
        reason_texts.append("평소 자주 가던 지역에 있어요.")
    if any("자주 방문한 구/군" in reason for reason in reasons):
        reason_texts.append("평소 자주 가던 동네에 있어요.")
    if any("선호 카테고리" in reason for reason in reasons):
        reason_texts.append("선호하는 메뉴와 잘 맞아요.")
    if any("유사 카테고리" in reason for reason in reasons):
        reason_texts.append("이전에 좋아한 메뉴와 비슷한 계열이에요.")
    if any(
        "300m" in reason or "1km" in reason or "3km" in reason
        for reason in reasons
    ):
        reason_texts.append("거리도 부담이 적어요.")
    if any("인기 지표" in reason for reason in reasons):
        reason_texts.append("방문과 평가 지표가 좋은 곳이에요.")
    if len(reason_texts) == 0:
        reason_texts.append("현재 조건에서 잘 맞는 곳이에요.")

    return reason_texts[:3]


def build_place_message(place_results):
    if len(place_results) == 0:
        return {
            "recommend": None,
            "reasons": ["지금 추천할 만한 업체를 찾지 못했어요."],
        }

    top_place = place_results[0]

    return {
        "recommend": top_place["name"],
        "reasons": build_place_reason_texts(top_place["reasons"]),
    }


def build_place_recommendations(place_results):
    return [
        {
            "placeId": result["placeId"],
            "name": result["name"],
            "address": result["address"],
            "reasons": build_place_reason_texts(result["reasons"]),
        }
        for result in place_results[:3]
    ]


def build_course_reason_texts(reasons):
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
        reason_texts.append("지금 가볍게 둘러보기 좋은 코스예요.")

    return reason_texts[:3]


def build_course_message(course_results):
    if len(course_results) == 0:
        return {
            "recommend": None,
            "reasons": ["지금 추천할 만한 코스를 찾지 못했어요."],
        }

    top_course = course_results[0]

    return {
        "recommend": top_course["title"],
        "reasons": build_course_reason_texts(top_course["reasons"]),
    }


def build_course_recommendations(course_results):
    return [
        {
            "courseId": result["courseId"],
            "title": result["title"],
            "visitedRatio": result["visitedRatio"],
            "reasons": build_course_reason_texts(result["reasons"]),
        }
        for result in course_results[:3]
    ]


def build_recommendation_message(place_results, course_results):
    return {
        "place": build_place_message(place_results),
        "course": build_course_message(course_results),
    }
