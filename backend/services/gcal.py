"""Google カレンダー認可・取得を集約するモジュール（docs/spec.md §5.7）。

`google_auth_oauthlib` / `googleapiclient` / `google.oauth2` を import するのはここだけ
（`services/ai.py` が `anthropic` を独占するのと同じ方針）。

方針は AI 側と同じで **例外を投げてデモを止めない**。設定漏れ・通信失敗は呼び出し側が
seed 同期にフォールバックできるよう、真偽値や None で返す。
"""

import logging
import os
import re
import secrets
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from sqlmodel import Session, select

from models import Event, OAuthToken
from services import oauth_scope

load_dotenv()

logger = logging.getLogger(__name__)

PROVIDER = "google"

#: 読み取り専用。書き込み権限は取らない（spec.md §2 やらないこと）。
SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

#: Google の OAuth2 エンドポイント（Credentials の再構築に必要）。
TOKEN_URI = "https://oauth2.googleapis.com/token"

#: 取得する期間（今日の 00:00 から N 日後の 23:59）。spec.md §5.7.2。
SYNC_DAYS = 14

#: 1ページあたりの取得件数（Google の上限は 2500 だが控えめにする）。
PAGE_SIZE = 250

#: 取得失敗時の試行回数（1回だけ再試行する。spec.md §5.7.2）。
MAX_ATTEMPTS = 2

#: DB の datetime は naive だが値は JST の壁時計。Google へ渡すときだけ offset を付ける。
JST = timezone(timedelta(hours=9))

#: summary がこれに一致したら kind = 学業（spec.md §5.7.2 の表）。大文字小文字は区別しない。
ACADEMIC_PATTERN = re.compile(
    r"ゼミ|研究室|講義|授業|レポート|課題|実験", re.IGNORECASE
)


class GoogleNotConfigured(Exception):
    """`.env` の GOOGLE_* が未設定（呼び出し側が 503 に変換する）。"""


class GoogleSyncFailed(Exception):
    """認可済みだが取得に失敗した（呼び出し側が seed 同期に落とす）。"""


# ---------------------------------------------------------------- 設定と資格情報


def _client_config() -> dict:
    """`.env` の値から `Flow.from_client_config` 用の dict を組む。

    `client_secret.json` をリポジトリに置かないため、ファイルではなく環境変数から作る。
    """
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    redirect_uri = os.getenv("GOOGLE_REDIRECT_URI")
    if not (client_id and client_secret and redirect_uri):
        raise GoogleNotConfigured("GOOGLE_CLIENT_ID / SECRET / REDIRECT_URI が未設定です")

    return {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": TOKEN_URI,
            "redirect_uris": [redirect_uri],
        }
    }


def is_configured() -> bool:
    """`.env` に GOOGLE_* が揃っているか。"""
    try:
        _client_config()
    except GoogleNotConfigured:
        return False
    return True


def _build_flow():
    """web サーバー用の Flow を作る。

    `InstalledAppFlow` は使わない（ローカルブラウザを勝手に開くのでサーバーから使えない）。
    """
    config = _client_config()
    from google_auth_oauthlib.flow import Flow

    return Flow.from_client_config(
        config,
        scopes=SCOPES,
        redirect_uri=config["web"]["redirect_uris"][0],
    )


def get_token(session: Session) -> OAuthToken | None:
    """保存済みの google トークン行を返す（無ければ None）。"""
    return session.exec(select(OAuthToken).where(OAuthToken.provider == PROVIDER)).first()


def is_connected(session: Session) -> bool:
    """同期に使えるトークンがあるか。

    `access_token` は失効するので、**`refresh_token` があれば繋がっている**と見なす。
    """
    token = get_token(session)
    if token is None:
        return False
    return bool(token.refresh_token or token.access_token)


def _credentials(token: OAuthToken):
    """DB の値から Credentials を組み直す。

    `expiry` を渡さないと google-auth は `expired` を常に False と判定し、
    **失効しても自動更新が一度も走らない**（実測で確認）。必ず渡す。
    """
    config = _client_config()["web"]
    from google.oauth2.credentials import Credentials

    return Credentials(
        token=token.access_token,
        refresh_token=token.refresh_token,
        token_uri=TOKEN_URI,
        client_id=config["client_id"],
        client_secret=config["client_secret"],
        scopes=token.scope.split() if token.scope else list(SCOPES),
        expiry=_naive_utc(token.expires_at),
    )


def _naive_utc(value: datetime | None) -> datetime | None:
    """google-auth の `expiry` 用に naive UTC へ揃える。

    google-auth は `expiry` を **naive UTC** として `datetime.utcnow()` と比較する。
    aware な値を渡すと「can't compare offset-naive and offset-aware datetimes」で落ちるため、
    aware で来た場合は UTC に変換して offset を落とす。
    """
    if value is None or value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------- 認可（§5.7.1）


