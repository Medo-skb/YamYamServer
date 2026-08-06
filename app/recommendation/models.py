from typing import TypedDict


class PlaceRecord(TypedDict):
    placeId: str
    name: str
    address: str
    regionId: str
    categoryIds: list[str]
    lat: float
    lng: float
    ratingAverage: float
    stampCount: int
    isActive: bool


class CourseCoordinate(TypedDict):
    lat: float
    lng: float


class CourseRecord(TypedDict):
    courseId: str
    title: str
    regionId: str
    categoryIds: list[str]
    placeIds: list[str]
    placeCoordinates: list[CourseCoordinate]
    isActive: bool


class StampRecord(TypedDict):
    stampId: str
    userId: str
    placeId: str
    courseId: str | None
    issuedAt: str


class RecommendationDataset(TypedDict):
    places: list[PlaceRecord]
    courses: list[CourseRecord]
    stamps: list[StampRecord]
