import hashlib
import math
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4
from firebase_admin import firestore, storage

from gifticon_purchase import ensure_firebase_app


MAX_RECEIPT_BYTES = 10 * 1024 * 1024
_KST = timezone(timedelta(hours=9))
_ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}


class StampVerificationError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def issue_dev_stamp(
    *,
    user_id: str,
    place_id: str,
    rating: int = 5,
    one_line_note: str | None = None,
) -> dict[str, Any]:
    if os.getenv("STAMP_DEV_BYPASS_ENABLED", "").strip().lower() not in {
        "1",
        "true",
        "yes",
        "on",
    }:
        raise StampVerificationError(
            code="dev_bypass_disabled",
            message="개발용 스탬프 즉시 발행 기능이 비활성화되어 있습니다.",
            status_code=403,
        )
    if not user_id or not place_id.strip():
        raise StampVerificationError(
            code="invalid_argument",
            message="사용자 ID와 업체 ID가 필요합니다.",
            status_code=422,
        )
    if rating < 1 or rating > 5:
        raise StampVerificationError(
            code="invalid_rating",
            message="별점은 1점부터 5점까지 입력할 수 있습니다.",
            status_code=422,
        )
    if one_line_note is not None and len(one_line_note.strip()) > 100:
        raise StampVerificationError(
            code="note_too_long",
            message="한줄 기록은 100자 이하여야 합니다.",
            status_code=422,
        )

    ensure_firebase_app()
    database = firestore.client()
    user_ref = database.collection("users").document(user_id)
    place_ref = database.collection("place").document(place_id)
    dev_id = f"dev_{uuid4().hex}"
    verification_ref = database.collection("verification").document(dev_id)
    stamp_ref = database.collection("stamp").document(dev_id)
    point_transaction_ref = user_ref.collection(
        "users_point_transaction"
    ).document(f"stamp_{dev_id}")
    reward_point = _non_negative_int_env("STAMP_REWARD_POINT", 0)
    transaction = database.transaction()

    @firestore.transactional
    def execute_dev_issue(current_transaction):
        current_user = user_ref.get(transaction=current_transaction)
        current_place = place_ref.get(transaction=current_transaction)

        if not current_user.exists:
            raise StampVerificationError(
                code="user_not_found",
                message="사용자 정보를 찾을 수 없습니다.",
                status_code=404,
            )
        if not current_place.exists:
            raise StampVerificationError(
                code="place_not_found",
                message="업체 정보를 찾을 수 없습니다.",
                status_code=404,
            )

        place_data = current_place.to_dict() or {}
        if place_data.get("isActive") is False:
            raise StampVerificationError(
                code="inactive_place",
                message="현재 이용할 수 없는 업체입니다.",
                status_code=409,
            )
        if place_data.get("stampEnabled") is False:
            raise StampVerificationError(
                code="stamp_disabled",
                message="현재 스탬프 발행이 중지된 업체입니다.",
                status_code=409,
            )

        place_lat = _as_float(place_data.get("lat"))
        place_lng = _as_float(place_data.get("lng"))
        if place_lat is None or place_lng is None:
            raise StampVerificationError(
                code="invalid_place_data",
                message="업체 위치 정보가 올바르지 않습니다.",
                status_code=500,
            )

        rating_sum = _as_non_negative_int(place_data.get("ratingSum"))
        rating_count = _as_non_negative_int(place_data.get("ratingCount"))
        stamp_count = _as_non_negative_int(place_data.get("stampCount"))
        user_data = current_user.to_dict() or {}
        free_point_balance = _as_non_negative_int(
            user_data.get("freePointBalance")
        )
        next_free_point_balance = free_point_balance + reward_point
        next_rating_sum = rating_sum + rating
        next_rating_count = rating_count + 1
        created_at = firestore.SERVER_TIMESTAMP

        current_transaction.set(
            verification_ref,
            {
                "userId": user_id,
                "placeId": place_id,
                "roadId": None,
                "receiptImageUrl": "",
                "ocrStoreName": None,
                "ocrDate": None,
                "ocrTime": None,
                "ocrAmount": None,
                "userLat": place_lat,
                "userLng": place_lng,
                "ipAddress": None,
                "isGpsValid": True,
                "isReceiptValid": True,
                "isRooted": False,
                "isMockLocation": False,
                "isAbnormalSpeed": False,
                "receiptHash": dev_id,
                "status": "approved",
                "rejectReason": None,
                "awardedPoints": reward_point,
                "isDevBypass": True,
                "createdAt": created_at,
            },
        )
        current_transaction.set(
            stamp_ref,
            {
                "userId": user_id,
                "placeId": place_id,
                "verificationId": dev_id,
                "roadId": None,
                "oneLineNote": (one_line_note or "").strip(),
                "rating": rating,
                "issuedAt": created_at,
                "noteUpdatedAt": None,
                "isDevBypass": True,
            },
        )
        current_transaction.update(
            place_ref,
            {
                "ratingSum": next_rating_sum,
                "ratingCount": next_rating_count,
                "ratingAverage": next_rating_sum / next_rating_count,
                "stampCount": stamp_count + 1,
            },
        )
        current_transaction.update(
            user_ref,
            {
                "freePointBalance": next_free_point_balance,
                "updatedAt": created_at,
            },
        )

        if reward_point > 0:
            current_transaction.set(
                point_transaction_ref,
                {
                    "type": "earn",
                    "source": "stamp",
                    "amount": reward_point,
                    "pointType": "free",
                    "refType": "stamp",
                    "refId": dev_id,
                    "createdAt": created_at,
                },
            )

        return {
            "approved": True,
            "verificationId": dev_id,
            "stampId": dev_id,
            "awardedPoints": reward_point,
            "remainingFreePoint": next_free_point_balance,
            "alreadyProcessed": False,
            "isDevBypass": True,
        }

    return execute_dev_issue(transaction)


