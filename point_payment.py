import json
import os
from datetime import datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
from uuid import uuid4

from firebase_admin import firestore

from gifticon_purchase import ensure_firebase_app


class PointPaymentError(Exception):
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


def prepare_point_payment(
    user_id: str,
    point_package_id: str,
) -> dict[str, Any]:
    if not user_id or not point_package_id:
        raise PointPaymentError(
            code="invalid_argument",
            message="결제 상품 정보가 올바르지 않습니다.",
        )

    store_id, channel_key, _ = _get_portone_config(
        require_api_secret=False
    )
    ensure_firebase_app()
    database = firestore.client()

    user_ref = database.collection("users").document(user_id)
    package_ref = database.collection("point_package").document(
        point_package_id
    )
    user_snapshot = user_ref.get()
    package_snapshot = package_ref.get()

    if not user_snapshot.exists:
        raise PointPaymentError(
            code="user_not_found",
            message="사용자 정보를 찾을 수 없습니다.",
            status_code=404,
        )
    if not package_snapshot.exists:
        raise PointPaymentError(
            code="point_package_not_found",
            message="포인트 상품을 찾을 수 없습니다.",
            status_code=404,
        )

    package_data = package_snapshot.to_dict() or {}
    if package_data.get("isActive") is False:
        raise PointPaymentError(
            code="not_available",
            message="현재 구매할 수 없는 포인트 상품입니다.",
        )

    point_amount = _as_positive_int(package_data.get("pointAmount"))
    total_amount = _as_positive_int(package_data.get("priceCash"))
    if point_amount <= 0 or total_amount <= 0:
        raise PointPaymentError(
            code="invalid_point_package",
            message="포인트 상품의 금액 정보가 올바르지 않습니다.",
            status_code=500,
        )

    payment_id = f"point_{uuid4().hex}"
    order_name = package_data.get("name") or f"{point_amount} 포인트"
    purchase_ref = user_ref.collection("users_purchase").document(payment_id)
    purchase_ref.set(
        {
            "purchaseType": "point_package",
            "itemId": point_package_id,
            "paymentMethod": "cash",
            "usedFreePoint": 0,
            "usedPaidPoint": 0,
            "paidAmount": total_amount,
            "pointAmount": point_amount,
            "status": "pending",
            "portonePaymentId": payment_id,
            "createdAt": firestore.SERVER_TIMESTAMP,
            "usedAt": None,
        }
    )

    return {
        "paymentId": payment_id,
        "pointPackageId": point_package_id,
        "orderName": str(order_name),
        "pointAmount": point_amount,
        "totalAmount": total_amount,
        "storeId": store_id,
        "channelKey": channel_key,
    }


