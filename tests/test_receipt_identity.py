from datetime import datetime, timezone

from app.services.receipt_identity import ReceiptContent, build_receipt_identity


def test_same_receipt_content_keeps_fingerprint_when_image_changes() -> None:
    # Given
    purchased_at = datetime(2026, 8, 7, 4, 5, 6, tzinfo=timezone.utc)

    # When
    original = build_receipt_identity(
        receipt_bytes=b"original image",
        content=ReceiptContent(
            place_id="place_daerim",
            purchased_at=purchased_at,
            amount=12_000,
            transaction_id="1234-5678",
        ),
    )
    edited = build_receipt_identity(
        receipt_bytes=b"edited image",
        content=ReceiptContent(
            place_id="place_daerim",
            purchased_at=purchased_at,
            amount=13_000,
            transaction_id="12345678",
        ),
    )

    # Then
    assert original.raw_hash != edited.raw_hash
    assert original.fingerprint == edited.fingerprint


def test_different_receipt_content_gets_different_fingerprint() -> None:
    # Given
    purchased_at = datetime(2026, 8, 7, 4, 5, 6, tzinfo=timezone.utc)

    # When
    first = build_receipt_identity(
        receipt_bytes=b"same image bytes are not required",
        content=ReceiptContent(
            place_id="place_daerim",
            purchased_at=purchased_at,
            amount=12_000,
            transaction_id=None,
        ),
    )
    second = build_receipt_identity(
        receipt_bytes=b"another image",
        content=ReceiptContent(
            place_id="place_daerim",
            purchased_at=purchased_at,
            amount=13_000,
            transaction_id=None,
        ),
    )

    # Then
    assert first.fingerprint != second.fingerprint


def test_same_receipt_without_transaction_id_keeps_fingerprint() -> None:
    # Given
    purchased_at = datetime(2026, 8, 7, 4, 5, 6, tzinfo=timezone.utc)

    # When
    original = build_receipt_identity(
        receipt_bytes=b"original image",
        content=ReceiptContent(
            place_id="place_daerim",
            purchased_at=purchased_at,
            amount=12_000,
            transaction_id=None,
        ),
    )
    edited = build_receipt_identity(
        receipt_bytes=b"edited image",
        content=ReceiptContent(
            place_id="place_daerim",
            purchased_at=purchased_at,
            amount=12_000,
            transaction_id=None,
        ),
    )

    # Then
    assert original.fingerprint == edited.fingerprint