def issue_stamp(
    *,
    user_id: str,
    place_id: str,
    receipt_bytes: bytes,
    receipt_filename: str | None,
    receipt_content_type: str | None,
    ocr_store_name: str,
    ocr_purchased_at: str,
    ocr_amount: int | None,
    user_lat: float,
    user_lng: float,
    rating: int,
    one_line_note: str | None,
    road_id: str | None,
    is_rooted: bool,
    is_mock_location: bool,
    ip_address: str | None,
) -> dict[str, Any]:
    _validate_request(
        user_id=user_id,
        place_id=place_id,
        receipt_bytes=receipt_bytes,
        receipt_filename=receipt_filename,
        receipt_content_type=receipt_content_type,
        ocr_store_name=ocr_store_name,
        user_lat=user_lat,
        user_lng=user_lng,
        rating=rating,
        one_line_note=one_line_note,
    )

    purchased_at = _parse_client_datetime(ocr_purchased_at)
    if purchased_at is None:
        raise StampVerificationError(
            code="invalid_purchase_datetime",
            message="영수증 결제 일시 형식이 올바르지 않습니다.",
            status_code=422,
        )

    now = datetime.now(timezone.utc)
    receipt_hash = hashlib.sha256(receipt_bytes).hexdigest()

    ensure_firebase_app()
    database = firestore.client()
    user_ref = database.collection("users").document(user_id)
    place_ref = database.collection("place").document(place_id)
    verification_ref = database.collection("verification").document(
        receipt_hash
    )
    stamp_ref = database.collection("stamp").document(receipt_hash)
    point_transaction_ref = user_ref.collection(
        "users_point_transaction"
    ).document(f"stamp_{receipt_hash}")

    user_snapshot = user_ref.get()
    place_snapshot = place_ref.get()
    existing_verification = verification_ref.get()

    if not user_snapshot.exists:
        raise StampVerificationError(
            code="user_not_found",
            message="사용자 정보를 찾을 수 없습니다.",
            status_code=404,
        )
    if not place_snapshot.exists:
        raise StampVerificationError(
            code="place_not_found",
            message="업체 정보를 찾을 수 없습니다.",
            status_code=404,
        )
    if existing_verification.exists:
        return _handle_existing_verification(
            existing_verification.to_dict() or {},
            user_id=user_id,
            receipt_hash=receipt_hash,
        )

    user_data = user_snapshot.to_dict() or {}
    place_data = place_snapshot.to_dict() or {}
    if place_data.get("isActive") is False:
        raise StampVerificationError(
            code="inactive_place",
            message="현재 이용할 수 없는 업체입니다.",
            status_code=409,
        )
    if place_data.get("stampEnabled") is False:
        raise StampVerificationError(
            code="stamp_disabled",
            message="현재 스탬프 인증이 중지된 업체입니다.",
            status_code=409,
        )

    expected_store_name = str(place_data.get("name") or "").strip()
    place_lat = _as_float(place_data.get("lat"))
    place_lng = _as_float(place_data.get("lng"))
    if not expected_store_name or place_lat is None or place_lng is None:
        raise StampVerificationError(
            code="invalid_place_data",
            message="업체 인증 정보가 올바르지 않습니다.",
            status_code=500,
        )

    store_similarity = _store_similarity(
        expected_store_name,
        ocr_store_name,
    )
    distance_meters = _distance_meters(
        user_lat,
        user_lng,
        place_lat,
        place_lng,
    )
    max_distance_meters = _positive_float_env(
        "STAMP_MAX_DISTANCE_METERS",
        150.0,
    )
    max_speed_kmh = _positive_float_env("STAMP_MAX_SPEED_KMH", 200.0)
    receipt_max_age_hours = _positive_float_env(
        "STAMP_RECEIPT_MAX_AGE_HOURS",
        6.0,
    )
    store_threshold = _positive_float_env(
        "STAMP_STORE_NAME_THRESHOLD",
        0.72,
    )

    reject_code: str | None = None
    reject_message: str | None = None
    if is_rooted:
        reject_code = "rooted_device"
        reject_message = "루팅 또는 탈옥된 기기에서는 인증할 수 없습니다."
    elif is_mock_location:
        reject_code = "mock_location"
        reject_message = "위치 조작이 의심되어 인증할 수 없습니다."
    elif store_similarity < store_threshold:
        reject_code = "store_name_mismatch"
        reject_message = "선택한 업체와 영수증의 상호명이 일치하지 않습니다."
    elif purchased_at > now + timedelta(minutes=5):
        reject_code = "future_dated_receipt"
        reject_message = "영수증 결제 시간이 현재 시간보다 이후입니다."
    elif now - purchased_at > timedelta(hours=receipt_max_age_hours):
        reject_code = "receipt_expired"
        reject_message = "영수증 인증 가능 시간이 지났습니다."
    elif distance_meters > max_distance_meters:
        reject_code = "gps_out_of_range"
        reject_message = "업체에서 너무 멀리 떨어져 있어 인증할 수 없습니다."

    initial_speed_kmh = _calculate_speed_from_last_verification(
        user_data.get("lastStampVerification"),
        current_lat=user_lat,
        current_lng=user_lng,
        current_time=now,
    )
    if (
        reject_code is None
        and initial_speed_kmh is not None
        and initial_speed_kmh > max_speed_kmh
    ):
        reject_code = "abnormal_speed"
        reject_message = "이전 인증 위치로부터 비정상적인 이동속도가 감지되었습니다."

    receipt_image_url = _upload_receipt(
        user_id=user_id,
        receipt_hash=receipt_hash,
        receipt_bytes=receipt_bytes,
        receipt_filename=receipt_filename,
        content_type=receipt_content_type,
    )

    common_verification_data = _build_verification_data(
        user_id=user_id,
        place_id=place_id,
        road_id=road_id,
        receipt_image_url=receipt_image_url,
        receipt_hash=receipt_hash,
        ocr_store_name=ocr_store_name,
        purchased_at=purchased_at,
        ocr_amount=ocr_amount,
        user_lat=user_lat,
        user_lng=user_lng,
        ip_address=ip_address,
        is_rooted=is_rooted,
        is_mock_location=is_mock_location,
        is_gps_valid=distance_meters <= max_distance_meters,
        is_receipt_valid=store_similarity >= store_threshold
        and now - purchased_at <= timedelta(hours=receipt_max_age_hours)
        and purchased_at <= now + timedelta(minutes=5),
        is_abnormal_speed=initial_speed_kmh is not None
        and initial_speed_kmh > max_speed_kmh,
        distance_meters=distance_meters,
        speed_kmh=initial_speed_kmh,
        store_similarity=store_similarity,
    )

    if reject_code is not None and reject_message is not None:
        _record_rejected_verification(
            verification_ref=verification_ref,
            verification_data=common_verification_data,
            reject_code=reject_code,
        )
        raise StampVerificationError(
            code=reject_code,
            message=reject_message,
            status_code=409,
        )

    reward_point = _non_negative_int_env("STAMP_REWARD_POINT", 0)
    transaction = database.transaction()

    @firestore.transactional
    def execute_approval(current_transaction):
        current_user = user_ref.get(transaction=current_transaction)
        current_place = place_ref.get(transaction=current_transaction)
        current_verification = verification_ref.get(
            transaction=current_transaction
        )

        if not current_user.exists:
            raise StampVerificationError(
                code="user_not_found",
                message="사용자 정보를 찾을 수 없습니다.",
                status_code=404,
            )
        if not current_place.exists:
            raise StampVerificationError(
                code="place_not_found",
                message="업체 정보를 찾을 수 없습니다.",
                status_code=404,
            )
        if current_verification.exists:
            return _handle_existing_verification(
                current_verification.to_dict() or {},
                user_id=user_id,
                receipt_hash=receipt_hash,
            )

        current_user_data = current_user.to_dict() or {}
        current_speed_kmh = _calculate_speed_from_last_verification(
            current_user_data.get("lastStampVerification"),
            current_lat=user_lat,
            current_lng=user_lng,
            current_time=now,
        )
        if (
            current_speed_kmh is not None
            and current_speed_kmh > max_speed_kmh
        ):
            rejected_data = {
                **common_verification_data,
                "isAbnormalSpeed": True,
                "speedKmh": current_speed_kmh,
                "status": "rejected",
                "rejectReason": "abnormal_speed",
                "createdAt": firestore.SERVER_TIMESTAMP,
            }
            current_transaction.set(verification_ref, rejected_data)
            return {
                "approved": False,
                "code": "abnormal_speed",
                "message": "이전 인증 위치로부터 비정상적인 이동속도가 감지되었습니다.",
            }

        current_place_data = current_place.to_dict() or {}
        rating_sum = _as_non_negative_int(
            current_place_data.get("ratingSum")
        )
        rating_count = _as_non_negative_int(
            current_place_data.get("ratingCount")
        )
        stamp_count = _as_non_negative_int(
            current_place_data.get("stampCount")
        )
        next_rating_sum = rating_sum + rating
        next_rating_count = rating_count + 1
        rating_average = next_rating_sum / next_rating_count
        free_point_balance = _as_non_negative_int(
            current_user_data.get("freePointBalance")
        )
        next_free_point_balance = free_point_balance + reward_point
        created_at = firestore.SERVER_TIMESTAMP

        current_transaction.set(
            verification_ref,
            {
                **common_verification_data,
                "isAbnormalSpeed": False,
                "speedKmh": current_speed_kmh,
                "status": "approved",
                "rejectReason": None,
                "awardedPoints": reward_point,
                "createdAt": created_at,
            },
        )
        current_transaction.set(
            stamp_ref,
            {
                "userId": user_id,
                "placeId": place_id,
                "verificationId": receipt_hash,
                "roadId": road_id,
                "oneLineNote": (one_line_note or "").strip(),
                "rating": rating,
                "issuedAt": created_at,
                "noteUpdatedAt": None,
            },
        )
        current_transaction.update(
            place_ref,
            {
                "ratingSum": next_rating_sum,
                "ratingCount": next_rating_count,
                "ratingAverage": rating_average,
                "stampCount": stamp_count + 1,
            },
        )
        current_transaction.update(
            user_ref,
            {
                "freePointBalance": next_free_point_balance,
                "lastStampVerification": {
                    "lat": user_lat,
                    "lng": user_lng,
                    "verifiedAt": now,
                },
                "updatedAt": created_at,
            },
        )

        if reward_point > 0:
            current_transaction.set(
                point_transaction_ref,
                {
                    "type": "earn",
                    "source": "stamp",
                    "amount": reward_point,
                    "pointType": "free",
                    "refType": "stamp",
                    "refId": receipt_hash,
                    "createdAt": created_at,
                },
            )

        return {
            "approved": True,
            "verificationId": receipt_hash,
            "stampId": receipt_hash,
            "awardedPoints": reward_point,
            "remainingFreePoint": next_free_point_balance,
            "distanceMeters": round(distance_meters, 1),
            "alreadyProcessed": False,
        }

    result = execute_approval(transaction)
    if result.get("approved") is False:
        raise StampVerificationError(
            code=str(result.get("code") or "rejected"),
            message=str(result.get("message") or "스탬프 인증이 거부되었습니다."),
            status_code=409,
        )
    return result