def complete_point_payment(
    user_id: str,
    payment_id: str,
) -> dict[str, Any]:
    if not user_id or not payment_id:
        raise PointPaymentError(
            code="invalid_argument",
            message="결제 확인 정보가 올바르지 않습니다.",
        )

    store_id, _, api_secret = _get_portone_config(
        require_api_secret=True
    )
    ensure_firebase_app()
    database = firestore.client()
    user_ref = database.collection("users").document(user_id)
    purchase_ref = user_ref.collection("users_purchase").document(payment_id)
    purchase_snapshot = purchase_ref.get()

    if not purchase_snapshot.exists:
        raise PointPaymentError(
            code="payment_not_prepared",
            message="서버에서 준비되지 않은 결제입니다.",
            status_code=404,
        )

    purchase_data = purchase_snapshot.to_dict() or {}
    if purchase_data.get("status") == "paid":
        return _build_completed_result(
            user_ref=user_ref,
            payment_id=payment_id,
            purchase_data=purchase_data,
            is_already_processed=True,
        )

    payment = _get_portone_payment(
        payment_id=payment_id,
        api_secret=api_secret,
    )
    _validate_portone_payment(
        payment=payment,
        payment_id=payment_id,
        expected_amount=_as_positive_int(purchase_data.get("paidAmount")),
        expected_store_id=store_id,
    )
    payment_details = _extract_payment_details(payment)

    point_transaction_ref = user_ref.collection(
        "users_point_transaction"
    ).document(f"portone_{payment_id}")
    transaction = database.transaction()

    @firestore.transactional
    def apply_payment(current_transaction):
        current_user = user_ref.get(transaction=current_transaction)
        current_purchase = purchase_ref.get(transaction=current_transaction)

        if not current_user.exists:
            raise PointPaymentError(
                code="user_not_found",
                message="사용자 정보를 찾을 수 없습니다.",
                status_code=404,
            )
        if not current_purchase.exists:
            raise PointPaymentError(
                code="payment_not_prepared",
                message="서버에서 준비되지 않은 결제입니다.",
                status_code=404,
            )

        current_purchase_data = current_purchase.to_dict() or {}
        if current_purchase_data.get("status") == "paid":
            return _build_completed_result_from_snapshots(
                user_snapshot=current_user,
                payment_id=payment_id,
                purchase_data=current_purchase_data,
                is_already_processed=True,
            )
        if current_purchase_data.get("status") != "pending":
            raise PointPaymentError(
                code="invalid_payment_status",
                message="처리할 수 없는 결제 상태입니다.",
                status_code=409,
            )

        point_amount = _as_positive_int(
            current_purchase_data.get("pointAmount")
        )
        expected_amount = _as_positive_int(
            current_purchase_data.get("paidAmount")
        )
        if point_amount <= 0 or expected_amount <= 0:
            raise PointPaymentError(
                code="invalid_payment_order",
                message="결제 주문 정보가 올바르지 않습니다.",
                status_code=500,
            )

        user_data = current_user.to_dict() or {}
        free_point_balance = _as_non_negative_int(
            user_data.get("freePointBalance")
        )
        paid_point_balance = _as_non_negative_int(
            user_data.get("paidPointBalance")
        )
        remaining_paid_point = paid_point_balance + point_amount
        completed_at = firestore.SERVER_TIMESTAMP

        current_transaction.update(
            user_ref,
            {
                "paidPointBalance": remaining_paid_point,
                "updatedAt": completed_at,
            },
        )
        current_transaction.update(
            purchase_ref,
            {
                "status": "paid",
                "portoneTransactionId": payment.get("transactionId"),
                **payment_details,
                "completedAt": completed_at,
            },
        )
        current_transaction.set(
            point_transaction_ref,
            {
                "type": "purchase",
                "source": "purchase",
                "amount": point_amount,
                "pointType": "paid",
                "refType": "purchase",
                "refId": payment_id,
                "createdAt": completed_at,
            },
        )

        return {
            "purchaseId": payment_id,
            "paymentId": payment_id,
            "grantedPoint": point_amount,
            "remainingFreePoint": free_point_balance,
            "remainingPaidPoint": remaining_paid_point,
            "alreadyProcessed": False,
        }

    return apply_payment(transaction)


def _get_portone_config(
    require_api_secret: bool,
) -> tuple[str, str, str]:
    store_id = os.getenv("PORTONE_STORE_ID", "").strip()
    channel_key = os.getenv("PORTONE_CHANNEL_KEY", "").strip()
    api_secret = os.getenv("PORTONE_API_SECRET", "").strip()

    missing = []
    if not store_id:
        missing.append("PORTONE_STORE_ID")
    if not channel_key:
        missing.append("PORTONE_CHANNEL_KEY")
    if require_api_secret and not api_secret:
        missing.append("PORTONE_API_SECRET")
    if missing:
        raise PointPaymentError(
            code="portone_not_configured",
            message=f"서버 환경변수가 필요합니다: {', '.join(missing)}",
            status_code=503,
        )

    return store_id, channel_key, api_secret


def _get_portone_payment(
    payment_id: str,
    api_secret: str,
) -> dict[str, Any]:
    encoded_payment_id = quote(payment_id, safe="")
    request = Request(
        f"https://api.portone.io/payments/{encoded_payment_id}",
        headers={
            "Authorization": f"PortOne {api_secret}",
            "Accept": "application/json",
        },
        method="GET",
    )

    try:
        with urlopen(request, timeout=65) as response:
            body = response.read().decode("utf-8")
    except HTTPError as error:
        try:
            error_data = json.loads(error.read().decode("utf-8"))
            error_message = error_data.get("message") or str(error)
        except (json.JSONDecodeError, UnicodeDecodeError):
            error_message = str(error)
        raise PointPaymentError(
            code="portone_verification_failed",
            message=f"PortOne 결제 조회에 실패했습니다: {error_message}",
            status_code=502,
        ) from error
    except (URLError, TimeoutError) as error:
        raise PointPaymentError(
            code="portone_unreachable",
            message="PortOne 결제 서버에 연결할 수 없습니다.",
            status_code=502,
        ) from error

    try:
        payment = json.loads(body)
    except json.JSONDecodeError as error:
        raise PointPaymentError(
            code="invalid_portone_response",
            message="PortOne 결제 응답을 해석할 수 없습니다.",
            status_code=502,
        ) from error
    if not isinstance(payment, dict):
        raise PointPaymentError(
            code="invalid_portone_response",
            message="PortOne 결제 응답 형식이 올바르지 않습니다.",
            status_code=502,
        )
    return payment


