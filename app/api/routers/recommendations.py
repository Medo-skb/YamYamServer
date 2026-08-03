from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies import get_current_uid
from app.recommendation.service import recommend


router = APIRouter()


@router.get("/recommend")
def get_recommend(
    userId: str,
    currentRegionId: str | None = None,
    userLat: float | None = None,
    userLng: float | None = None,
    authenticated_user_id: str = Depends(get_current_uid),
):
    if userId != authenticated_user_id:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "user_mismatch",
                "message": "현재 로그인한 사용자 정보가 일치하지 않습니다.",
            },
        )
    return recommend(
        userId=authenticated_user_id,
        currentRegionId=currentRegionId,
        userLat=userLat,
        userLng=userLng,
    )