def _validate_request(
    *,
    user_id: str,
    place_id: str,
    receipt_bytes: bytes,
    receipt_filename: str | None,
    receipt_content_type: str | None,
    ocr_store_name: str,
    user_lat: float,
    user_lng: float,
    rating: int,
    one_line_note: str | None,
) -> None:
    if not user_id or not place_id:
        raise StampVerificationError(
            code="invalid_argument",
            message="스탬프 인증 정보가 올바르지 않습니다.",
        )
    if not receipt_bytes:
        raise StampVerificationError(
            code="empty_receipt_image",
            message="영수증 이미지가 필요합니다.",
            status_code=422,
        )
    if len(receipt_bytes) > MAX_RECEIPT_BYTES:
        raise StampVerificationError(
            code="receipt_image_too_large",
            message="영수증 이미지는 10MB 이하여야 합니다.",
            status_code=413,
        )
    normalized_content_type = (receipt_content_type or "").lower()
    extension = Path(receipt_filename or "").suffix.lower()
    if (
        normalized_content_type not in _ALLOWED_CONTENT_TYPES
        and extension not in {".jpg", ".jpeg", ".png", ".webp"}
    ):
        raise StampVerificationError(
            code="unsupported_receipt_image",
            message="JPG, PNG 또는 WebP 영수증 이미지만 사용할 수 있습니다.",
            status_code=415,
        )
    if not ocr_store_name.strip():
        raise StampVerificationError(
            code="empty_ocr_store_name",
            message="영수증 상호명 인식 결과가 필요합니다.",
            status_code=422,
        )
    if not -90 <= user_lat <= 90 or not -180 <= user_lng <= 180:
        raise StampVerificationError(
            code="invalid_location",
            message="사용자 위치 정보가 올바르지 않습니다.",
            status_code=422,
        )
    if rating < 1 or rating > 5:
        raise StampVerificationError(
            code="invalid_rating",
            message="별점은 1점부터 5점까지 입력할 수 있습니다.",
            status_code=422,
        )
    if one_line_note is not None and len(one_line_note.strip()) > 100:
        raise StampVerificationError(
            code="note_too_long",
            message="한줄 기록은 100자 이하여야 합니다.",
            status_code=422,
        )