def _validate_portone_payment(
    payment: dict[str, Any],
    payment_id: str,
    expected_amount: int,
    expected_store_id: str,
) -> None:
    if str(payment.get("status", "")).upper() != "PAID":
        raise PointPaymentError(
            code="payment_not_paid",
            message="결제가 완료되지 않았습니다.",
            status_code=409,
        )
    if payment.get("id") != payment_id:
        raise PointPaymentError(
            code="payment_id_mismatch",
            message="결제 번호가 주문 정보와 일치하지 않습니다.",
            status_code=409,
        )

    amount = payment.get("amount")
    paid_total = _as_positive_int(
        amount.get("total") if isinstance(amount, dict) else None
    )
    if expected_amount <= 0 or paid_total != expected_amount:
        raise PointPaymentError(
            code="payment_amount_mismatch",
            message="실제 결제 금액이 주문 금액과 일치하지 않습니다.",
            status_code=409,
        )

    currency = payment.get("currency")
    if isinstance(currency, dict):
        currency = currency.get("code") or currency.get("value")
    if str(currency).upper() != "KRW":
        raise PointPaymentError(
            code="payment_currency_mismatch",
            message="결제 통화가 주문 정보와 일치하지 않습니다.",
            status_code=409,
        )

    response_store_id = payment.get("storeId")
    if response_store_id and response_store_id != expected_store_id:
        raise PointPaymentError(
            code="payment_store_mismatch",
            message="결제 상점 정보가 일치하지 않습니다.",
            status_code=409,
        )


def _extract_payment_details(
    payment: dict[str, Any],
) -> dict[str, Any]:
    method = payment.get("method")
    if not isinstance(method, dict):
        method = {}

    payment_method_type = _normalize_payment_method_type(
        method.get("type")
    )
    card_method = method
    easy_pay_provider = None

    if payment_method_type == "EASY_PAY":
        easy_pay_provider = _as_optional_string(method.get("provider"))
        easy_pay_method = method.get("easyPayMethod")
        if isinstance(easy_pay_method, dict):
            card_method = easy_pay_method

    details: dict[str, Any] = {}
    if payment_method_type:
        details["paymentMethodType"] = payment_method_type
    if easy_pay_provider:
        details["easyPayProvider"] = easy_pay_provider

    if _normalize_payment_method_type(card_method.get("type")) == "CARD":
        card = card_method.get("card")
        if not isinstance(card, dict):
            card = {}

        card_issuer = _as_optional_string(card.get("issuer"))
        masked_card_number = _as_optional_string(card.get("number"))
        approval_number = _as_optional_string(
            card_method.get("approvalNumber")
        )

        if card_issuer:
            details["cardIssuer"] = card_issuer
        if masked_card_number and _is_masked_card_number(
            masked_card_number
        ):
            details["maskedCardNumber"] = masked_card_number
        if approval_number:
            details["approvalNumber"] = approval_number

    paid_at = _parse_portone_timestamp(payment.get("paidAt"))
    if paid_at is not None:
        details["paidAt"] = paid_at

    return details


def _parse_portone_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None

    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None


def _is_masked_card_number(value: str) -> bool:
    return any(character in value for character in ("*", "X", "x"))


def _normalize_payment_method_type(value: Any) -> str | None:
    method_type = _as_optional_string(value)
    if method_type is None:
        return None

    aliases = {
        "PAYMENTMETHODCARD": "CARD",
        "PAYMENTMETHODEASYPAY": "EASY_PAY",
    }
    normalized = method_type.replace("_", "").upper()
    return aliases.get(normalized, method_type.upper())


def _as_optional_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _build_completed_result(
    user_ref,
    payment_id: str,
    purchase_data: dict[str, Any],
    is_already_processed: bool,
) -> dict[str, Any]:
    user_snapshot = user_ref.get()
    if not user_snapshot.exists:
        raise PointPaymentError(
            code="user_not_found",
            message="사용자 정보를 찾을 수 없습니다.",
            status_code=404,
        )
    return _build_completed_result_from_snapshots(
        user_snapshot=user_snapshot,
        payment_id=payment_id,
        purchase_data=purchase_data,
        is_already_processed=is_already_processed,
    )


def _build_completed_result_from_snapshots(
    user_snapshot,
    payment_id: str,
    purchase_data: dict[str, Any],
    is_already_processed: bool,
) -> dict[str, Any]:
    user_data = user_snapshot.to_dict() or {}
    return {
        "purchaseId": payment_id,
        "paymentId": payment_id,
        "grantedPoint": _as_non_negative_int(
            purchase_data.get("pointAmount")
        ),
        "remainingFreePoint": _as_non_negative_int(
            user_data.get("freePointBalance")
        ),
        "remainingPaidPoint": _as_non_negative_int(
            user_data.get("paidPointBalance")
        ),
        "alreadyProcessed": is_already_processed,
    }


def _as_positive_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _as_non_negative_int(value: Any) -> int:
    return max(_as_positive_int(value), 0)
