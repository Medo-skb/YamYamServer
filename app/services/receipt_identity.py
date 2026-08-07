import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Final


_FINGERPRINT_VERSION: Final = "receipt-v1"


@dataclass(frozen=True, slots=True)
class ReceiptIdentity:
    raw_hash: str
    fingerprint: str


@dataclass(frozen=True, slots=True)
class ReceiptContent:
    place_id: str
    purchased_at: datetime
    amount: int | None
    transaction_id: str | None


def build_receipt_identity(
    *,
    receipt_bytes: bytes,
    content: ReceiptContent,
) -> ReceiptIdentity:
    purchased_at_utc = content.purchased_at.astimezone(timezone.utc).replace(
        microsecond=0
    )
    normalized_transaction_id = re.sub(
        r"[^0-9A-Za-z]",
        "",
        content.transaction_id or "",
    ).upper()
    if normalized_transaction_id:
        fingerprint_parts = (
            _FINGERPRINT_VERSION,
            "transaction",
            content.place_id.strip(),
            purchased_at_utc.date().isoformat(),
            normalized_transaction_id,
        )
    else:
        fingerprint_parts = (
            _FINGERPRINT_VERSION,
            "fallback",
            content.place_id.strip(),
            purchased_at_utc.isoformat(),
            "-" if content.amount is None else str(content.amount),
        )
    fingerprint_source = "\x1f".join(fingerprint_parts).encode("utf-8")
    return ReceiptIdentity(
        raw_hash=hashlib.sha256(receipt_bytes).hexdigest(),
        fingerprint=hashlib.sha256(fingerprint_source).hexdigest(),
    )
