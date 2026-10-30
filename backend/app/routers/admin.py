from fastapi import APIRouter, Request, HTTPException
from typing import Dict, Any, List, Optional
from .auth import get_current_user_from_request
from ..models import ScheduleInterviewRequest, SettingsUpdateRequest
from ..database import (
    get_all_candidates, get_all_interviews, get_user_by_id,
    get_interviews_for_candidate, create_interview, get_report_by_interview_id,
    update_interview_status, get_setting, set_setting, get_all_settings,
    get_configured_question_count, get_interview_by_id,
    delete_interview_record, clear_all_interview_history, get_interview_full_details
)

router = APIRouter(prefix="/api/admin", tags=["admin"])

def require_admin(request: Request) -> Dict[str, Any]:
    user = get_current_user_from_request(request)
    if not user or user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin authorization required.")
    return user

@router.get("/dashboard")
async def get_admin_dashboard(request: Request):
    require_admin(request)
    candidates = get_all_candidates()
    interviews = get_all_interviews()

    scheduled_count = len([i for i in interviews if i["status"] == "scheduled"])
    completed_count = len([i for i in interviews if i["status"] == "completed"])

    return {
        "stats": {
            "seekers_count": len(candidates),
            "total_interviews": len(interviews),
            "scheduled_count": scheduled_count,
            "completed_count": completed_count
        },
        "candidates": candidates,
        "interviews": interviews
    }

@router.get("/candidates")
async def list_candidates(request: Request):
    require_admin(request)
    return {"candidates": get_all_candidates()}

@router.get("/candidate/{candidate_id}")
async def get_candidate_detail(candidate_id: int, request: Request):
    require_admin(request)
    candidate = get_user_by_id(candidate_id)
    if not candidate or candidate["role"] != "job_seeker":
        raise HTTPException(status_code=404, detail="Candidate not found.")
    interviews = get_interviews_for_candidate(candidate_id)
    return {
        "candidate": candidate,
        "interviews": interviews
    }

@router.post("/schedule")
async def schedule_interview_route(payload: ScheduleInterviewRequest, request: Request):
    admin = require_admin(request)
    candidate = get_user_by_id(payload.candidateId)
    if not candidate or candidate.get("role") != "job_seeker":
        raise HTTPException(
            status_code=400,
            detail="Invalid candidate ID. Interviews can only be scheduled for genuine registered job seekers."
        )

    q_count = payload.questionCount or get_configured_question_count(payload.jobRole)

    interview = create_interview(
        candidate_id=payload.candidateId,
        admin_id=admin["id"],
        job_role=payload.jobRole,
        experience_level="Mid-Level",
        interview_type=payload.interviewType,
        difficulty=payload.difficulty,
        question_count=q_count,
        duration_minutes=20,
        camera_enabled=False,
        status="scheduled",
        scheduled_date=payload.scheduledDate,
        scheduled_time=payload.scheduledTime
    )
    return {"interview": interview}

@router.post("/cancel/{interview_id}")
async def cancel_interview_route(interview_id: int, request: Request):
    require_admin(request)
    interview = get_interview_by_id(interview_id)
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found.")
    update_interview_status(interview_id, "cancelled")
    return {"message": "Interview cancelled successfully."}

@router.post("/not-attended/{interview_id}")
@router.post("/missed/{interview_id}")
async def mark_interview_not_attended_route(interview_id: int, request: Request):
    require_admin(request)
    interview = get_interview_by_id(interview_id)
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found.")
    if interview["status"] == "completed":
        raise HTTPException(status_code=400, detail="Cannot mark a completed interview as not attended.")
    update_interview_status(interview_id, "not_attended")
    return {"message": "Interview marked as Not Attended."}

@router.get("/interviews/{interview_id}/details")
async def get_interview_details_for_admin(interview_id: int, request: Request):
    require_admin(request)
    details = get_interview_full_details(interview_id)
    if not details:
        raise HTTPException(status_code=404, detail="Interview record not found.")
    return details

@router.delete("/interviews/{interview_id}")
async def delete_single_interview_route(interview_id: int, request: Request):
    require_admin(request)
    interview = get_interview_by_id(interview_id)
    if not interview:
        raise HTTPException(status_code=404, detail="Interview record not found.")
    delete_interview_record(interview_id)
    return {"message": f"Interview record #{interview_id} successfully deleted. Registered candidate account was preserved."}

@router.delete("/interview-history")
async def clear_all_interview_history_route(request: Request):
    require_admin(request)
    count = clear_all_interview_history()
    return {"message": f"All {count} interview history records safely removed from the system. Candidate accounts preserved."}

@router.get("/settings")
async def get_admin_settings(request: Request):
    require_admin(request)
    all_settings = get_all_settings()
    default_cnt = get_configured_question_count()
    return {
        "default_question_count": default_cnt,
        "settings": all_settings
    }

@router.post("/settings")
async def update_admin_settings(payload: SettingsUpdateRequest, request: Request):
    require_admin(request)
    if payload.defaultQuestionCount is not None:
        if not (1 <= payload.defaultQuestionCount <= 50):
            raise HTTPException(status_code=400, detail="Default question count must be between 1 and 50.")
        set_setting("default_question_count", str(payload.defaultQuestionCount))
    elif payload.key:
        if payload.key in ["default_question_count"] or payload.key.startswith("question_count_"):
            try:
                val_int = int(payload.value)
                if not (1 <= val_int <= 50):
                    raise HTTPException(status_code=400, detail="Question count must be between 1 and 50.")
                set_setting(payload.key, str(val_int))
            except (ValueError, TypeError):
                raise HTTPException(status_code=400, detail="Invalid integer for question count.")
        else:
            set_setting(payload.key, str(payload.value))
    else:
        raise HTTPException(status_code=400, detail="No setting provided to update.")

    if payload.roleOverrides:
        for role, count in payload.roleOverrides.items():
            if not (1 <= count <= 50):
                raise HTTPException(status_code=400, detail=f"Question count for {role} must be between 1 and 50.")
            role_key = f"question_count_{role.lower().replace(' ', '_')}"
            set_setting(role_key, str(count))

    return {
        "message": "Settings updated successfully.",
        "default_question_count": get_configured_question_count(),
        "settings": get_all_settings()
    }
