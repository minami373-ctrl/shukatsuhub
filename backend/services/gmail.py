"""Gmail 認可・取得を集約するモジュール。

`services/gcal.py` が Google カレンダー用に `google_auth_oauthlib` /
`googleapiclient` / `google.oauth2` を独占するのと同じ方針で、**Gmail の呼び出しはここだけ**にする。

方針も `gcal.py` と揃える：**例外を投げてデモを止めない。**設定漏れ・通信失敗は
呼び出し側が seed のメールにフォールバックできるよう、真偽値や専用の例外で返す。

スコープを `gmail.metadata` にしているのは、**本文が API から取得できない**ようにするため。
docs/spec.md §5.1.2 は「AI に本文を渡さない」と定めており、権限の側で保証すれば
実装ミスで本文が AI に流れることが起きない（CLAUDE.md §D の実データ最小化）。

注意：`gmail.metadata` スコープでは `users().messages().list()` の `q` パラメータが使えない
（Google が 403 を返す）。そのため期間の絞り込みはサーバー側で行わず、
`labelIds` で受信トレイに限定して取得し、**受信日時での絞り込みは取得後に行う**。
"""

import email.errors
import email.utils
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from email.header import decode_header, make_header

from dotenv import load_dotenv
from sqlmodel import Session, select

from models import OAuthToken
from services import oauth_scope

load_dotenv()

logger = logging.getLogger(__name__)

PROVIDER = "gmail"

#: メタデータ（ヘッダ）のみ。**本文を取得する権限を取らない**（spec.md §5.1.2）。
SCOPES = ["https://www.googleapis.com/auth/gmail.metadata"]

#: Google の OAuth2 エンドポイント（Credentials の再構築に必要）。
TOKEN_URI = "https://oauth2.googleapis.com/token"

#: 取得対象のラベル。受信トレイに限定する（送信済み・下書きを取り込まない）。
LABEL_IDS = ["INBOX"]

#: 取り込む期間（今日から N 日前まで）。カレンダー同期の SYNC_DAYS と同じ幅に揃える。
SYNC_DAYS = 14

#: 1ページあたりの取得件数。
PAGE_SIZE = 100

#: 1回の同期で取り込む上限。実アカウントの受信トレイ全件を舐めないための安全弁。
#: ルールで決まらないメールは1通ずつ AI に投げる（spec.md §5.1.2）ので、
#: 上限が無いと AI 呼び出しが受信数に比例して増えてしまう。
MAX_MESSAGES = 100

#: 取得失敗時の試行回数（1回だけ再試行する。gcal.MAX_ATTEMPTS と同じ）。
MAX_ATTEMPTS = 2

#: 取得するヘッダ。**本文（body / snippet）は使わない。**
METADATA_HEADERS = ["Subject", "From", "Date"]

#: DB の datetime は naive だが値は JST の壁時計（プロジェクト全体の前提）。
JST = timezone(timedelta(hours=9))


class GmailNotConfigured(Exception):
    """`.env` の GOOGLE_CLIENT_ID / SECRET / GMAIL_REDIRECT_URI が未設定。"""


class GmailSyncFailed(Exception):
    """認可済みだが取得に失敗した（呼び出し側が seed のメールに落とす）。"""


# ---------------------------------------------------------------- 設定と資格情報


def _client_config() -> dict:
    """`.env` の値から `Flow.from_client_config` 用の dict を組む。

    `client_secret.json` をリポジトリに置かないため、ファイルではなく環境変数から作る。
    クライアント ID / シークレットはカレンダーと共用し、**リダイレクト URI だけ別**にする
    （Google Cloud Console 側で `/api/gmail/callback` を承認済みにしておく）。
    """
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    redirect_uri = os.getenv("GMAIL_REDIRECT_URI")
    if not (client_id and client_secret and redirect_uri):
        raise GmailNotConfigured(
            "GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / GMAIL_REDIRECT_URI が未設定です"
        )

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
    """`.env` に必要なキーが揃っているか。"""
    try:
        _client_config()
    except GmailNotConfigured:
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
    """保存済みの gmail トークン行を返す（無ければ None）。

    `provider` はカレンダーの `google` とは別の値なので、
    **カレンダー連携と Gmail 連携は互いに影響しない**（片方だけ解除できる）。
    """
    return session.exec(select(OAuthToken).where(OAuthToken.provider == PROVIDER)).first()


def is_connected(session: Session) -> bool:
    """同期に使えるトークンがあるか。

    `access_token` は失効するので、`refresh_token` があれば繋がっていると見なす。
    """
    token = get_token(session)
    if token is None:
        return False
    return bool(token.refresh_token or token.access_token)


