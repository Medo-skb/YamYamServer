from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, status
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.api.dependencies import get_current_uid
from app.services.community_notifications import (
    CommunityNotificationEvent,
    notify_community_event_safely,
)


router = APIRouter()
NonEmptyId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class CommunityNotificationRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_type: CommunityNotificationEvent = Field(alias="eventType")
    post_id: NonEmptyId = Field(alias="postId")
    comment_id: NonEmptyId | None = Field(default=None, alias="commentId")


class CommunityNotificationAccepted(BaseModel):
    model_config = ConfigDict(frozen=True)

    accepted: bool


@router.post(
    "/notifications/community",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=CommunityNotificationAccepted,
)
def create_community_notification_endpoint(
    payload: CommunityNotificationRequest,
    background_tasks: BackgroundTasks,
    user_id: str = Depends(get_current_uid),
) -> CommunityNotificationAccepted:
    background_tasks.add_task(
        notify_community_event_safely,
        actor_user_id=user_id,
        event=payload.event_type,
        post_id=payload.post_id,
        comment_id=payload.comment_id,
    )
    return CommunityNotificationAccepted(accepted=True)
