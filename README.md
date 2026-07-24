# YamYamRoad FastAPI Server

YamYamRoad Flutter 앱에서 사용하는 FastAPI 서버입니다.

현재 다음 기능을 처리합니다.

- 사용자 맞춤 업체·로드 추천
- Firebase ID 토큰 검증
- PortOne 포인트 결제 준비·검증·지급
- 기프티콘 재고 확인·포인트 구매
- 영수증 OCR 결과·GPS 기반 스탬프 검증
- 스탬프·별점·무료 포인트 지급
- 조건별 뱃지 검사·지급
- 인앱 알림 문서 생성 및 FCM 발송

## 1. 파일 구성

```text
YamYamRecommendServer
├─ main.py                    FastAPI 엔드포인트
├─ recommender.py             업체·로드 추천 점수 계산
├─ point_payment.py           PortOne 결제 준비·검증·포인트 지급
├─ gifticon_purchase.py       기프티콘 재고·구매 처리
├─ stamp_verification.py      OCR·GPS 검증 및 스탬프 발행
├─ badge_service.py           조건별 뱃지 검사·지급
├─ notification_service.py    인앱 알림·FCM 발송
├─ requirements.txt           Python 패키지 목록
├─ run_server.bat             Windows 서버 실행 파일
├─ .gitignore                 비밀키·가상환경 제외 설정
└─ README.md
```

다음 파일은 각 개발자 PC에만 두고 Git에는 올리지 않습니다.

```text
.env
Firebase Admin SDK 서비스 계정 JSON
.venv
```

## 2. 최초 실행 준비

Python 3.14 환경을 기준으로 개발했습니다.

VS Code 터미널 또는 PowerShell에서 서버 폴더로 이동합니다.

```powershell
cd C:\YamYamRecommendServer
```

가상환경을 생성합니다.

```powershell
python -m venv .venv
```

필요한 패키지를 설치합니다.

```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 3. Firebase Admin SDK 설정

Firebase Console에서 개발용 서비스 계정 비공개 키를 발급받아 서버 폴더에 둡니다.

예:

```text
YamYamRecommendServer
└─ yamyamroad-firebase-adminsdk-example.json
```

서비스 계정 JSON은 관리자 권한이 포함된 비밀키이므로 Git, Discord, 공개 Drive 등에 올리지 않습니다.

## 4. `.env` 만들기

서버 최상위 폴더에 `.env` 파일을 만들고 다음 형식으로 입력합니다.

```env
# Firebase
GOOGLE_APPLICATION_CREDENTIALS=./yamyamroad-firebase-adminsdk-example.json
FIREBASE_STORAGE_BUCKET=yamyamroad.firebasestorage.app

# PortOne V2
PORTONE_STORE_ID=store-xxxxxxxx
PORTONE_CHANNEL_KEY=channel-key-xxxxxxxx
PORTONE_API_SECRET=xxxxxxxx

# Stamp verification
STAMP_MAX_DISTANCE_METERS=150
STAMP_MAX_SPEED_KMH=200
STAMP_RECEIPT_MAX_AGE_HOURS=6
STAMP_STORE_NAME_THRESHOLD=0.72
STAMP_REWARD_POINT=0

