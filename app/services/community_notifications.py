import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import assert_never

from firebase_admin import firestore
from google.cloud.firestore_v1 import Client, DocumentReference, DocumentSnapshot

from app.core.firebase import ensure_firebase_app
from app.services.notifications import notify_user_safely


logger = logging.getLogger(__name__)


class CommunityNotificationEvent(StrEnum):
    POST_LIKE = "post_like"
    POST_SCRAP = "post_scrap"
    POST_COMMENT = "post_comment"
    COMMENT_LIKE = "comment_like"


@dataclass(frozen=True, slots=True)
class SocialNotification:
    recipient_user_id: str
    actor_user_id: str
    notification_type: str
    title: str
    body: str
    post_id: str
    notification_id: str


def notify_community_event_safely(
    *,
    actor_user_id: str,
    event: CommunityNotificationEvent,
    post_id: str,
    comment_id: str | None,
) -> bool:
    try:
        return _notify_community_event(
            actor_user_id=actor_user_id,
            event=event,
            post_id=post_id,
            comment_id=comment_id,
        )
    except Exception:  # noqa: BROAD_EXCEPT_OK — background task boundary
        logger.exception(
            "커뮤니티 알림 생성 중 오류가 발생했습니다: actor=%s, event=%s, post=%s",
            actor_user_id,
            event.value,
            post_id,
        )
        return False


def _notify_community_event(
    *,
    actor_user_id: str,
    event: CommunityNotificationEvent,
    post_id: str,
    comment_id: str | None,
) -> bool:
    ensure_firebase_app()
    database = firestore.client()
    post_ref = database.collection("posts").document(post_id)
    post_snapshot = post_ref.get()
    if not post_snapshot.exists:
        return False

    post_data = post_snapshot.to_dict() or {}
    post_owner_id = str(post_data.get("userId") or "").strip()
    actor_name = _actor_name(database, actor_user_id)

    match event:
        case CommunityNotificationEvent.POST_LIKE:
            if not post_ref.collection("post_like").document(actor_user_id).get().exists:
                return False
            return _notify_social_event(
                SocialNotification(
                    recipient_user_id=post_owner_id,
                    actor_user_id=actor_user_id,
                    notification_type="like",
                    title="좋아요",
                    body=f"{actor_name}님이 회원님의 게시글을 좋아합니다.",
                    post_id=post_id,
                    notification_id=f"post_like_{post_id}_{actor_user_id}",
                )
            )
        case CommunityNotificationEvent.POST_SCRAP:
            if not post_ref.collection("post_scrap").document(actor_user_id).get().exists:
                return False
            return _notify_social_event(
                SocialNotification(
                    recipient_user_id=post_owner_id,
                    actor_user_id=actor_user_id,
                    notification_type="scrap",
                    title="스크랩",
                    body=f"{actor_name}님이 회원님의 게시글을 스크랩했습니다.",
                    post_id=post_id,
                    notification_id=f"post_scrap_{post_id}_{actor_user_id}",
                )
            )
        case CommunityNotificationEvent.POST_COMMENT:
            comment_snapshot = _comment_snapshot(post_ref, comment_id)
            if comment_snapshot is None:
                return False
            comment_data = comment_snapshot.to_dict() or {}
            if str(comment_data.get("userId") or "").strip() != actor_user_id:
                return False
            return _notify_social_event(
                SocialNotification(
                    recipient_user_id=post_owner_id,
                    actor_user_id=actor_user_id,
                    notification_type="comment",
                    title="새 댓글",
                    body=f"{actor_name}님이 회원님의 게시글에 댓글을 남겼습니다.",
                    post_id=post_id,
                    notification_id=f"post_comment_{comment_snapshot.id}",
                )
            )
        case CommunityNotificationEvent.COMMENT_LIKE:
            comment_snapshot = _comment_snapshot(post_ref, comment_id)
            if comment_snapshot is None:
                return False
            if not comment_snapshot.reference.collection("comment_like").document(
                actor_user_id
            ).get().exists:
                return False
            comment_data = comment_snapshot.to_dict() or {}
            return _notify_social_event(
                SocialNotification(
                    recipient_user_id=str(
                        comment_data.get("userId") or ""
                    ).strip(),
                    actor_user_id=actor_user_id,
                    notification_type="like",
                    title="댓글 좋아요",
                    body=f"{actor_name}님이 회원님의 댓글을 좋아합니다.",
                    post_id=post_id,
                    notification_id=(
                        f"comment_like_{comment_snapshot.id}_{actor_user_id}"
                    ),
                )
            )
        case unreachable:
            assert_never(unreachable)


def _comment_snapshot(
    post_ref: DocumentReference,
    comment_id: str | None,
) -> DocumentSnapshot | None:
    normalized_comment_id = (comment_id or "").strip()
    if not normalized_comment_id:
        return None
    snapshot = post_ref.collection("comments").document(normalized_comment_id).get()
    return snapshot if snapshot.exists else None


def _actor_name(database: Client, actor_user_id: str) -> str:
    actor_snapshot = database.collection("users").document(actor_user_id).get()
    actor_data = actor_snapshot.to_dict() or {}
    actor_name = str(actor_data.get("nickname") or "").strip()
    return actor_name or "누군가"


def _notify_social_event(notification: SocialNotification) -> bool:
    if (
        not notification.recipient_user_id
        or notification.recipient_user_id == notification.actor_user_id
    ):
        return False
    result = notify_user_safely(
        user_id=notification.recipient_user_id,
        notification_type=notification.notification_type,
        title=notification.title,
        body=notification.body,
        ref_type="post",
        ref_id=notification.post_id,
        notification_id=notification.notification_id,
    )
    return bool(result.get("created"))
