from fastapi import BackgroundTasks

from app.services.badges import grant_earned_badges_safely
from app.services.notifications import notify_user_safely


def attach_badge_grants(
    *,
    result: dict,
    user_id: str,
    road_id: str | None,
    background_tasks: BackgroundTasks,
) -> None:
    badge_result = grant_earned_badges_safely(
        user_id=user_id,
        road_id=road_id,
    )
    new_badges = badge_result["newBadges"]
    result["badgeGrantStatus"] = badge_result["status"]
    result["newBadges"] = new_badges
    if badge_result["failedConditions"]:
        result["badgeGrantFailedConditions"] = badge_result["failedConditions"]

    for badge in new_badges:
        badge_id = badge["badgeId"]
        badge_name = badge["name"]
        background_tasks.add_task(
            notify_user_safely,
            user_id=user_id,
            notification_type="badge",
            title="새로운 뱃지 획득",
            body=f"{badge_name} 뱃지를 획득했습니다.",
            ref_type="badge",
            ref_id=badge_id,
            notification_id=f"badge_{badge_id}",
        )
