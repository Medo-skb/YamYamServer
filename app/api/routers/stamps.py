from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
)

from app.api.badge_grants import attach_badge_grants
from app.api.dependencies import get_current_uid
from app.services.notifications import notify_user_safely
from app.services.stamps import (
    MAX_RECEIPT_BYTES,
    StampVerificationError,
    issue_dev_stamp,
    issue_stamp,
)


router = APIRouter()


@router.post("/stamp-verifications")
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


@router.post("/dev/stamps/issue")
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