# 로컬 개발에서만 true
STAMP_DEV_BYPASS_ENABLED=false
```

주의:

- `PORTONE_API_SECRET`은 Flutter 앱에 넣지 않습니다.
- `STAMP_DEV_BYPASS_ENABLED=true`는 영수증·GPS 검사를 생략하고 실제 Firestore에 스탬프를 생성합니다.
- 테스트가 끝나면 `STAMP_DEV_BYPASS_ENABLED=false`로 변경합니다.
- `.env`를 변경한 뒤에는 서버를 완전히 종료하고 다시 실행합니다.

## 5. 서버 실행

가장 간단한 실행 방법:

```powershell
.\run_server.bat
```

직접 실행하려면:

```powershell
.\.venv\Scripts\python.exe -m uvicorn main:app --reload --env-file .env
```

정상 실행 확인:

```text
http://127.0.0.1:8000/health
```

예상 응답:

```json
{
  "status": "ok"
}
```

Swagger API 문서:

```text
http://127.0.0.1:8000/docs
```

서버를 종료할 때는 터미널에서 `Ctrl+C`를 누릅니다.

```text
Terminate batch job (Y/N)?
```

서버와 배치 파일을 모두 종료하려면 `Y`를 입력합니다.

## 6. Flutter 앱에서 접속

Android 에뮬레이터에서 같은 PC의 서버로 접속:

```text
http://10.0.2.2:8000
```

현재 Flutter API 클라이언트의 기본 주소가 위 주소로 설정되어 있습니다.

실제 휴대폰에서 PC 서버로 접속하려면 서버를 다음과 같이 실행합니다.

```powershell
.\.venv\Scripts\python.exe -m uvicorn main:app --reload --host 0.0.0.0 --port 8000 --env-file .env
```

Flutter 실행 시 PC의 내부 IP를 전달합니다.

```powershell
flutter run --dart-define=YAMYAM_API_URL=http://192.168.0.10:8000
```

휴대폰과 PC가 같은 네트워크에 연결되어 있어야 하며 Windows 방화벽에서 8000 포트 연결 허용이 필요할 수 있습니다.

## 7. 주요 API

```text
GET  /health
GET  /recommend
POST /point-payments/{pointPackageId}/prepare
POST /point-payments/{paymentId}/complete
POST /gifticons/{gifticonId}/purchase
POST /stamp-verifications
POST /dev/stamps/issue
```

인증이 필요한 API는 Flutter에서 Firebase ID 토큰을 전달합니다.

```http
Authorization: Bearer <Firebase ID Token>
```

## 8. 스탬프 발행 흐름

```text
Flutter 영수증 촬영
→ ML Kit OCR
→ FastAPI 전송
→ Firebase ID 토큰 검증
→ 영수증 상호명·시간 검사
→ GPS 거리 검사
→ 루팅·위치 조작·비정상 속도 검사
→ 영수증 이미지 Storage 업로드
→ verification 승인
→ stamp 생성
→ 업체 별점·stampCount 반영
→ 무료 포인트·거래 내역 생성
→ 뱃지 검사·지급
→ 인앱 알림·FCM 발송
```

## 9. 뱃지 지급

지원 조건:

- `stamp_count`
- `weekly_stamp`
- `monthly_stamp`
- `yearly_stamp`
- `road_progress`

사용자 지급 문서:

```text
users/{userId}/users_badge/{badgeId}
```

`badgeId`를 문서 ID로 사용해 같은 뱃지의 중복 지급을 방지합니다.

스탬프 API 응답에는 다음 값이 포함됩니다.

```json
{
  "badgeGrantStatus": "completed",
  "newBadges": []
}
```

상태 값:

- `completed`: 모든 조건 검사 완료
- `partial`: 일부 조건 검사 실패
- `failed`: 뱃지 지급 처리 전체 실패

복합 인덱스가 필요한 쿼리가 실패하면 스탬프 발행은 유지되고, 서버 로그에 실패한 조건이 출력됩니다.

## 10. 개발용 스탬프 테스트

`.env`:

```env
STAMP_DEV_BYPASS_ENABLED=true
```

Flutter의 이모티콘 탭 하단에서 `개발용 스탬프 테스트` 버튼을 선택하고 실제 `placeId`를 입력합니다.

개발용 발행도 실제로 다음 데이터를 변경합니다.

- `verification` 생성
- `stamp` 생성
- 업체 `stampCount`·별점 반영
- 누적·기간 뱃지 지급
- 스탬프·뱃지 알림 생성

개발용 발행은 `roadId`가 없으므로 `road_progress` 뱃지는 지급하지 않습니다.

테스트 데이터는 자동으로 제거되지 않으므로 테스트 계정을 사용합니다.

## 11. PortOne 결제 테스트

현재 Flutter 결제창은 PortOne 테스트 채널의 일반 카드 결제를 사용합니다.

```text
Flutter 결제창
→ PortOne 테스트 결제
→ FastAPI가 PortOne API로 결제 금액·상태 확인
→ 검증 성공 시 유료 포인트 지급
→ 포인트 거래 내역·알림 생성
```

테스트 결제는 실제 돈이 결제되지 않습니다.

## 12. 자주 발생하는 문제

### `401 Unauthorized`

확인 항목:

1. Flutter에서 Firebase 로그인이 완료됐는지 확인
2. `.env`의 `GOOGLE_APPLICATION_CREDENTIALS` 확인
3. 서비스 계정 JSON과 Flutter Firebase 프로젝트가 같은지 확인
4. `.env` 수정 후 서버 재시작
5. 필요하면 Flutter에서 로그아웃 후 다시 로그인

### `403 dev_bypass_disabled`

`.env`:

```env
STAMP_DEV_BYPASS_ENABLED=true
```

서버를 완전히 재시작합니다.

### `502 Bad Gateway`

PortOne 결제 완료 검증 과정에서 발생할 수 있습니다.

확인 항목:

- `PORTONE_STORE_ID`
- `PORTONE_CHANNEL_KEY`
- `PORTONE_API_SECRET`
- PortOne 테스트 채널 설정
- FastAPI 터미널의 실제 오류 로그

### `badgeGrantStatus: partial`

FastAPI 로그에서 `failedConditions`와 Firestore 인덱스 오류를 확인합니다.

뱃지 일부 조건이 실패해도 이미 승인된 스탬프와 포인트 지급은 취소되지 않습니다.

## 13. Git 업로드 전 확인

```powershell
git status
```

다음 파일이 표시되면 커밋하지 않습니다.

```text
.env
.venv
Firebase Admin SDK JSON
__pycache__
```

이미 커밋한 비밀키는 `.gitignore`를 추가하는 것만으로 제거되지 않습니다. 즉시 Git 기록에서 제거하고 해당 키를 폐기·재발급해야 합니다.
