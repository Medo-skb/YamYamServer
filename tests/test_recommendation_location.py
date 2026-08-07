from unittest.mock import Mock, patch

from app.recommendation import repository
from app.recommendation.messages import (
    build_course_recommendations,
    build_place_recommendations,
)
from app.recommendation.service import calculate_course_score, calculate_place_score


def test_current_location_uses_only_current_region_candidates() -> None:
    # Given
    database = Mock()
    with (
        patch.object(repository, "ensure_firebase_app"),
        patch.object(repository.firestore, "client", return_value=database),
        patch.object(repository, "_load_stamps", return_value=[]),
        patch.object(repository, "_load_places_by_ids", return_value=[]),
        patch.object(repository, "_load_candidate_places", return_value=[]) as loader,
        patch.object(repository, "load_courses", return_value=[]),
    ):
        # When
        repository.load_recommendation_dataset(
            user_id="test_user",
            current_region_id="region_incheon",
        )

    # Then
    loader.assert_called_once_with(
        database,
        loader.call_args.args[1],
    )
    selection = loader.call_args.args[1]
    assert selection.region_ids == ("region_incheon",)
    assert selection.category_ids == ()
    assert selection.address_prefixes == ()


def test_distant_place_is_excluded_when_current_location_is_used() -> None:
    # Given
    place = {
        "placeId": "jongno_place",
        "name": "종로 카페",
        "address": "서울특별시 종로구",
        "regionId": "region_seoul",
        "categoryIds": ["cafe"],
        "lat": 37.573,
        "lng": 126.979,
        "ratingAverage": 5.0,
        "stampCount": 100,
        "isActive": True,
    }
    profile = {
        "visitedPlaceIds": [],
        "recentVisitedPlaceIds": [],
        "topRegionIds": ["region_seoul"],
        "topAddressPrefixes": [],
        "topCategoryIds": ["cafe"],
    }

    # When
    result = calculate_place_score(
        place=place,
        profile=profile,
        current_region_id="region_incheon",
        user_lat=37.493,
        user_lng=126.724,
    )

    # Then
    assert result is None


def test_distant_place_remains_eligible_without_current_location() -> None:
    # Given
    place = {
        "placeId": "jongno_place",
        "name": "종로 카페",
        "address": "서울특별시 종로구",
        "regionId": "region_seoul",
        "categoryIds": ["cafe"],
        "lat": 37.573,
        "lng": 126.979,
        "ratingAverage": 5.0,
        "stampCount": 100,
        "isActive": True,
    }
    profile = {
        "visitedPlaceIds": [],
        "recentVisitedPlaceIds": [],
        "topRegionIds": ["region_seoul"],
        "topAddressPrefixes": [],
        "topCategoryIds": ["cafe"],
    }

    # When
    result = calculate_place_score(
        place=place,
        profile=profile,
        current_region_id=None,
        user_lat=None,
        user_lng=None,
    )

    # Then
    assert result is not None


def test_distant_course_is_excluded_when_current_location_is_used() -> None:
    # Given
    course = {
        "courseId": "jongno_course",
        "title": "종로 디저트 코스",
        "regionId": "region_seoul",
        "categoryIds": ["cafe"],
        "placeIds": ["jongno_place"],
        "placeCoordinates": [{"lat": 37.573, "lng": 126.979}],
        "isActive": True,
    }
    profile = {
        "visitedPlaceIds": [],
        "recentVisitedPlaceIds": [],
        "topRegionIds": ["region_seoul"],
        "topAddressPrefixes": [],
        "topCategoryIds": ["cafe"],
    }

    # When
    result = calculate_course_score(
        course=course,
        profile=profile,
        current_region_id="region_incheon",
        user_lat=37.493,
        user_lng=126.724,
    )

    # Then
    assert result is None


def test_recently_visited_place_receives_twelve_point_penalty() -> None:
    # Given
    place = {
        "placeId": "visited_place",
        "name": "방문한 카페",
        "address": "인천광역시 부평구",
        "regionId": "region_incheon",
        "categoryIds": ["cafe"],
        "lat": 37.493,
        "lng": 126.724,
        "ratingAverage": 0.0,
        "stampCount": 0,
        "isActive": True,
    }
    base_profile = {
        "visitedPlaceIds": [],
        "recentVisitedPlaceIds": [],
        "topRegionIds": [],
        "topAddressPrefixes": [],
        "topCategoryIds": [],
    }
    visited_profile = {
        **base_profile,
        "visitedPlaceIds": [place["placeId"]],
        "recentVisitedPlaceIds": [place["placeId"]],
    }

    # When
    unvisited_result = calculate_place_score(
        place, base_profile, "region_incheon", 37.493, 126.724
    )
    visited_result = calculate_place_score(
        place, visited_profile, "region_incheon", 37.493, 126.724
    )

    # Then
    assert unvisited_result is not None
    assert visited_result is not None
    assert unvisited_result["score"] - visited_result["score"] == 12


def test_previously_visited_place_receives_six_point_penalty() -> None:
    # Given
    place = {
        "placeId": "visited_place",
        "name": "방문한 카페",
        "address": "인천광역시 부평구",
        "regionId": "region_incheon",
        "categoryIds": ["cafe"],
        "lat": 37.493,
        "lng": 126.724,
        "ratingAverage": 0.0,
        "stampCount": 0,
        "isActive": True,
    }
    base_profile = {
        "visitedPlaceIds": [],
        "recentVisitedPlaceIds": [],
        "topRegionIds": [],
        "topAddressPrefixes": [],
        "topCategoryIds": [],
    }
    visited_profile = {
        **base_profile,
        "visitedPlaceIds": [place["placeId"]],
    }

    # When
    unvisited_result = calculate_place_score(
        place, base_profile, "region_incheon", 37.493, 126.724
    )
    visited_result = calculate_place_score(
        place, visited_profile, "region_incheon", 37.493, 126.724
    )

    # Then
    assert unvisited_result is not None
    assert visited_result is not None
    assert unvisited_result["score"] - visited_result["score"] == 6


def test_recommendation_lists_are_limited_to_top_three() -> None:
    # Given
    place_results = [
        {
            "placeId": f"place_{index}",
            "name": f"업체 {index}",
            "address": "인천광역시",
            "reasons": [],
        }
        for index in range(4)
    ]
    course_results = [
        {
            "courseId": f"course_{index}",
            "title": f"코스 {index}",
            "visitedRatio": 0.0,
            "reasons": [],
        }
        for index in range(4)
    ]

    # When
    places = build_place_recommendations(place_results)
    courses = build_course_recommendations(course_results)

    # Then
    assert [place["placeId"] for place in places] == [
        "place_0",
        "place_1",
        "place_2",
    ]
    assert [course["courseId"] for course in courses] == [
        "course_0",
        "course_1",
        "course_2",
    ]
