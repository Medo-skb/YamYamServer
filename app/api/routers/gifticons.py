from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from app.api.dependencies import get_current_uid
from app.services.gifticons import GifticonPurchaseError, purchase_gifticon
from app.services.notifications import notify_user_safely


router = APIRouter()


@router.post("/gifticons/{gifticon_id}/purchase")
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