def _build_verification_data(
    *,
    user_id: str,
    place_id: str,
    road_id: str | None,
    receipt_image_url: str,
    receipt_hash: str,
    ocr_store_name: str,
    purchased_at: datetime,
    ocr_amount: int | None,
    user_lat: float,
    user_lng: float,
    ip_address: str | None,
    is_rooted: bool,
    is_mock_location: bool,
    is_gps_valid: bool,
    is_receipt_valid: bool,
    is_abnormal_speed: bool,
    distance_meters: float,
    speed_kmh: float | None,
    store_similarity: float,
) -> dict[str, Any]:
    purchased_at_kst = purchased_at.astimezone(_KST)
    return {
        "userId": user_id,
        "placeId": place_id,
        "roadId": road_id,
        "receiptImageUrl": receipt_image_url,
        "ocrStoreName": ocr_store_name.strip(),
        "ocrDate": purchased_at_kst.strftime("%Y-%m-%d"),
        "ocrTime": purchased_at_kst.strftime("%H:%M:%S"),
        "ocrAmount": ocr_amount,
        "userLat": user_lat,
        "userLng": user_lng,
        "ipAddress": ip_address,
        "isGpsValid": is_gps_valid,
        "isReceiptValid": is_receipt_valid,
        "isRooted": is_rooted,
        "isMockLocation": is_mock_location,
        "isAbnormalSpeed": is_abnormal_speed,
        "receiptHash": receipt_hash,
        "distanceMeters": round(distance_meters, 1),
        "speedKmh": None if speed_kmh is None else round(speed_kmh, 1),
        "storeNameSimilarity": round(store_similarity, 4),
    }


