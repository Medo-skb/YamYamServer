from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Request,
    UploadFile,
)
from firebase_admin import auth

from badge_service import grant_earned_badges_safely
from gifticon_purchase import (
    GifticonPurchaseError,
    ensure_firebase_app,
    purchase_gifticon,
)
from point_payment import (
    PointPaymentError,
    complete_point_payment,
    prepare_point_payment,
)
from notification_service import notify_user_safely
from recommender import recommend
from stamp_verification import (
    MAX_RECEIPT_BYTES,
    StampVerificationError,
    issue_dev_stamp,
    issue_stamp,
)

app = FastAPI()


def attach_badge_grants(
    *,
    result: dict,
    user_id: str,
    road_id: str | None,
    background_tasks: BackgroundTasks,
) -> None:
    badge_result = grant_earned_badges_safely(
        user_id=user_id,
        road_id=road_id,
    )
    new_badges = badge_result["newBadges"]
    result["badgeGrantStatus"] = badge_result["status"]
    result["newBadges"] = new_badges
    if badge_result["failedConditions"]:
        result["badgeGrantFailedConditions"] = badge_result[
            "failedConditions"
        ]

    for badge in new_badges:
        badge_id = badge["badgeId"]
        badge_name = badge["name"]
        background_tasks.add_task(
            notify_user_safely,
            user_id=user_id,
            notification_type="badge",
            title="새로운 뱃지 획득",
            body=f"{badge_name} 뱃지를 획득했습니다.",
            ref_type="badge",
            ref_id=badge_id,
            notification_id=f"badge_{badge_id}",
        )


def get_current_uid(
    authorization: str | None = Header(default=None),
) -> str:
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")

    id_token = authorization.removeprefix("Bearer ").strip()
    if not id_token:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")

    try:
        ensure_firebase_app()
        decoded_token = auth.verify_id_token(id_token)
        return decoded_token["uid"]
    except Exception as error:
        raise HTTPException(
            status_code=401,
            detail="유효하지 않은 로그인 정보입니다.",
        ) from error


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/recommend")
def get_recommend(
    userId: str,
    currentRegionId: str | None = None,
    userLat: float | None = None,
    userLng: float | None = None,
):
    return recommend(
        userId=userId,
        currentRegionId=currentRegionId,
        userLat=userLat,
        userLng=userLng,
    )


@app.post("/gifticons/{gifticon_id}/purchase")
def purchase_gifticon_endpoint(
    gifticon_id: str,
    background_tasks: BackgroundTasks,
    user_id: str = Depends(get_current_uid),
):
    try:
        result = purchase_gifticon(
            user_id=user_id,
            gifticon_id=gifticon_id,
        )
        used_point = int(result.get("usedFreePoint") or 0) + int(
            result.get("usedPaidPoint") or 0
        )
        background_tasks.add_task(
            notify_user_safely,
            user_id=user_id,
            notification_type="point",
            title="기프티콘 구매 완료",
            body=f"기프티콘 구매에 {used_point:,}포인트를 사용했습니다.",
            ref_type="purchase",
            ref_id=result["purchaseId"],
            notification_id=f"gifticon_purchase_{result['purchaseId']}",
        )
        return result
    except GifticonPurchaseError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail={"code": error.code, "message": error.message},
        ) from error


@app.post("/point-payments/{point_package_id}/prepare")
def prepare_point_payment_endpoint(
    point_package_id: str,
    user_id: str = Depends(get_current_uid),
):
    try:
        return prepare_point_payment(
            user_id=user_id,
            point_package_id=point_package_id,
        )
    except PointPaymentError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail={"code": error.code, "message": error.message},
        ) from error


