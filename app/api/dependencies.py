from fastapi import Header, HTTPException
from firebase_admin import auth

from app.core.firebase import ensure_firebase_app


def get_current_uid(
    authorization: str | None = Header(default=None),
) -> str:
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")

    id_token = authorization.removeprefix("Bearer ").strip()
    if not id_token:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")

    try:
        ensure_firebase_app()
        decoded_token = auth.verify_id_token(id_token)
        return decoded_token["uid"]
    except Exception as error:  # noqa: BROAD_EXCEPT_OK — HTTP auth boundary
        raise HTTPException(
            status_code=401,
            detail="유효하지 않은 로그인 정보입니다.",
        ) from error