def _record_rejected_verification(
    *,
    verification_ref,
    verification_data: dict[str, Any],
    reject_code: str,
) -> None:
    database = firestore.client()
    transaction = database.transaction()

    @firestore.transactional
    def record(current_transaction):
        current = verification_ref.get(transaction=current_transaction)
        if current.exists:
            raise StampVerificationError(
                code="duplicate_receipt",
                message="이미 인증에 사용된 영수증입니다.",
                status_code=409,
            )
        current_transaction.set(
            verification_ref,
            {
                **verification_data,
                "status": "rejected",
                "rejectReason": reject_code,
                "createdAt": firestore.SERVER_TIMESTAMP,
            },
        )

    record(transaction)


def _handle_existing_verification(
    data: dict[str, Any],
    *,
    user_id: str,
    receipt_hash: str,
) -> dict[str, Any]:
    if data.get("userId") == user_id and data.get("status") == "approved":
        return {
            "approved": True,
            "verificationId": receipt_hash,
            "stampId": receipt_hash,
            "awardedPoints": _as_non_negative_int(data.get("awardedPoints")),
            "alreadyProcessed": True,
        }
    raise StampVerificationError(
        code="duplicate_receipt",
        message="이미 인증에 사용된 영수증입니다.",
        status_code=409,
    )


