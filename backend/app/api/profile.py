import json
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.profile import UserProfile
from app.schemas.profile import ProfileRead, ProfileUpdate, ResumeUploadResponse
from app.services.extraction import extract_skills
from app.services.query_cache import invalidate_jobs_query_cache
from app.services.resume_parser import extract_resume_text

router = APIRouter(prefix="/profile", tags=["profile"])

UPLOAD_DIR = Path(__file__).resolve().parents[2] / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def _get_or_create_profile(db: Session) -> UserProfile:
    profile = db.scalar(select(UserProfile).order_by(UserProfile.id.asc()))
    if profile:
        patched = False
        if not profile.score_tuning_mode:
            profile.score_tuning_mode = "balanced"
            patched = True
        if profile.hobbies_json is None:
            profile.hobbies_json = json.dumps([])
            patched = True
        if patched:
            db.add(profile)
            db.commit()
            db.refresh(profile)
        return profile
    profile = UserProfile(
        skills_json=json.dumps([]),
        hobbies_json=json.dumps([]),
        distance_miles=30,
        score_tuning_mode="balanced",
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


def _serialize(profile: UserProfile) -> ProfileRead:
    return ProfileRead(
        id=profile.id,
        full_name=profile.full_name,
        email=profile.email,
        phone=profile.phone,
        zip_code=profile.zip_code,
        distance_miles=profile.distance_miles,
        skills=json.loads(profile.skills_json or "[]"),
        hobbies=json.loads(profile.hobbies_json or "[]"),
        score_tuning_mode=profile.score_tuning_mode or "balanced",
        resume_path=profile.resume_path,
        resume_filename=profile.resume_filename,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
        last_rescored_at=profile.last_rescored_at,
    )


@router.get("", response_model=ProfileRead)
def get_profile(db: Session = Depends(get_db)):
    return _serialize(_get_or_create_profile(db))


@router.patch("", response_model=ProfileRead)
def update_profile(payload: ProfileUpdate, db: Session = Depends(get_db)):
    profile = _get_or_create_profile(db)
    values = payload.model_dump(exclude_none=True)
    for key, value in values.items():
        if key == "skills":
            profile.skills_json = json.dumps(value)
        elif key == "hobbies":
            profile.hobbies_json = json.dumps(value)
        else:
            setattr(profile, key, value)
    db.add(profile)
    db.commit()
    db.refresh(profile)
    invalidate_jobs_query_cache()
    return _serialize(profile)


@router.post("/resume", response_model=ResumeUploadResponse)
async def upload_resume(file: UploadFile = File(...), db: Session = Depends(get_db)):
    profile = _get_or_create_profile(db)
    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing file name")

    suffix = Path(file.filename).suffix.lower()
    if suffix not in {".pdf", ".doc", ".docx", ".txt"}:
        raise HTTPException(status_code=400, detail="Resume must be pdf/doc/docx/txt")

    target = UPLOAD_DIR / f"profile_{profile.id}_resume{suffix}"
    content = await file.read()
    target.write_bytes(content)

    profile.resume_path = str(target)
    profile.resume_filename = file.filename
    resume_text = extract_resume_text(target)
    warning: str | None = None
    extracted_count = 0
    if resume_text:
        extracted = extract_skills(resume_text)
        # A new resume should replace the previous resume-derived signal, not accumulate older versions.
        profile.skills_json = json.dumps(sorted(set(extracted)))
        extracted_count = len(extracted)
    else:
        warning = (
            "Could not extract text from this resume file. "
            "Please upload a text-based PDF/DOCX or add skills in Profile so scoring can use your resume signal."
        )
    db.add(profile)
    db.commit()
    invalidate_jobs_query_cache()

    return ResumeUploadResponse(
        resume_path=str(target),
        resume_filename=file.filename,
        extracted_skills_count=extracted_count,
        warning=warning,
    )
