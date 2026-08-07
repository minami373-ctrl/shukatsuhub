"""Gmail 実連携（認可・同期）。

- POST   /api/gmail/sync     認可済みなら Gmail から取り込む。未認可・失敗なら seed のまま
- GET    /api/gmail/auth     Gmail 認可 URL を返す
- GET    /api/gmail/callback 認可コードを受け取りトークンを保存 → /inbox へ戻す
- GET    /api/gmail/status   連携済みかを返す（トークン本体は返さない）
- DELETE /api/gmail/auth     連携解除（`Email` は消さない）

`routers/events.py` のカレンダー同期と同じ作法にしている：
**`external_id` をキーにした upsert なので2回押しても件数が増えない**、
設定漏れ・通信失敗では例外を投げず seed 側に落ちてデモが止まらない。

分類は `services/classifier.py`（ルール優先＋AIフォールバック。docs/spec.md §5.1）を
そのまま呼ぶ。**ここに分類ロジックを複製しない。**
"""

import logging
import os

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.exc import OperationalError
from sqlmodel import Session, select

from db import get_session
from models import Company, Email
from services import gmail, grouping
from services.classifier import classify_email

load_dotenv()

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/gmail", tags=["gmail"])

#: 認可後に戻る画面のオリジン。
#: **相対パスでリダイレクトしてはいけない。**このルーターは API（8000番）が返すので、
#: `/inbox?connected=1` を返すとブラウザは 8000番の `/inbox` を開き、
#: 画面が無いため 404 になる（実測で確認）。開発では Vite の 5173番が画面を持つ。
DEFAULT_FRONTEND_ORIGIN = "http://localhost:5173"


def _inbox_url() -> str:
    """認可後に戻る受信箱の URL（絶対 URL）。"""
    origin = (os.getenv("FRONTEND_ORIGIN") or DEFAULT_FRONTEND_ORIGIN).rstrip("/")
    return f"{origin}/inbox?connected=1"


def _upsert_emails(session: Session, rows: list[dict]) -> dict[str, int]:
    """`external_id` をキーに Email を upsert する。

    同じ `external_id` は更新されるので、何回同期しても件数が増えない
    （`routers/events.py` の `_upsert_events` と同じ考え方）。

    分類・企業の逆引き・スレッドキーは取り込むたびに再計算する。件名が同じなら
    ルール判定は同じ結果になり（§5.1.1 は決定的）、AI に投げるのは保留分だけ。

    **DB を触る処理と分類を混ぜない。**分類は1通ずつ AI を呼ぶので遅く、
    書き込みを挟みながら回すとトランザクションが分類の間ずっと開いたままになる。
    画面は `/api/emails` などを定期的に取りに来るため、これが衝突して
    `sqlite3.OperationalError: database is locked` になった（実測で確認）。
    そこで ①企業の読み出し ②分類（DB を触らない） ③書き込み の3段に分け、
    書き込みトランザクションを最後の一瞬だけに縮める。
    """
    # ① 企業を読み、読み取りトランザクションをすぐ閉じる（分類の間ロックを持たない）
    companies = list(session.exec(select(Company)))
    session.commit()

    # ② 分類。ここでは DB を一切触らない（AI 呼び出しで数秒かかることがある）
    classified: list[dict] = []
    for row in rows:
        category, needs_reply, decided_by = classify_email(row["from_address"], row["subject"])
        classified.append(
            {
                **row,
                "category": category,
                "needs_reply": needs_reply,
                "decided_by": decided_by,
                "company_id": grouping.resolve_company_id(row["from_address"], companies),
                "thread_key": grouping.build_thread_key(
                    row["from_address"], row["subject"], companies
                ),
            }
        )

    ai_decided = sum(1 for values in classified if values["decided_by"] == "ai")
    if not classified:
        return {"added": 0, "updated": 0, "ai_decided": 0}

    # ③ 既存行を1回でまとめて引き、追加・更新して1回だけ commit する
    external_ids = [values["external_id"] for values in classified]
    existing = {
        row.external_id: row
        for row in session.exec(select(Email).where(Email.external_id.in_(external_ids)))
    }

    added = 0
    updated = 0
    for values in classified:
        found = existing.get(values["external_id"])
        if found is None:
            session.add(Email(**values))
            added += 1
        else:
            for key, value in values.items():
                setattr(found, key, value)
            session.add(found)
            updated += 1

    session.commit()
    logger.info("Gmail 同期: 追加 %d 件・更新 %d 件（うち AI 判定 %d 件）", added, updated, ai_decided)
    return {"added": added, "updated": updated, "ai_decided": ai_decided}