def _upload_receipt(
    *,
    user_id: str,
    receipt_hash: str,
    receipt_bytes: bytes,
    receipt_filename: str | None,
    content_type: str | None,
) -> str:
    bucket_name = os.getenv(
        "FIREBASE_STORAGE_BUCKET",
        "yamyamroad.firebasestorage.app",
    ).strip()
    if not bucket_name:
        raise StampVerificationError(
            code="storage_not_configured",
            message="영수증 저장소가 설정되지 않았습니다.",
            status_code=503,
        )

    extension = Path(receipt_filename or "").suffix.lower()
    if extension not in {".jpg", ".jpeg", ".png", ".webp"}:
        extension = {
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/webp": ".webp",
        }.get((content_type or "").lower(), ".jpg")

    object_path = (
        f"receipt_img/{user_id}/{receipt_hash}{extension}"
    )
    try:
        bucket = storage.bucket(bucket_name)
        blob = bucket.blob(object_path)
        blob.upload_from_string(
            receipt_bytes,
            content_type=content_type or "application/octet-stream",
        )
    except Exception as error:
        raise StampVerificationError(
            code="receipt_upload_failed",
            message="영수증 이미지를 저장하지 못했습니다.",
            status_code=503,
        ) from error

    return f"gs://{bucket_name}/{object_path}"