def start_auth(session: Session) -> str:
    """認可 URL を作り、CSRF 用の `state` と PKCE の `code_verifier` を保存して返す。

    `access_type="offline"` でないと `refresh_token` が返らない。

    `Flow` は既定で PKCE 有効（`autogenerate_code_verifier = True`）なので、
    `authorization_url()` が `code_challenge` を URL に載せ、`flow.code_verifier` を埋める。
    **この値を保存しないと `callback` で `Flow` を作り直した時点で失われ、**
    Google が `invalid_grant: Missing code verifier.` を返す（実測で確認）。

    **`include_granted_scopes="true"`（差分認可）は渡さない。**渡すと Google が
    「同じクライアントで過去に許可済みのスコープ」（Gmail の `gmail.metadata`）を
    合わせて返し、要求と戻りが食い違って oauthlib が
    `Warning: Scope has changed from ... to ...` を投げる（Gmail 側で実測して確認）。
    カレンダーと Gmail は `OAuthToken` の行が別なので、差分認可にする必要がない。
    """
    flow = _build_flow()
    auth_url, state = flow.authorization_url(
        access_type="offline",
        prompt="consent",
    )
    _save_state(session, state, flow.code_verifier)
    return auth_url


def _save_state(session: Session, state: str, code_verifier: str | None) -> None:
    token = get_token(session)
    if token is None:
        token = OAuthToken(provider=PROVIDER, updated_at=datetime.now())
    token.auth_state = state
    token.code_verifier = code_verifier
    token.updated_at = datetime.now()
    session.add(token)
    session.commit()


def finish_auth(session: Session, code: str, state: str) -> None:
    """認可コードをトークンに交換して保存する。

    `state` が保存値と一致しない場合は `fetch_token` を呼ばずに ValueError を投げる
    （CSRF 対策。spec.md §5.7.1 / §7 の受け入れ条件）。
    """
    token = get_token(session)
    expected = token.auth_state if token else None
    # secrets.compare_digest でタイミング差から state を推測されないようにする
    if not expected or not state or not secrets.compare_digest(expected, state):
        raise ValueError("state が一致しません")

    flow = _build_flow()
    # 認可開始時の code_verifier を注入する。作り直した Flow には入っていないため、
    # ここで戻さないと Google が invalid_grant: Missing code verifier. を返す
    flow.code_verifier = token.code_verifier
    # 別の Google 連携（Gmail）を認可済みだと Google が付与済みスコープを
    # 合わせて返し、oauthlib が Scope has changed で失敗させる。その間だけ検査を緩める
    with oauth_scope.relaxed_token_scope():
        flow.fetch_token(code=code)
    creds = flow.credentials

    # 実際に付与されたスコープを検証する（同意画面で権限を絞られた場合を検知する）。
    # スコープ名は秘密情報ではないのでログに出してよい（トークンは出さない）
    granted = set(creds.scopes or [])
    if granted and not set(SCOPES).issubset(granted):
        logger.warning(
            "カレンダーに必要なスコープが付与されませんでした: 付与=%s", sorted(granted)
        )

    token.access_token = creds.token
    # 再認可では refresh_token が返らないことがある。空で既存値を消さない（§7）
    if creds.refresh_token:
        token.refresh_token = creds.refresh_token
    token.expires_at = creds.expiry
    if creds.scopes:
        token.scope = " ".join(creds.scopes)
    token.auth_state = None  # 使い終わった state は消す
    token.code_verifier = None  # 使い終わった code_verifier も残さない
    token.updated_at = datetime.now()
    session.add(token)
    session.commit()


def disconnect(session: Session) -> bool:
    """連携を解除する。`Event` は消さない（CLAUDE.md §0-⑥）。"""
    token = get_token(session)
    if token is None:
        return False
    session.delete(token)
    session.commit()
    return True


# ---------------------------------------------------------------- 取得（§5.7.2）


def _service(session: Session, token: OAuthToken):
    """Calendar API のサービスを組む。失効していれば refresh して保存する。"""
    creds = _credentials(token)

    if not creds.valid:
        from google.auth.transport.requests import Request

        creds.refresh(Request())
        token.access_token = creds.token
        token.expires_at = creds.expiry
        token.updated_at = datetime.now()
        session.add(token)
        session.commit()

    from googleapiclient.discovery import build

    return build("calendar", "v3", credentials=creds)


def _naive_jst(value: datetime) -> datetime:
    """DB 保存用に JST の naive へ揃える（プロジェクト全体が naive JST 前提）。"""
    if value.tzinfo is None:
        return value  # offset 無しで来たら JST の壁時計として扱う
    return value.astimezone(JST).replace(tzinfo=None)