def _seed_result() -> dict:
    """未認可・取得失敗のときの応答。

    seed のメールは `python -m seed.load` で既に DB に入っているので、
    ここでは**何も書き換えず件数 0 を返す**（再投入すると seed 側に upsert キーが無く
    重複するため。カレンダーが seed を読み直せるのは `external_id` を持っているから）。
    受信箱は seed のメールを表示し続けるのでデモは止まらない。
    """
    return {"added": 0, "updated": 0, "ai_decided": 0, "source": "seed"}


@router.post("/sync")
def sync_gmail(session: Session = Depends(get_session)) -> dict:
    """Gmail を同期する。同じ `external_id` は更新されるので冪等。

    未認可・設定漏れ・取得失敗では**例外を投げず** seed 側に落とす
    （カレンダー同期・AI フォールバックと同じ方針）。
    """
    if not gmail.is_connected(session):
        # 未認可なら Gmail を一切呼ばない（テストで呼び出し回数 0 を検証する）
        return _seed_result()

    try:
        rows = gmail.fetch_messages(session)
    except gmail.GmailSyncFailed:
        logger.info("Gmail 同期に失敗したため seed のメールを表示し続けます")
        return _seed_result()
    except gmail.GmailNotConfigured:
        logger.info("GMAIL_REDIRECT_URI 等が未設定のため seed のメールを表示し続けます")
        return _seed_result()

    try:
        result = _upsert_emails(session, rows)
    except OperationalError:
        # 例：他のリクエストと衝突した `database is locked`。
        # 500 を返さず seed 表示のまま続ける（取り込みは次の同期で再試行できる）
        session.rollback()
        logger.warning("Gmail の取り込み中に DB が使用中だったため、今回の同期を中止しました")
        return _seed_result()

    return {**result, "source": "gmail"}


@router.get("/status")
def gmail_status(session: Session = Depends(get_session)) -> dict:
    """Gmail 連携済みかを返す。**トークン本体は返さない**（§6 OAuthToken）。"""
    token = gmail.get_token(session)
    return {
        "connected": gmail.is_connected(session),
        "configured": gmail.is_configured(),
        "scope": token.scope if token else None,
        "expires_at": token.expires_at if token else None,
    }


@router.get("/auth")
def gmail_auth(session: Session = Depends(get_session)) -> dict:
    """Gmail の認可 URL を返す。未設定なら 503（例外にしない）。"""
    try:
        return {"auth_url": gmail.start_auth(session)}
    except gmail.GmailNotConfigured as e:
        raise HTTPException(status_code=503, detail="Gmail 連携が設定されていません") from e


@router.get("/callback")
def gmail_callback(
    code: str = Query(..., description="Google が返す認可コード"),
    state: str = Query(..., description="CSRF 用の state"),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    """認可コードをトークンに交換して保存し、受信箱へ戻す。

    `code` / トークンをレスポンスやログに出さない。
    """
    try:
        gmail.finish_auth(session, code=code, state=state)
    except ValueError as e:
        # state 不一致。fetch_token は呼ばれていない
        raise HTTPException(status_code=400, detail="state が一致しません") from e
    except gmail.GmailNotConfigured as e:
        raise HTTPException(status_code=503, detail="Gmail 連携が設定されていません") from e
    except Exception as e:
        # description は Google が返す理由（redirect_uri の不一致など）。切り分けに必要。
        # code / トークンは含まれないのでログに出してよい
        logger.warning(
            "Gmail の認可に失敗しました: %s: %s",
            type(e).__name__,
            getattr(e, "description", "") or str(e),
        )
        raise HTTPException(status_code=502, detail="Gmail の認可に失敗しました") from e

    return RedirectResponse(url=_inbox_url(), status_code=302)


@router.delete("/auth")
def gmail_disconnect(session: Session = Depends(get_session)) -> dict:
    """連携を解除する。**`Email` は消さない**（CLAUDE.md §0-⑥）。"""
    return {"disconnected": gmail.disconnect(session)}