@app.post("/point-payments/{payment_id}/complete")
def complete_point_payment_endpoint(
    payment_id: str,
    background_tasks: BackgroundTasks,
    user_id: str = Depends(get_current_uid),
):
    try:
        result = complete_point_payment(
            user_id=user_id,
            payment_id=payment_id,
        )
        if not result.get("alreadyProcessed"):
            granted_point = int(result.get("grantedPoint") or 0)
            background_tasks.add_task(
                notify_user_safely,
                user_id=user_id,
                notification_type="point",
                title="포인트 충전 완료",
                body=f"유료 포인트 {granted_point:,}P가 충전되었습니다.",
                ref_type="point",
                ref_id=payment_id,
                notification_id=f"point_payment_{payment_id}",
            )
        return result
    except PointPaymentError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail={"code": error.code, "message": error.message},
        ) from error


@app.post("/stamp-verifications")
async def create_stamp_verification_endpoint(
    request: Request,
    background_tasks: BackgroundTasks,
    placeId: str = Form(...),
    ocrStoreName: str = Form(...),
    ocrPurchasedAt: str = Form(...),
    userLat: float = Form(...),
    userLng: float = Form(...),
    rating: int = Form(...),
    receiptImage: UploadFile = File(...),
    ocrAmount: int | None = Form(default=None),
    oneLineNote: str | None = Form(default=None),
    roadId: str | None = Form(default=None),
    isRooted: bool = Form(default=False),
    isMockLocation: bool = Form(default=False),
    user_id: str = Depends(get_current_uid),
):
    try:
        receipt_bytes = await receiptImage.read(MAX_RECEIPT_BYTES + 1)
        result = issue_stamp(
            user_id=user_id,
            place_id=placeId,
            receipt_bytes=receipt_bytes,
            receipt_filename=receiptImage.filename,
            receipt_content_type=receiptImage.content_type,
            ocr_store_name=ocrStoreName,
            ocr_purchased_at=ocrPurchasedAt,
            ocr_amount=ocrAmount,
            user_lat=userLat,
            user_lng=userLng,
            rating=rating,
            one_line_note=oneLineNote,
            road_id=roadId,
            is_rooted=isRooted,
            is_mock_location=isMockLocation,
            ip_address=request.client.host if request.client else None,
        )
        attach_badge_grants(
            result=result,
            user_id=user_id,
            road_id=roadId,
            background_tasks=background_tasks,
        )
        if not result.get("alreadyProcessed"):
            awarded_points = int(result.get("awardedPoints") or 0)
            point_message = (
                f" 무료 포인트 {awarded_points:,}P도 적립되었습니다."
                if awarded_points > 0
                else ""
            )
            background_tasks.add_task(
                notify_user_safely,
                user_id=user_id,
                notification_type="stamp",
                title="스탬프 발행 완료",
                body=f"스탬프 인증이 완료되었습니다.{point_message}",
                ref_type="stamp",
                ref_id=result["stampId"],
                notification_id=f"stamp_{result['stampId']}",
            )
        return result
    except StampVerificationError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail={"code": error.code, "message": error.message},
        ) from error
    finally:
        await receiptImage.close()


@app.post("/dev/stamps/issue")
def create_dev_stamp_endpoint(
    background_tasks: BackgroundTasks,
    placeId: str,
    rating: int = 5,
    oneLineNote: str | None = None,
    user_id: str = Depends(get_current_uid),
):
    try:
        result = issue_dev_stamp(
            user_id=user_id,
            place_id=placeId,
            rating=rating,
            one_line_note=oneLineNote,
        )
        attach_badge_grants(
            result=result,
            user_id=user_id,
            road_id=None,
            background_tasks=background_tasks,
        )
        background_tasks.add_task(
            notify_user_safely,
            user_id=user_id,
            notification_type="stamp",
            title="개발용 스탬프 발행 완료",
            body="인증을 생략한 개발용 스탬프가 발행되었습니다.",
            ref_type="stamp",
            ref_id=result["stampId"],
            notification_id=f"stamp_{result['stampId']}",
        )
        return result
    except StampVerificationError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail={"code": error.code, "message": error.message},
        ) from error
