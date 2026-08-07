"""プロフィール API（spec.md §4.4 / §5.5）。

GET  /api/profile … プロフィール ＋ completeness
PUT  /api/profile … 9項目を更新（単一レコード id = 1。無ければ作成）
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from db import get_session
from models import (
    PROFILE_FIELD_LABELS,
    PROFILE_FIELDS,
    PROFILE_ID,
    PROFILE_MAX_LENGTH,
    Profile,
    completeness,
)

router = APIRouter(prefix="/api/profile", tags=["profile"])


class ProfileBody(BaseModel):
    """PUT のリクエストボディ。9項目すべて任意で、空文字を許容する（spec.md §5.5）。"""

    gakuchika: str = ""
    strengths: str = ""
    self_pr: str = ""
    academics: str = ""
    motivation_template: str = ""
    job_axis: str = ""
    skills: str = ""
    career_plan: str = ""
    teamwork: str = ""


class ProfileResponse(ProfileBody):
    """レスポンス。completeness は保存しない導出値（spec.md §6）。"""

    completeness: int


def _to_response(profile: Profile) -> ProfileResponse:
    return ProfileResponse(
        **{name: getattr(profile, name) for name in PROFILE_FIELDS},
        completeness=completeness(profile),
    )


def _get_or_create(session: Session) -> Profile:
    profile = session.get(Profile, PROFILE_ID)
    if profile is None:
        profile = Profile(id=PROFILE_ID)
        session.add(profile)
    return profile


@router.get("", response_model=ProfileResponse)
def read_profile(session: Session = Depends(get_session)) -> ProfileResponse:
    """未保存でも空のプロフィールを返す（画面が落ちないように）。"""
    profile = session.get(Profile, PROFILE_ID)
    return _to_response(profile or Profile(id=PROFILE_ID))


@router.put("", response_model=ProfileResponse)
def update_profile(
    body: ProfileBody, session: Session = Depends(get_session)
) -> ProfileResponse:
    too_long = [
        PROFILE_FIELD_LABELS[name]
        for name in PROFILE_FIELDS
        if len(getattr(body, name)) > PROFILE_MAX_LENGTH
    ]
    if too_long:
        # 1項目でも超過していたら9項目とも保存しない（spec.md §5.5 エラー時）
        raise HTTPException(
            # starlette の 422 定数は名称変更の途中で非推奨警告が出るため数値で書く
            status_code=422,
            detail=f"{'・'.join(too_long)} は{PROFILE_MAX_LENGTH}文字以内で入力してください",
        )

    profile = _get_or_create(session)
    for name in PROFILE_FIELDS:
        setattr(profile, name, getattr(body, name))
    session.add(profile)
    session.commit()
    session.refresh(profile)
    return _to_response(profile)
