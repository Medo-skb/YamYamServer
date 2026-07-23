import logging
import re
from typing import Any
from uuid import uuid4

from firebase_admin import firestore, messaging
from google.api_core.exceptions import AlreadyExists

from gifticon_purchase import ensure_firebase_app


logger = logging.getLogger(__name__)


def notify_user_safely(
    *,
    user_id: str,
    notification_type: str,
    title: str,
    body: str,
    ref_type: str | None = None,
    ref_id: str | None = None,
    notification_id: str | None = None,
) -> dict[str, Any]:
    try:
        return _create_and_send_notification(
            user_id=user_id,
            notification_type=notification_type,
            title=title,
            body=body,
            ref_type=ref_type,
            ref_id=ref_id,
            notification_id=notification_id,
        )
    except Exception:
        logger.exception("알림 생성 또는 FCM 발송 중 오류가 발생했습니다.")
        return {
            "created": False,
            "sentCount": 0,
            "failedCount": 0,
        }


def _create_and_send_notification(
    *,
    user_id: str,
    notification_type: str,
    title: str,
    body: str,
    ref_type: str | None,
    ref_id: str | None,
    notification_id: str | None,
) -> dict[str, Any]:
    normalized_user_id = user_id.strip()
    if not normalized_user_id:
        raise ValueError("user_id가 비어 있습니다.")

    ensure_firebase_app()
    database = firestore.client()
    user_ref = database.collection("users").document(normalized_user_id)
    normalized_notification_id = _document_id(
        notification_id or f"notification_{uuid4().hex}"
    )
    notification_ref = user_ref.collection(
        "users_notification"
    ).document(normalized_notification_id)

    data: dict[str, Any] = {
        "type": notification_type.strip(),
        "title": title.strip(),
        "body": body.strip(),
        "refType": _optional_text(ref_type),
        "refId": _optional_text(ref_id),
        "isRead": False,
        "createdAt": firestore.SERVER_TIMESTAMP,
    }

    try:
        notification_ref.create(data)
    except AlreadyExists:
        return {
            "notificationId": normalized_notification_id,
            "created": False,
            "sentCount": 0,
            "failedCount": 0,
        }

    device_documents = list(user_ref.collection("users_device").stream())
    token_documents = {
        str((document.to_dict() or {}).get("fcmToken") or "").strip(): document
        for document in device_documents
    }
    token_documents.pop("", None)

    sent_count = 0
    failed_count = 0
    for token, device_document in token_documents.items():
        try:
            messaging.send(
                messaging.Message(
                    token=token,
                    notification=messaging.Notification(
                        title=data["title"],
                        body=data["body"],
                    ),
                    data=_message_data(
                        notification_id=normalized_notification_id,
                        notification_type=data["type"],
                        ref_type=data["refType"],
                        ref_id=data["refId"],
                    ),
                    android=messaging.AndroidConfig(priority="high"),
                )
            )
            sent_count += 1
        except (messaging.UnregisteredError, messaging.SenderIdMismatchError):
            failed_count += 1
            device_document.reference.delete()
        except Exception:
            failed_count += 1
            logger.exception(
                "FCM 발송 실패: user_id=%s, notification_id=%s",
                normalized_user_id,
                normalized_notification_id,
            )

    return {
        "notificationId": normalized_notification_id,
        "created": True,
        "sentCount": sent_count,
        "failedCount": failed_count,
    }


def _message_data(
    *,
    notification_id: str,
    notification_type: str,
    ref_type: str | None,
    ref_id: str | None,
) -> dict[str, str]:
    data = {
        "notificationId": notification_id,
        "type": notification_type,
    }
    if ref_type:
        data["refType"] = ref_type
    if ref_id:
        data["refId"] = ref_id
    return data


def _document_id(value: str) -> str:
    normalized = re.sub(r"[/\\]", "_", value.strip())
    if not normalized:
        return f"notification_{uuid4().hex}"
    return normalized[:1400]


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None