def _parse_client_datetime(value: str) -> datetime | None:
    normalized = value.strip()
    if not normalized:
        return None
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_KST)
    return parsed.astimezone(timezone.utc)


def _calculate_speed_from_last_verification(
    last_verification: Any,
    *,
    current_lat: float,
    current_lng: float,
    current_time: datetime,
) -> float | None:
    if not isinstance(last_verification, dict):
        return None
    last_lat = _as_float(last_verification.get("lat"))
    last_lng = _as_float(last_verification.get("lng"))
    verified_at = last_verification.get("verifiedAt")
    if (
        last_lat is None
        or last_lng is None
        or not isinstance(verified_at, datetime)
    ):
        return None
    if verified_at.tzinfo is None:
        verified_at = verified_at.replace(tzinfo=timezone.utc)
    elapsed_hours = (
        current_time - verified_at.astimezone(timezone.utc)
    ).total_seconds() / 3600
    if elapsed_hours <= 0:
        return None
    distance_km = (
        _distance_meters(last_lat, last_lng, current_lat, current_lng)
        / 1000
    )
    return distance_km / elapsed_hours


def _distance_meters(
    first_lat: float,
    first_lng: float,
    second_lat: float,
    second_lng: float,
) -> float:
    earth_radius_meters = 6_371_000
    first_lat_radians = math.radians(first_lat)
    second_lat_radians = math.radians(second_lat)
    latitude_delta = math.radians(second_lat - first_lat)
    longitude_delta = math.radians(second_lng - first_lng)
    haversine = (
        math.sin(latitude_delta / 2) ** 2
        + math.cos(first_lat_radians)
        * math.cos(second_lat_radians)
        * math.sin(longitude_delta / 2) ** 2
    )
    return earth_radius_meters * 2 * math.atan2(
        math.sqrt(haversine),
        math.sqrt(1 - haversine),
    )


def _store_similarity(expected: str, actual: str) -> float:
    expected_normalized = _normalize_store_name(expected)
    actual_normalized = _normalize_store_name(actual)
    if not expected_normalized or not actual_normalized:
        return 0.0
    if expected_normalized == actual_normalized:
        return 1.0
    if expected_normalized in actual_normalized:
        return 1.0
    if (
        len(actual_normalized) >= 3
        and actual_normalized in expected_normalized
    ):
        return 0.9
    return _dice_coefficient(expected_normalized, actual_normalized)


def _normalize_store_name(value: str) -> str:
    return re.sub(r"[^0-9a-z가-힣]", "", value.lower())


def _dice_coefficient(left: str, right: str) -> float:
    if left == right:
        return 1.0
    if len(left) < 2 or len(right) < 2:
        return 0.0
    left_pairs: dict[str, int] = {}
    for index in range(len(left) - 1):
        pair = left[index : index + 2]
        left_pairs[pair] = left_pairs.get(pair, 0) + 1
    intersection = 0
    for index in range(len(right) - 1):
        pair = right[index : index + 2]
        count = left_pairs.get(pair, 0)
        if count > 0:
            intersection += 1
            left_pairs[pair] = count - 1
    return (2 * intersection) / (len(left) + len(right) - 2)


def _positive_float_env(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
        return value if value > 0 else default
    except (TypeError, ValueError):
        return default


def _non_negative_int_env(name: str, default: int) -> int:
    try:
        return max(int(os.getenv(name, str(default))), 0)
    except (TypeError, ValueError):
        return default


def _as_non_negative_int(value: Any) -> int:
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return 0


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
