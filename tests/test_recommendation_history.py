from unittest.mock import Mock, patch

from app.recommendation import repository
from app.recommendation.service import build_user_profile, calculate_place_score


def test_user_profile_ranks_frequently_visited_districts() -> None:
    # Given
    places_by_id = {
        "seongsu_1": {
            "placeId": "seongsu_1",
            "address": "서울특별시 성동구 성수이로 1",
            "regionId": "region_seoul",
            "categoryIds": ["cafe"],
        },
        "seongsu_2": {
            "placeId": "seongsu_2",
            "address": "서울특별시 성동구 성수이로 2",
            "regionId": "region_seoul",
            "categoryIds": ["cafe"],
        },
        "jongno_1": {
            "placeId": "jongno_1",
            "address": "서울특별시 종로구 인사동길 1",
            "regionId": "region_seoul",
            "categoryIds": ["cafe"],
        },
    }
    stamps = [
        {"userId": "user", "placeId": "seongsu_1", "issuedAt": "2026-01-01"},
        {"userId": "user", "placeId": "seongsu_2", "issuedAt": "2026-01-02"},
        {"userId": "user", "placeId": "jongno_1", "issuedAt": "2026-01-03"},
    ]

    # When
    profile = build_user_profile("user", stamps, places_by_id)

    # Then
    assert profile["topAddressPrefixes"] == [
        "서울특별시 성동구",
        "서울특별시 종로구",
    ]


def test_frequently_visited_district_receives_higher_score() -> None:
    # Given
    profile = {
        "visitedPlaceIds": [],
        "recentVisitedPlaceIds": [],
        "topRegionIds": ["region_seoul"],
        "topAddressPrefixes": ["서울특별시 성동구", "서울특별시 종로구"],
        "topCategoryIds": ["cafe"],
    }
    common = {
        "categoryIds": ["cafe"],
        "regionId": "region_seoul",
        "lat": 37.55,
        "lng": 127.04,
        "ratingAverage": 0.0,
        "stampCount": 0,
        "isActive": True,
    }
    seongdong = {
        **common,
        "placeId": "seongdong",
        "name": "성동 카페",
        "address": "서울특별시 성동구 성수이로 1",
    }
    jongno = {
        **common,
        "placeId": "jongno",
        "name": "종로 카페",
        "address": "서울특별시 종로구 인사동길 1",
    }

    # When
    seongdong_result = calculate_place_score(
        seongdong, profile, None, None, None
    )
    jongno_result = calculate_place_score(jongno, profile, None, None, None)

    # Then
    assert seongdong_result is not None
    assert jongno_result is not None
    assert seongdong_result["score"] - jongno_result["score"] == 3


def test_popularity_score_is_preserved_during_scoring_refactor() -> None:
    # Given
    profile = {
        "visitedPlaceIds": [],
        "recentVisitedPlaceIds": [],
        "topRegionIds": [],
        "topAddressPrefixes": [],
        "topCategoryIds": [],
    }
    place = {
        "placeId": "popular",
        "name": "인기 카페",
        "address": "서울특별시 성동구 성수이로 1",
        "regionId": "region_seoul",
        "categoryIds": ["cafe"],
        "lat": 37.55,
        "lng": 127.04,
        "ratingAverage": 4.5,
        "stampCount": 100,
        "isActive": True,
    }

    # When
    result = calculate_place_score(place, profile, None, None, None)

    # Then
    assert result is not None
    assert result["score"] == 5


def test_visit_history_candidates_use_district_prefixes() -> None:
    # Given
    database = Mock()
    visited_places = [
        {
            "placeId": "seongsu_1",
            "name": "성수 카페 1",
            "address": "서울특별시 성동구 성수이로 1",
            "regionId": "region_seoul",
            "categoryIds": ["cafe"],
            "lat": 37.55,
            "lng": 127.04,
            "ratingAverage": 0.0,
            "stampCount": 0,
            "isActive": True,
        },
        {
            "placeId": "seongsu_2",
            "name": "성수 카페 2",
            "address": "서울특별시 성동구 성수이로 2",
            "regionId": "region_seoul",
            "categoryIds": ["cafe"],
            "lat": 37.55,
            "lng": 127.04,
            "ratingAverage": 0.0,
            "stampCount": 0,
            "isActive": True,
        },
        {
            "placeId": "jongno_1",
            "name": "종로 카페",
            "address": "서울특별시 종로구 인사동길 1",
            "regionId": "region_seoul",
            "categoryIds": ["cafe"],
            "lat": 37.57,
            "lng": 126.98,
            "ratingAverage": 0.0,
            "stampCount": 0,
            "isActive": True,
        },
    ]
    stamps = [
        {"placeId": place["placeId"]}
        for place in visited_places
    ]
    with (
        patch.object(repository, "ensure_firebase_app"),
        patch.object(repository.firestore, "client", return_value=database),
        patch.object(repository, "_load_stamps", return_value=stamps),
        patch.object(repository, "_load_places_by_ids", return_value=visited_places),
        patch.object(repository, "_load_candidate_places", return_value=[]) as loader,
        patch.object(repository, "load_courses", return_value=[]),
    ):
        # When
        repository.load_recommendation_dataset(
            user_id="user",
            current_region_id=None,
        )

    # Then
    selection = loader.call_args.args[1]
    assert selection.address_prefixes == (
        "서울특별시 성동구",
        "서울특별시 종로구",
    )
