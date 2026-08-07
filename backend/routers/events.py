"""イベント取得とカレンダー同期（docs/spec.md §4.2 / §5.4 / §5.7 / API 一覧）。

- GET    /api/events            期間で取得（from / to）
- POST   /api/calendar/sync     Google 認可済みなら実カレンダー、未認可なら seed から upsert
- GET    /api/calendar/auth     Google 認可 URL を返す
- GET    /api/calendar/callback 認可コードを受け取りトークンを保存
- GET    /api/calendar/status   連携済みかを返す（トークン本体は返さない）
- DELETE /api/calendar/auth     連携解除（Event は消さない）

いずれの同期も `external_id` をキーにした upsert なので、2回押しても件数が増えない。
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlmodel import Session, select

from db import get_session
from models import Event
from services import gcal

load_dotenv()

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["calendar"])

#: 認可後に戻る画面のオリジン。
#: **相対パスでリダイレクトしてはいけない。**このルーターは API（8000番）が返すので、
#: `/calendar?connected=1` を返すとブラウザは 8000番の `/calendar` を開き、
#: 画面が無いため 404 になる（Gmail 側で実測して確認）。開発では Vite の 5173番が画面を持つ。
#: `routers/gmail.py` にも同じ定義がある（各ルーターを自己完結させるため意図的に重複させている）。
DEFAULT_FRONTEND_ORIGIN = "http://localhost:5173"


def _calendar_url() -> str:
    """認可後に戻るカレンダー画面の URL（絶対 URL）。"""
    origin = (os.getenv("FRONTEND_ORIGIN") or DEFAULT_FRONTEND_ORIGIN).rstrip("/")
    return f"{origin}/calendar?connected=1"

SEED_PATH = Path(__file__).resolve().parent.parent / "seed" / "calendar.json"

# seed 1件に必要なキー（欠けていたら読み込みを中断し DB を変更しない）
REQUIRED_KEYS = ("external_id", "title", "kind", "start_at", "end_at")
VALID_KINDS = ("選考", "学業")


class SeedError(Exception):
    """seed/calendar.json が読めない・壊れているときに投げる（§5.4 エラー時）。"""


def _parse_seed(seed_path: Path) -> list[dict]:
    """seed を読んで検証済みの dict 一覧にする。1件でも不正なら SeedError。

    DB を触る前に全件を検証するので、途中で失敗しても DB は変更されない。
    """
    try:
        raw = json.loads(seed_path.read_text(encoding="utf-8"))
    except OSError as e:
        raise SeedError(f"seed を読み込めません: {e}") from e
    except json.JSONDecodeError as e:
        raise SeedError(f"seed の JSON が壊れています: {e}") from e

    if not isinstance(raw, list):
        raise SeedError("seed のトップレベルは配列である必要があります")

    parsed: list[dict] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise SeedError(f"{i} 件目がオブジェクトではありません")
        missing = [k for k in REQUIRED_KEYS if not item.get(k)]
        if missing:
            raise SeedError(f"{i} 件目に必須項目がありません: {', '.join(missing)}")
        if item["kind"] not in VALID_KINDS:
            raise SeedError(f"{i} 件目の kind が不正です: {item['kind']}")
        try:
            start_at = datetime.fromisoformat(item["start_at"])
            end_at = datetime.fromisoformat(item["end_at"])
        except ValueError as e:
            raise SeedError(f"{i} 件目の日時が ISO 形式ではありません: {e}") from e
        if end_at <= start_at:
            raise SeedError(f"{i} 件目の end_at が start_at 以前です")

        parsed.append(
            {
                "external_id": item["external_id"],
                "title": item["title"],
                "kind": item["kind"],
                "start_at": start_at,
                "end_at": end_at,
                "location": item.get("location"),
                "company_id": item.get("company_id"),
            }
        )
    return parsed


def _upsert_events(
    session: Session,
    rows: list[dict],
    delete_external_ids: list[str] | None = None,
) -> dict[str, int]:
    """external_id をキーに upsert し、指定された external_id を削除する。

    seed 同期（§5.4）と Google 同期（§5.7.2）で共通。**同じ external_id は更新される**ので、
    何回実行しても件数が増えない。
    """
    added = 0
    updated = 0
    for row in rows:
        existing = session.exec(
            select(Event).where(Event.external_id == row["external_id"])
        ).first()
        if existing is None:
            session.add(Event(**row))
            added += 1
        else:
            for key, value in row.items():
                setattr(existing, key, value)
            session.add(existing)
            updated += 1

    deleted = 0
    for external_id in delete_external_ids or []:
        existing = session.exec(
            select(Event).where(Event.external_id == external_id)
        ).first()
        if existing is not None:
            session.delete(existing)
            deleted += 1

    session.commit()
    return {"added": added, "updated": updated, "deleted": deleted}


def sync_events_from_seed(session: Session, seed_path: Path = SEED_PATH) -> dict[str, int]:
    """external_id をキーに upsert する（§5.4）。戻り値は {added, updated}。"""
    parsed = _parse_seed(seed_path)
    result = _upsert_events(session, parsed)
    # seed 同期は削除を行わないので deleted は返さない（§5.4 の出力仕様のまま）
    return {"added": result["added"], "updated": result["updated"]}


@router.get("/events", response_model=list[Event])
def list_events(
    from_: datetime = Query(..., alias="from", description="期間の開始（ISO 8601）"),
    to: datetime = Query(..., alias="to", description="期間の終了（ISO 8601）"),
    session: Session = Depends(get_session),
) -> list[Event]:
    """期間に重なるイベントを開始時刻の昇順で返す。

    「重なる」判定にしているのは、期間の境界をまたぐ予定（週表示の月曜朝など）を
    カレンダーから消さないため。
    """
    if to <= from_:
        raise HTTPException(status_code=422, detail="to は from より後である必要があります")

    statement = (
        select(Event)
        .where(Event.start_at < to, Event.end_at > from_)
        .order_by(Event.start_at)
    )
    return list(session.exec(statement))


def _sync_from_seed(session: Session, source: str = "seed") -> dict:
    """seed/calendar.json を取り込む（§5.4）。"""
    try:
        result = sync_events_from_seed(session)
    except SeedError as e:
        # DB は変更していない（_parse_seed が全件検証してから書き込むため）
        raise HTTPException(status_code=500, detail=str(e)) from e
    return {**result, "deleted": 0, "source": source}


@router.post("/calendar/sync")
def sync_calendar(session: Session = Depends(get_session)) -> dict:
    """カレンダーを同期する。同じ external_id は更新されるので冪等（§5.4 / §5.7.2）。

    Google 認可済みなら実カレンダー、未認可・取得失敗なら seed に落とす。
    **例外を投げてデモを止めない**（AI 側のフォールバック方針と同じ）。
    """
    if not gcal.is_connected(session):
        # 未認可なら Google を一切呼ばない（§7 の受け入れ条件で呼び出し回数を検証する）
        return _sync_from_seed(session)

    try:
        rows, cancelled = gcal.fetch_events(session)
    except gcal.GoogleSyncFailed:
        logger.info("Google 同期に失敗したため seed 同期に落とします")
        return _sync_from_seed(session)
    except gcal.GoogleNotConfigured:
        logger.info("GOOGLE_* が未設定のため seed 同期に落とします")
        return _sync_from_seed(session)

    result = _upsert_events(session, rows, cancelled)
    return {**result, "source": "google"}


@router.get("/calendar/status")
def calendar_status(session: Session = Depends(get_session)) -> dict:
    """Google 連携済みかを返す。**トークン本体は返さない**（§5.7.1 / §6 OAuthToken）。"""
    token = gcal.get_token(session)
    return {
        "connected": gcal.is_connected(session),
        "configured": gcal.is_configured(),
        "scope": token.scope if token else None,
        "expires_at": token.expires_at if token else None,
    }


@router.get("/calendar/auth")
def calendar_auth(session: Session = Depends(get_session)) -> dict:
    """Google の認可 URL を返す。GOOGLE_* 未設定なら 503（例外にしない）。"""
    try:
        return {"auth_url": gcal.start_auth(session)}
    except gcal.GoogleNotConfigured as e:
        raise HTTPException(status_code=503, detail="Google 連携が設定されていません") from e


@router.get("/calendar/callback")
def calendar_callback(
    code: str = Query(..., description="Google が返す認可コード"),
    state: str = Query(..., description="CSRF 用の state"),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    """認可コードをトークンに交換して保存し、カレンダー画面へ戻す（§5.7.1）。

    `code` / トークンをレスポンスやログに出さない。
    """
    try:
        gcal.finish_auth(session, code=code, state=state)
    except ValueError as e:
        # state 不一致。fetch_token は呼ばれていない
        raise HTTPException(status_code=400, detail="state が一致しません") from e
    except gcal.GoogleNotConfigured as e:
        raise HTTPException(status_code=503, detail="Google 連携が設定されていません") from e
    except Exception as e:
        # description は Google が返す理由（redirect_uri の不一致など）。切り分けに必要。
        # code / トークンは含まれないのでログに出してよい
        logger.warning(
            "Google の認可に失敗しました: %s: %s",
            type(e).__name__,
            getattr(e, "description", "") or str(e),
        )
        raise HTTPException(status_code=502, detail="Google の認可に失敗しました") from e

    return RedirectResponse(url=_calendar_url(), status_code=302)


@router.delete("/calendar/auth")
def calendar_disconnect(session: Session = Depends(get_session)) -> dict:
    """連携を解除する。**`Event` は消さない**（CLAUDE.md §0-⑥ / §7 の受け入れ条件）。"""
    return {"disconnected": gcal.disconnect(session)}
