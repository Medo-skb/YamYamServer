from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from app.api.dependencies import get_current_uid
from app.services.notifications import notify_user_safely
from app.services.point_payments import (
    PointPaymentError,
    complete_point_payment,
    prepare_point_payment,
)


router = APIRouter()


@router.post("/point-payments/{point_package_id}/prepare")
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


@router.post("/point-payments/{payment_id}/complete")
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
