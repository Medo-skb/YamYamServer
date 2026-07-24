from datetime import datetime, timezone
from typing import Any

import firebase_admin
from firebase_admin import firestore
from google.cloud.firestore_v1.base_query import FieldFilter
from google.cloud.firestore_v1.document import DocumentSnapshot


class GifticonPurchaseError(Exception):
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


def ensure_firebase_app() -> None:
    try:
        firebase_admin.get_app()
    except ValueError:
        firebase_admin.initialize_app()


def purchase_gifticon(user_id: str, gifticon_id: str) -> dict[str, Any]:
    if not user_id or not gifticon_id:
        raise GifticonPurchaseError(
            code="invalid_argument",
            message="구매 정보가 올바르지 않습니다.",
        )

    ensure_firebase_app()
    database = firestore.client()

    user_ref = database.collection("users").document(user_id)
    gifticon_ref = database.collection("gifticon").document(gifticon_id)
    purchase_ref = user_ref.collection("users_purchase").document()
    point_transaction_ref = user_ref.collection(
        "users_point_transaction"
    ).document()

    available_stock_query = (
        database.collection("gifticon_stock")
        .where(filter=FieldFilter("gifticonId", "==", gifticon_id))
        .where(filter=FieldFilter("status", "==", "available"))
    )

    transaction = database.transaction()

    @firestore.transactional
    def execute_purchase(current_transaction):
        user_snapshot = user_ref.get(transaction=current_transaction)
        gifticon_snapshot = gifticon_ref.get(transaction=current_transaction)
        stock_snapshots = list(
            current_transaction.get(available_stock_query)
        )

        if not user_snapshot.exists:
            raise GifticonPurchaseError(
                code="user_not_found",
                message="사용자 정보를 찾을 수 없습니다.",
                status_code=404,
            )

        if not gifticon_snapshot.exists:
            raise GifticonPurchaseError(
                code="gifticon_not_found",
                message="기프티콘 상품을 찾을 수 없습니다.",
                status_code=404,
            )

        gifticon_data = gifticon_snapshot.to_dict() or {}
        if gifticon_data.get("isActive") is False:
            raise GifticonPurchaseError(
                code="not_available",
                message="현재 구매할 수 없는 기프티콘입니다.",
            )

        selected_stock = _select_available_stock(stock_snapshots)
        if selected_stock is None:
            raise GifticonPurchaseError(
                code="sold_out",
                message="사용 가능한 기프티콘 재고가 없습니다.",
                status_code=409,
            )

        required_point = _as_non_negative_int(
            gifticon_data.get("requiredPoint")
        )
        if required_point <= 0:
            raise GifticonPurchaseError(
                code="invalid_price",
                message="기프티콘 가격 정보가 올바르지 않습니다.",
                status_code=500,
            )

        user_data = user_snapshot.to_dict() or {}
        point_usage = _calculate_point_usage(
            free_point=_as_non_negative_int(
                user_data.get("freePointBalance")
            ),
            paid_point=_as_non_negative_int(
                user_data.get("paidPointBalance")
            ),
            required_point=required_point,
        )

        created_at = firestore.SERVER_TIMESTAMP
        purchase_id = purchase_ref.id

        current_transaction.update(
            user_ref,
            {
                "freePointBalance": point_usage["remainingFreePoint"],
                "paidPointBalance": point_usage["remainingPaidPoint"],
                "updatedAt": created_at,
            },
        )

        current_transaction.set(
            purchase_ref,
            {
                "purchaseType": "gifticon",
                "itemId": gifticon_id,
                "stockId": selected_stock.id,
                "paymentMethod": "point",
                "usedFreePoint": point_usage["usedFreePoint"],
                "usedPaidPoint": point_usage["usedPaidPoint"],
                "paidAmount": 0,
                "status": "paid",
                "createdAt": created_at,
                "usedAt": None,
            },
        )

        current_transaction.update(
            selected_stock.reference,
            {
                "status": "assigned",
                "assignedUserId": user_id,
                "purchaseId": purchase_id,
                "assignedAt": created_at,
            },
        )

        stock_count = _as_non_negative_int(
            gifticon_data.get("stockCount")
        )
        current_transaction.update(
            gifticon_ref,
            {"stockCount": max(stock_count - 1, 0)},
        )

        _write_point_transaction(
            transaction=current_transaction,
            transaction_ref=point_transaction_ref,
            purchase_id=purchase_id,
            point_usage=point_usage,
            created_at=created_at,
        )

        return {
            "purchaseId": purchase_id,
            "gifticonId": gifticon_id,
            "stockId": selected_stock.id,
            **point_usage,
        }

    return execute_purchase(transaction)


def _select_available_stock(
    stock_snapshots: list[DocumentSnapshot],
) -> DocumentSnapshot | None:
    now = datetime.now(timezone.utc)
    valid_stock = []

    for snapshot in stock_snapshots:
        data = snapshot.to_dict() or {}
        expires_at = data.get("expiresAt")
        if not isinstance(expires_at, datetime) or expires_at <= now:
            continue
        valid_stock.append(snapshot)

    if not valid_stock:
        return None

    return min(
        valid_stock,
        key=lambda snapshot: (snapshot.get("expiresAt"), snapshot.id),
    )


def _calculate_point_usage(
    free_point: int,
    paid_point: int,
    required_point: int,
) -> dict[str, int]:
    if free_point + paid_point < required_point:
        raise GifticonPurchaseError(
            code="insufficient_points",
            message="보유 포인트가 부족합니다.",
            status_code=409,
        )

    used_free_point = min(free_point, required_point)
    used_paid_point = required_point - used_free_point

    return {
        "usedFreePoint": used_free_point,
        "usedPaidPoint": used_paid_point,
        "remainingFreePoint": free_point - used_free_point,
        "remainingPaidPoint": paid_point - used_paid_point,
    }


def _write_point_transaction(
    transaction,
    transaction_ref,
    purchase_id: str,
    point_usage: dict[str, int],
    created_at,
) -> None:
    used_free_point = point_usage["usedFreePoint"]
    used_paid_point = point_usage["usedPaidPoint"]
    if used_free_point > 0 and used_paid_point > 0:
        point_type = "mixed"
    elif used_free_point > 0:
        point_type = "free"
    else:
        point_type = "paid"

    transaction.set(
        transaction_ref,
        {
            "type": "use",
            "source": "purchase",
            "amount": -(used_free_point + used_paid_point),
            "pointType": point_type,
            "usedFreePoint": used_free_point,
            "usedPaidPoint": used_paid_point,
            "freePointBalanceAfter": point_usage["remainingFreePoint"],
            "paidPointBalanceAfter": point_usage["remainingPaidPoint"],
            "refType": "purchase",
            "refId": purchase_id,
            "createdAt": created_at,
        },
    )


def _as_non_negative_int(value: Any) -> int:
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return 0