def _to_event_row(item: dict) -> dict | None:
    """Google のイベント1件を Event の列に写す。取り込まないものは None。

    終日予定（`start.date` しか無い）は時間占有が計算できず空き時間算出を壊すので除外する。
    """
    start = (item.get("start") or {}).get("dateTime")
    end = (item.get("end") or {}).get("dateTime")
    if not start or not end:
        return None

    try:
        start_at = datetime.fromisoformat(start)
        end_at = datetime.fromisoformat(end)
    except ValueError:
        logger.warning("Google イベントの日時が ISO 形式ではないため取り込みません")
        return None

    if end_at <= start_at:
        return None

    # SQLite の datetime 列は tz を保持しないので naive に落とす。
    # offset を剥がすだけだと他タイムゾーンの予定が別時刻になるので、必ず JST へ換算する
    start_at = _naive_jst(start_at)
    end_at = _naive_jst(end_at)

    summary = item.get("summary") or "（無題）"
    return {
        "external_id": f"google:{item['id']}",
        "title": summary,
        "kind": "学業" if ACADEMIC_PATTERN.search(summary) else "選考",
        "start_at": start_at,
        "end_at": end_at,
        "location": item.get("location"),
        # 実カレンダーのタイトルから企業を推測しない（§5.2 と同じ方針）
        "company_id": None,
    }


def sync_window(now: datetime | None = None) -> tuple[str, str]:
    """Google に渡す timeMin / timeMax を RFC3339 で作る（§5.7.2）。

    naive な値は JST の壁時計として扱う（プロジェクト全体の前提）。
    **`Z` を付けない。**`Z` は UTC を意味するので、JST の値に付けると 9 時間ずれて
    当日 00:00〜09:00 の予定が取得範囲から漏れる。
    """
    base = now or datetime.now()
    if base.tzinfo is None:
        base = base.replace(tzinfo=JST)

    time_min = base.replace(hour=0, minute=0, second=0, microsecond=0)
    time_max = (base + timedelta(days=SYNC_DAYS)).replace(
        hour=23, minute=59, second=59, microsecond=0
    )
    return time_min.isoformat(), time_max.isoformat()


def _fetch_once(
    session: Session, token: OAuthToken, time_min: str, time_max: str
) -> tuple[list[dict], list[str]]:
    """1回だけ取得を試みる。nextPageToken がある限りページを辿る。"""
    service = _service(session, token)
    rows: list[dict] = []
    cancelled: list[str] = []
    page_token = None
    while True:
        res = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                orderBy="startTime",
                maxResults=PAGE_SIZE,
                pageToken=page_token,
            )
            .execute()
        )
        for item in res.get("items", []):
            if not item.get("id"):
                continue
            if item.get("status") == "cancelled":
                cancelled.append(f"google:{item['id']}")
                continue
            row = _to_event_row(item)
            if row is not None:
                rows.append(row)

        page_token = res.get("nextPageToken")
        if not page_token:
            break

    return rows, cancelled


def _vanished_external_ids(
    session: Session,
    time_min: str,
    time_max: str,
    rows: list[dict],
    cancelled: list[str],
) -> list[str]:
    """Google 側で完全に削除された予定の external_id を検出する。

    `events().list()`（timeMin/timeMax の範囲取得）は削除済みの予定をそもそも返さない
    （`status="cancelled"` が返るのは `syncToken` を使った差分同期のときだけ）。そのため、
    同じ範囲に入っているはずの既存の google 由来イベントと突き合わせ、
    今回の取得結果に含まれなくなったものを「消えた」とみなす。
    """
    window_start = _naive_jst(datetime.fromisoformat(time_min))
    window_end = _naive_jst(datetime.fromisoformat(time_max))

    existing_ids = {
        e.external_id
        for e in session.exec(
            select(Event).where(
                Event.external_id.like("google:%"),
                Event.start_at < window_end,
                Event.end_at > window_start,
            )
        )
    }
    fetched_ids = {row["external_id"] for row in rows}
    already_marked = set(cancelled)
    return list(existing_ids - fetched_ids - already_marked)


def fetch_events(session: Session, now: datetime | None = None) -> tuple[list[dict], list[str]]:
    """Google から予定を取得し (取り込む行, 削除する external_id) を返す。

    失敗したら**1回だけ再試行**する（§5.7.2）。2回とも失敗したら GoogleSyncFailed。
    `now` を引数にしているのはテストで基準日時を固定できるようにするため。
    """
    token = get_token(session)
    if token is None:
        raise GoogleSyncFailed("google のトークンがありません")

    time_min, time_max = sync_window(now)

    for attempt in range(MAX_ATTEMPTS):
        try:
            rows, cancelled = _fetch_once(session, token, time_min, time_max)
            vanished = _vanished_external_ids(session, time_min, time_max, rows, cancelled)
            return rows, cancelled + vanished
        except Exception as e:
            # トークン・コードが例外文に混ざらないよう、型名だけをログに出す（§6 OAuthToken）
            logger.warning(
                "Google カレンダーの取得に失敗しました（試行%d回目）: %s",
                attempt + 1,
                type(e).__name__,
            )
            last_error = e

    raise GoogleSyncFailed("Google カレンダーの取得に失敗しました") from last_error