def _naive_utc(value: datetime | None) -> datetime | None:
    """google-auth の `expiry` 用に naive UTC へ揃える。

    google-auth は `expiry` を naive UTC として扱う。aware な値を渡すと
    「can't compare offset-naive and offset-aware datetimes」で落ちる。
    """
    if value is None or value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _credentials(token: OAuthToken):
    """DB の値から Credentials を組み直す。

    `expiry` を渡さないと google-auth は `expired` を常に False と判定し、
    失効しても自動更新が走らない（`gcal.py` で実測済みの落とし穴）。
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


# ---------------------------------------------------------------- 認可


def start_auth(session: Session) -> str:
    """認可 URL を作り、CSRF 用の `state` と PKCE の `code_verifier` を保存して返す。

    `access_type="offline"` でないと `refresh_token` が返らない。
    `code_verifier` を保存しないと `callback` で `Flow` を作り直した時点で失われ、
    Google が `invalid_grant: Missing code verifier.` を返す（`gcal.py` で実測済み）。

    **`include_granted_scopes="true"`（差分認可）は渡さない。**渡すと Google が
    「同じクライアントで過去に許可済みのスコープ」（カレンダーの `calendar.readonly`）を
    合わせて返し、要求と戻りが食い違って oauthlib が
    `Warning: Scope has changed from ... to ...` を投げる（実測で確認）。
    Gmail とカレンダーは `OAuthToken` の行が別なので、差分認可にする必要がない。
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

    `state` が保存値と一致しない場合は `fetch_token` を呼ばずに ValueError を投げる（CSRF 対策）。
    """
    token = get_token(session)
    expected = token.auth_state if token else None
    # secrets.compare_digest でタイミング差から state を推測されないようにする
    if not expected or not state or not secrets.compare_digest(expected, state):
        raise ValueError("state が一致しません")

    flow = _build_flow()
    # 認可開始時の code_verifier を注入する（作り直した Flow には入っていない）
    flow.code_verifier = token.code_verifier
    # 別の Google 連携（カレンダー）を認可済みだと Google が付与済みスコープを
    # 合わせて返し、oauthlib が Scope has changed で失敗させる。その間だけ検査を緩める
    with oauth_scope.relaxed_token_scope():
        flow.fetch_token(code=code)
    creds = flow.credentials

    # 実際に付与されたスコープを検証する（ユーザーが同意画面で権限を絞った場合を検知する）。
    # スコープ名は秘密情報ではないのでログに出してよい（トークンは出さない）
    granted = set(creds.scopes or [])
    if granted and not set(SCOPES).issubset(granted):
        logger.warning(
            "Gmail に必要なスコープが付与されませんでした: 付与=%s", sorted(granted)
        )

    token.access_token = creds.token
    # 再認可では refresh_token が返らないことがある。空で既存値を消さない
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
    """連携を解除する。**`Email` は消さない**（CLAUDE.md §0-⑥）。"""
    token = get_token(session)
    if token is None:
        return False
    session.delete(token)
    session.commit()
    return True


# ---------------------------------------------------------------- 取得


def _service(session: Session, token: OAuthToken):
    """Gmail API のサービスを組む。失効していれば refresh して保存する。"""
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

    return build("gmail", "v1", credentials=creds)


def _decode_header_value(raw: str) -> str:
    """RFC 2047 でエンコードされたヘッダ（`=?UTF-8?B?...?=`）を復号する。

    日本語の件名・表示名はほぼ確実にエンコードされて届くため、そのまま使うと文字化けする。
    復号に失敗しても例外を投げず、生の文字列を返す（デモを止めない）。
    """
    if not raw:
        return ""
    try:
        return str(make_header(decode_header(raw)))
    except (UnicodeDecodeError, LookupError, ValueError, email.errors.MessageError):
        # HeaderParseError は ValueError 系列ではないので明示的に捕まえる。
        # ここで漏らすと fetch_messages の except に飛び、**1通のヘッダ異常で
        # その同期の全メールが seed に落ちる**（他が巻き添えにならない方針に反する）
        logger.warning("メールヘッダを復号できなかったため生の値を使います")
        return raw


def _headers_of(message: dict) -> dict[str, str]:
    """payload.headers を小文字キーの dict にする。"""
    headers = (message.get("payload") or {}).get("headers") or []
    return {
        h["name"].lower(): h.get("value", "")
        for h in headers
        if isinstance(h, dict) and h.get("name")
    }


def _received_at(message: dict, headers: dict[str, str]) -> datetime | None:
    """受信日時を JST の naive datetime にする。

    `internalDate`（Gmail がサーバー受信時刻をエポックミリ秒で持つ値）を優先する。
    ヘッダの `Date` は送信側の時計・書式に依存するので、無いときのフォールバックに使う。
    """
    internal = message.get("internalDate")
    if internal:
        try:
            epoch_ms = int(internal)
        except (TypeError, ValueError):
            epoch_ms = None
        if epoch_ms is not None:
            return datetime.fromtimestamp(epoch_ms / 1000, tz=JST).replace(tzinfo=None)

    raw_date = headers.get("date")
    if raw_date:
        try:
            parsed = email.utils.parsedate_to_datetime(raw_date)
        except (TypeError, ValueError):
            parsed = None
        if parsed is not None:
            if parsed.tzinfo is None:
                return parsed  # offset 無しなら JST の壁時計として扱う
            return parsed.astimezone(JST).replace(tzinfo=None)

    return None


def _to_email_row(message: dict) -> dict | None:
    """Gmail のメッセージ1件を Email の列に写す。取り込めないものは None。

    **本文（body / snippet）は写さない。**`gmail.metadata` スコープでは取得もできない。
    """
    message_id = message.get("id")
    if not message_id:
        return None

    headers = _headers_of(message)

    from_raw = headers.get("from", "")
    from_name, from_address = email.utils.parseaddr(from_raw)
    if not from_address:
        # 送信元が読めないメールは分類もグルーピングもできないので取り込まない
        logger.warning("送信元を読めないメールを取り込みませんでした")
        return None

    received_at = _received_at(message, headers)
    if received_at is None:
        logger.warning("受信日時を読めないメールを取り込みませんでした")
        return None

    return {
        "external_id": f"gmail:{message_id}",
        "account": "gmail",
        "from_address": from_address,
        "from_name": _decode_header_value(from_name) or None,
        "subject": _decode_header_value(headers.get("subject", "")),
        # 本文は取得しない（分類に使わないうえ、スコープ上そもそも取れない）
        "body": None,
        "received_at": received_at,
    }


def sync_window(now: datetime | None = None) -> datetime:
    """取り込む受信日時の下限（今日の N 日前の 00:00）を JST の naive で返す。

    `gmail.metadata` スコープでは `q="newer_than:14d"` が使えないため、
    この値との比較で取得後に絞り込む。
    """
    base = now or datetime.now()
    if base.tzinfo is not None:
        base = base.astimezone(JST).replace(tzinfo=None)
    return (base - timedelta(days=SYNC_DAYS)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )


def _list_message_ids(service) -> list[str]:
    """受信トレイのメッセージ ID を新しい順に集める（上限 MAX_MESSAGES）。"""
    ids: list[str] = []
    page_token = None
    while len(ids) < MAX_MESSAGES:
        res = (
            service.users()
            .messages()
            .list(
                userId="me",
                labelIds=LABEL_IDS,
                maxResults=min(PAGE_SIZE, MAX_MESSAGES - len(ids)),
                pageToken=page_token,
            )
            .execute()
        )
        for item in res.get("messages") or []:
            if item.get("id"):
                ids.append(item["id"])

        page_token = res.get("nextPageToken")
        if not page_token:
            break

    if len(ids) >= MAX_MESSAGES:
        # 打ち切ったことを黙って隠さない（発表で件数を説明できるようにする）
        logger.info("受信トレイの取得を %d 件で打ち切りました", MAX_MESSAGES)
    return ids[:MAX_MESSAGES]


def _fetch_once(service, since: datetime) -> list[dict]:
    """メッセージ ID ごとにメタデータを取得し、期間内のものだけ行に写す。"""
    rows: list[dict] = []
    skipped_old = 0
    for message_id in _list_message_ids(service):
        message = (
            service.users()
            .messages()
            .get(
                userId="me",
                id=message_id,
                format="metadata",  # 本文を取らない（metadata スコープでは full が使えない）
                metadataHeaders=METADATA_HEADERS,
            )
            .execute()
        )
        row = _to_email_row(message)
        if row is None:
            continue
        if row["received_at"] < since:
            skipped_old += 1
            continue
        rows.append(row)

    if skipped_old:
        logger.info("%d 日より前のメール %d 件は取り込みませんでした", SYNC_DAYS, skipped_old)
    return rows


def fetch_messages(session: Session, now: datetime | None = None) -> list[dict]:
    """Gmail から受信メールを取得し、Email に upsert できる行の一覧を返す。

    失敗したら**1回だけ再試行**する（`gcal.fetch_events` と同じ）。
    2回とも失敗したら `GmailSyncFailed`。`now` はテストで基準日時を固定するための引数。
    """
    token = get_token(session)
    if token is None:
        raise GmailSyncFailed("gmail のトークンがありません")

    since = sync_window(now)

    last_error: Exception | None = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            service = _service(session, token)
            return _fetch_once(service, since)
        except Exception as e:
            # トークン・コードが例外文に混ざらないよう、型名だけをログに出す（§6 OAuthToken）
            logger.warning(
                "Gmail の取得に失敗しました（試行%d回目）: %s",
                attempt + 1,
                type(e).__name__,
            )
            last_error = e

    raise GmailSyncFailed("Gmail の取得に失敗しました") from last_error
