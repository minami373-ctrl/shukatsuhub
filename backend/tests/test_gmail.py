"""Gmail 実連携のテスト。

方針は docs/spec.md §3「AI 部分のテスト方針」と `tests/test_gcal.py` に揃える。
**実 API を叩かない。**`services/gmail.py` の `Flow` / `build` をモックに差し替え、
テストするのは「Gmail の周りのコードが正しいか」だけに絞る
（どんなメールが届くか・分類が人間の感覚と合うかは期待値にしない）。
"""

import os
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import OperationalError
from sqlmodel import Session, select

from models import Company, Email, OAuthToken
from services import gmail

GMAIL_ENV = {
    "GOOGLE_CLIENT_ID": "test-client-id",
    "GOOGLE_CLIENT_SECRET": "test-client-secret",
    "GMAIL_REDIRECT_URI": "http://localhost:8000/api/gmail/callback",
}

BASE = datetime(2026, 7, 30, 12, 20)  # 仕様書の基準日時

#: 既定のトークン失効時刻（naive UTC）。**実時刻より未来**にしておく。
#: 過去にすると `_service()` が本物の `credentials.refresh()` を呼び、
#: pytest が実ネットワークへ出てしまう（§3「実 API を叩かない」に反する）。
FAR_FUTURE = datetime(2099, 1, 1)


@pytest.fixture(autouse=True)
def _never_call_azure():
    """AI フォールバックが実 API へ出ないようにする。

    `services/ai.py` は `load_dotenv()` を呼ぶので、開発者の `.env` に Azure の
    認証情報があると pytest から実 API を叩いてしまう。ここで必ず未設定扱いにする。
    """
    with patch("services.ai._get_client", return_value=None):
        yield


def _connect(session: Session, **kwargs) -> OAuthToken:
    """Gmail が認可済みの状態を作る。"""
    token = OAuthToken(
        provider="gmail",
        access_token=kwargs.pop("access_token", "at-1"),
        refresh_token=kwargs.pop("refresh_token", "rt-1"),
        expires_at=kwargs.pop("expires_at", FAR_FUTURE),
        scope=kwargs.pop("scope", " ".join(gmail.SCOPES)),
        updated_at=BASE,
        **kwargs,
    )
    session.add(token)
    session.commit()
    return token


def _epoch_ms(value: datetime) -> str:
    """JST の naive datetime を Gmail の internalDate（エポックミリ秒の文字列）にする。"""
    return str(int(value.replace(tzinfo=gmail.JST).timestamp() * 1000))


def _gmsg(
    message_id: str,
    *,
    subject: str = "一次面接のご案内",
    from_header: str = "採用担当 <recruit@alphatech.co.jp>",
    received_at: datetime | None = None,
    **overrides,
) -> dict:
    """Gmail の messages.get（format=metadata）が返すメッセージを1件作る。"""
    message = {
        "id": message_id,
        "threadId": f"t-{message_id}",
        "internalDate": _epoch_ms(received_at or datetime(2026, 7, 30, 14, 20)),
        "payload": {
            "headers": [
                {"name": "Subject", "value": subject},
                {"name": "From", "value": from_header},
            ]
        },
    }
    message.update(overrides)
    return message


def _mock_service(messages: list[dict], pages: list[dict] | None = None) -> MagicMock:
    """`build()` の戻り値を模した Gmail service。

    `messages.list` は ID の一覧、`messages.get` は ID に対応するメッセージを返す。
    """
    service = MagicMock()
    api = service.users.return_value.messages.return_value

    if pages is None:
        pages = [{"messages": [{"id": m["id"]} for m in messages]}]
    api.list.return_value.execute.side_effect = pages

    by_id = {m["id"]: m for m in messages}

    def get(**kwargs):
        request = MagicMock()
        request.execute.return_value = by_id[kwargs["id"]]
        return request

    api.get.side_effect = get
    return service


# ------------------------------------------------------------------ 未認可


def test_sync_without_token_never_calls_gmail(client, session: Session) -> None:
    """未認可なら Gmail を一切呼ばず、seed のメールを表示し続ける。"""
    with patch.object(gmail, "fetch_messages") as fetch:
        res = client.post("/api/gmail/sync")

    assert res.status_code == 200
    body = res.json()
    assert body["source"] == "seed"
    assert body["added"] == 0
    assert fetch.call_count == 0  # Gmail を一切呼んでいない

    assert client.get("/api/gmail/status").json()["connected"] is False


def test_sync_without_token_keeps_seed_emails(client, session: Session) -> None:
    """未認可の同期が既存の（seed 由来の）メールを消さないこと（CLAUDE.md §0-⑥）。"""
    session.add(
        Email(
            account="icloud",
            from_address="info@beta-inc.jp",
            subject="ES提出期限のリマインド",
            received_at=BASE,
            category="確認",
            thread_key="beta-inc.jp|ES提出期限のリマインド",
        )
    )
    session.commit()

    client.post("/api/gmail/sync")

    assert len(session.exec(select(Email)).all()) == 1


# ------------------------------------------------------------------ 冪等性


@patch.dict("os.environ", GMAIL_ENV)
def test_gmail_sync_is_idempotent(client, session: Session) -> None:
    """同じ3件を2回取り込んでも Email は3件のまま（`external_id` で upsert）。"""
    _connect(session)
    messages = [
        _gmsg("m1"),
        _gmsg("m2", subject="二次面接の日程について"),
        _gmsg("m3", subject="説明会のご案内"),
    ]

    with patch("googleapiclient.discovery.build", return_value=_mock_service(messages)):
        first = client.post("/api/gmail/sync").json()
    with patch("googleapiclient.discovery.build", return_value=_mock_service(messages)):
        second = client.post("/api/gmail/sync").json()

    assert first["source"] == "gmail"
    assert first["added"] == 3
    assert second["added"] == 0
    assert second["updated"] == 3
    assert len(session.exec(select(Email)).all()) == 3

    external_ids = {e.external_id for e in session.exec(select(Email)).all()}
    assert external_ids == {"gmail:m1", "gmail:m2", "gmail:m3"}


# ------------------------------------------------------------------ ヘッダの写し方


@patch.dict("os.environ", GMAIL_ENV)
def test_encoded_japanese_headers_are_decoded(client, session: Session) -> None:
    """RFC 2047 で符号化された件名・表示名を復号すること（生のままだと文字化けする）。

    `=?UTF-8?B?...?=` は「一次面接のご案内」「採用担当」を Base64 にしたもの。
    """
    _connect(session)
    message = _gmsg(
        "m1",
        subject="=?UTF-8?B?5LiA5qyh6Z2i5o6l44Gu44GU5qGI5YaF?=",
        from_header="=?UTF-8?B?5o6h55So5ouF5b2T?= <recruit@alphatech.co.jp>",
    )

    with patch("googleapiclient.discovery.build", return_value=_mock_service([message])):
        client.post("/api/gmail/sync")

    saved = session.exec(select(Email).where(Email.external_id == "gmail:m1")).one()
    assert saved.subject == "一次面接のご案内"
    assert saved.from_name == "採用担当"
    assert saved.from_address == "recruit@alphatech.co.jp"


@patch.dict("os.environ", GMAIL_ENV)
def test_body_is_never_stored(client, session: Session) -> None:
    """本文を保存しないこと（§5.1.2「本文を渡さない」を実装側でも守る）。

    `snippet` が応答に混ざっていても body には入らない。
    """
    _connect(session)
    message = _gmsg("m1", snippet="本文の抜粋がここに入る")

    with patch("googleapiclient.discovery.build", return_value=_mock_service([message])):
        client.post("/api/gmail/sync")

    saved = session.exec(select(Email).where(Email.external_id == "gmail:m1")).one()
    assert saved.body is None
    assert saved.account == "gmail"


@patch.dict("os.environ", GMAIL_ENV)
def test_received_at_comes_from_internal_date_in_jst(client, session: Session) -> None:
    """`internalDate`（エポックミリ秒）を JST の naive datetime に直して保存すること。"""
    _connect(session)
    received = datetime(2026, 7, 30, 14, 20)

    with patch(
        "googleapiclient.discovery.build",
        return_value=_mock_service([_gmsg("m1", received_at=received)]),
    ):
        client.post("/api/gmail/sync")

    saved = session.exec(select(Email).where(Email.external_id == "gmail:m1")).one()
    assert saved.received_at == received


@patch.dict("os.environ", GMAIL_ENV)
def test_date_header_is_used_when_internal_date_is_missing(session: Session) -> None:
    """`internalDate` が無ければ `Date` ヘッダから受信日時を取る（JST へ換算）。"""
    _connect(session)
    message = _gmsg("m1")
    del message["internalDate"]
    # UTC 05:20 = JST 14:20
    message["payload"]["headers"].append(
        {"name": "Date", "value": "Thu, 30 Jul 2026 05:20:00 +0000"}
    )

    with patch("googleapiclient.discovery.build", return_value=_mock_service([message])):
        rows = gmail.fetch_messages(session, now=BASE)

    assert rows[0]["received_at"] == datetime(2026, 7, 30, 14, 20)


@patch.dict("os.environ", GMAIL_ENV)
def test_message_without_sender_is_skipped(session: Session) -> None:
    """送信元が読めないメールは分類もグルーピングもできないので取り込まない。"""
    _connect(session)
    broken = _gmsg("m1", from_header="")

    with patch("googleapiclient.discovery.build", return_value=_mock_service([broken, _gmsg("m2")])):
        rows = gmail.fetch_messages(session, now=BASE)

    assert {row["external_id"] for row in rows} == {"gmail:m2"}


# ------------------------------------------------------------------ 取得範囲と API 引数


def test_sync_window_is_days_before_midnight() -> None:
    """取り込む下限は SYNC_DAYS 日前の 00:00。"""
    assert gmail.sync_window(BASE) == datetime(2026, 7, 16, 0, 0)


@patch.dict("os.environ", GMAIL_ENV)
def test_old_messages_are_not_imported(session: Session) -> None:
    """下限より前に届いたメールは取り込まない。"""
    _connect(session)
    messages = [
        _gmsg("m1", received_at=datetime(2026, 7, 29, 9, 0)),  # 範囲内
        _gmsg("m2", received_at=datetime(2026, 7, 1, 9, 0)),  # 範囲外
    ]

    with patch("googleapiclient.discovery.build", return_value=_mock_service(messages)):
        rows = gmail.fetch_messages(session, now=BASE)

    assert {row["external_id"] for row in rows} == {"gmail:m1"}


@patch.dict("os.environ", GMAIL_ENV)
def test_get_uses_metadata_format_and_list_omits_q(session: Session) -> None:
    """`gmail.metadata` スコープの制約を守っていること。

    - `messages.get` は `format="metadata"`（`full` / `raw` は権限で拒否される）
    - `messages.list` に `q` を渡さない（metadata スコープでは 403 になる）
    """
    _connect(session)
    service = _mock_service([_gmsg("m1")])

    with patch("googleapiclient.discovery.build", return_value=service):
        gmail.fetch_messages(session, now=BASE)

    api = service.users.return_value.messages.return_value
    list_kwargs = api.list.call_args.kwargs
    assert "q" not in list_kwargs
    assert list_kwargs["labelIds"] == gmail.LABEL_IDS
    assert list_kwargs["userId"] == "me"

    get_kwargs = api.get.call_args.kwargs
    assert get_kwargs["format"] == "metadata"
    assert get_kwargs["metadataHeaders"] == gmail.METADATA_HEADERS


@patch.dict("os.environ", GMAIL_ENV)
def test_list_follows_page_tokens(session: Session) -> None:
    """nextPageToken がある限り ID の取得を続ける。"""
    _connect(session)
    messages = [_gmsg("m1"), _gmsg("m2", subject="二次面接の日程")]
    pages = [
        {"messages": [{"id": "m1"}], "nextPageToken": "p2"},
        {"messages": [{"id": "m2"}]},
    ]

    with patch(
        "googleapiclient.discovery.build", return_value=_mock_service(messages, pages=pages)
    ):
        rows = gmail.fetch_messages(session, now=BASE)

    assert len(rows) == 2


@patch.dict("os.environ", GMAIL_ENV)
def test_list_stops_at_max_messages(session: Session) -> None:
    """MAX_MESSAGES で打ち切る（受信トレイ全件を舐めない・AI 呼び出しが膨らまない）。"""
    _connect(session)
    over = gmail.MAX_MESSAGES + 5
    messages = [_gmsg(f"m{i}") for i in range(over)]
    # 1ページで上限を超える件数を返してくる状況
    pages = [{"messages": [{"id": m["id"]} for m in messages]}]

    with patch(
        "googleapiclient.discovery.build", return_value=_mock_service(messages, pages=pages)
    ):
        rows = gmail.fetch_messages(session, now=BASE)

    assert len(rows) == gmail.MAX_MESSAGES


# ------------------------------------------------------------------ 分類との連携


@patch.dict("os.environ", GMAIL_ENV)
def test_rule_decided_mail_never_calls_ai(client, session: Session) -> None:
    """§5.1 のルールで決まる件名は AI に投げない（呼び出し回数 0 で検証）。"""
    _connect(session)
    messages = [_gmsg("m1", subject="一次面接のご案内"), _gmsg("m2", subject="メルマガ配信")]

    with (
        patch("services.ai.classify_email_ai") as classify_ai,
        patch("googleapiclient.discovery.build", return_value=_mock_service(messages)),
    ):
        body = client.post("/api/gmail/sync").json()

    assert classify_ai.call_count == 0
    assert body["ai_decided"] == 0

    saved = {e.external_id: e for e in session.exec(select(Email)).all()}
    assert saved["gmail:m1"].category == "重要"
    assert saved["gmail:m2"].category == "広告"
    assert all(e.decided_by == "rule" for e in saved.values())


@patch.dict("os.environ", GMAIL_ENV)
def test_unresolved_mail_falls_back_to_ai(client, session: Session) -> None:
    """ルールで決まらない件名は AI に回り、`decided_by = "ai"` になる。"""
    _connect(session)
    messages = [_gmsg("m1", subject="いつもお世話になっております")]

    with (
        patch("services.ai.classify_email_ai", return_value=("確認", False, "ai")) as classify_ai,
        patch("googleapiclient.discovery.build", return_value=_mock_service(messages)),
    ):
        body = client.post("/api/gmail/sync").json()

    assert classify_ai.call_count == 1
    assert body["ai_decided"] == 1

    saved = session.exec(select(Email).where(Email.external_id == "gmail:m1")).one()
    assert saved.category == "確認"
    assert saved.decided_by == "ai"


@patch.dict("os.environ", GMAIL_ENV)
def test_classification_finishes_before_any_write(client, session: Session) -> None:
    """分類中に DB へ書き込まないこと（`database is locked` の回帰防止）。

    AI 呼び出しは1通ずつで遅い。書き込みを挟みながら回すと書き込みトランザクションを
    分類の間ずっと保持してしまい、画面のポーリングと衝突して同期が 500 になった。
    分類が全通終わるまで Email が1件も増えていないことで、順序を担保する。
    """
    _connect(session)
    messages = [_gmsg(f"m{i}", subject="いつもお世話になっております") for i in range(3)]
    seen_counts: list[int] = []

    def classify(*_args, **_kwargs):
        # 分類のたびに、その時点で書き込み済みの件数を記録する
        seen_counts.append(len(session.exec(select(Email)).all()))
        return "確認", False, "ai"

    with (
        patch("services.ai.classify_email_ai", side_effect=classify),
        patch("googleapiclient.discovery.build", return_value=_mock_service(messages)),
    ):
        body = client.post("/api/gmail/sync").json()

    assert body["added"] == 3
    # 3通ぶん分類が呼ばれ、そのどの時点でも書き込みは0件だった
    assert len(seen_counts) == 3
    assert seen_counts == [0, 0, 0]


@patch.dict("os.environ", GMAIL_ENV)
def test_locked_database_does_not_return_500(client, session: Session) -> None:
    """DB が使用中でも 500 を返さず seed 表示のまま続けること（デモを止めない）。"""
    _connect(session)

    with (
        patch(
            "routers.gmail._upsert_emails",
            side_effect=OperationalError("INSERT", {}, Exception("database is locked")),
        ),
        patch("googleapiclient.discovery.build", return_value=_mock_service([_gmsg("m1")])),
    ):
        res = client.post("/api/gmail/sync")

    assert res.status_code == 200
    assert res.json()["source"] == "seed"


@patch.dict("os.environ", GMAIL_ENV)
def test_company_and_thread_key_are_resolved(client, session: Session) -> None:
    """ドメイン完全一致で企業を逆引きし、`Re:` を除いた件名でスレッドを畳めること（§5.2）。"""
    _connect(session)
    company = Company(name="アルファテック", domain="alphatech.co.jp")
    session.add(company)
    session.commit()
    session.refresh(company)

    messages = [
        _gmsg("m1", subject="一次面接のご案内"),
        _gmsg("m2", subject="Re: 一次面接のご案内"),
        _gmsg("m3", subject="一次面接のご案内", from_header="info@unknown-domain.example"),
    ]

    with patch("googleapiclient.discovery.build", return_value=_mock_service(messages)):
        client.post("/api/gmail/sync")

    saved = {e.external_id: e for e in session.exec(select(Email)).all()}
    assert saved["gmail:m1"].company_id == company.id
    assert saved["gmail:m2"].company_id == company.id
    # Re: を除いた件名が同じなので同一スレッドに畳まれる
    assert saved["gmail:m1"].thread_key == saved["gmail:m2"].thread_key
    # 未登録ドメインは推測でひも付けない
    assert saved["gmail:m3"].company_id is None
    assert saved["gmail:m3"].thread_key != saved["gmail:m1"].thread_key


# ------------------------------------------------------------------ 認可


@patch.dict("os.environ", GMAIL_ENV)
def test_state_mismatch_never_fetches_token(client, session: Session) -> None:
    """state 不一致を拒否する（モックの呼び出し回数で検証）。"""
    _connect(session, auth_state="expected-state")

    flow = MagicMock()
    with patch("google_auth_oauthlib.flow.Flow.from_client_config", return_value=flow):
        res = client.get("/api/gmail/callback", params={"code": "c", "state": "wrong-state"})

    assert res.status_code == 400
    assert flow.fetch_token.call_count == 0


@patch.dict("os.environ", GMAIL_ENV)
def test_callback_without_saved_state_is_rejected(client, session: Session) -> None:
    """認可を開始していない状態のコールバックを受け付けない。"""
    flow = MagicMock()
    with patch("google_auth_oauthlib.flow.Flow.from_client_config", return_value=flow):
        res = client.get("/api/gmail/callback", params={"code": "c", "state": "s"})

    assert res.status_code == 400
    assert flow.fetch_token.call_count == 0


@patch.dict("os.environ", GMAIL_ENV)
def test_callback_saves_token_and_redirects_to_inbox(client, session: Session) -> None:
    """state が一致すれば fetch_token → credentials を保存し、受信箱へ戻す。"""
    _connect(
        session,
        access_token=None,
        refresh_token=None,
        expires_at=None,
        scope=None,
        auth_state="s-1",
    )

    flow = MagicMock()
    flow.credentials = MagicMock(
        token="new-at",
        refresh_token="new-rt",
        expiry=FAR_FUTURE,
        scopes=list(gmail.SCOPES),
    )
    with patch("google_auth_oauthlib.flow.Flow.from_client_config", return_value=flow):
        res = client.get(
            "/api/gmail/callback",
            params={"code": "code-1", "state": "s-1"},
            follow_redirects=False,
        )

    assert res.status_code == 302
    # 相対パスにすると 8000番（API）の /inbox へ飛んで 404 になる（実測した不具合の回帰防止）。
    # 画面を持つのは 5173番なので絶対 URL で返すこと
    assert res.headers["location"] == "http://localhost:5173/inbox?connected=1"

    token = gmail.get_token(session)
    session.refresh(token)
    assert token.access_token == "new-at"
    assert token.refresh_token == "new-rt"
    assert token.auth_state is None  # 使い終わった state は消える


@patch.dict("os.environ", {**GMAIL_ENV, "FRONTEND_ORIGIN": "http://localhost:4000/"})
def test_redirect_origin_is_configurable(client, session: Session) -> None:
    """戻り先のオリジンを `.env` の FRONTEND_ORIGIN で差し替えられること（末尾の / も許容）。"""
    _connect(session, auth_state="s-1")

    flow = MagicMock()
    flow.credentials = MagicMock(
        token="new-at", refresh_token="new-rt", expiry=FAR_FUTURE, scopes=list(gmail.SCOPES)
    )
    with patch("google_auth_oauthlib.flow.Flow.from_client_config", return_value=flow):
        res = client.get(
            "/api/gmail/callback",
            params={"code": "c", "state": "s-1"},
            follow_redirects=False,
        )

    assert res.headers["location"] == "http://localhost:4000/inbox?connected=1"


@patch.dict("os.environ", GMAIL_ENV)
def test_reauth_keeps_existing_refresh_token(client, session: Session) -> None:
    """再認可で `refresh_token` を消さない（空が返っても既存値を保持する）。"""
    _connect(session, refresh_token="keep-me", auth_state="s-1")

    flow = MagicMock()
    flow.credentials = MagicMock(
        token="new-at", refresh_token=None, expiry=FAR_FUTURE, scopes=list(gmail.SCOPES)
    )
    with patch("google_auth_oauthlib.flow.Flow.from_client_config", return_value=flow):
        client.get(
            "/api/gmail/callback",
            params={"code": "c", "state": "s-1"},
            follow_redirects=False,
        )

    token = gmail.get_token(session)
    session.refresh(token)
    assert token.refresh_token == "keep-me"


@patch.dict("os.environ", GMAIL_ENV)
def test_auth_requests_metadata_scope_only(client, session: Session) -> None:
    """**本文を読む権限を取らない。**認可 URL のスコープが metadata だけであること。

    ここは本物の `Flow` を使う（モックすると PKCE とスコープを検証できない）。
    """
    res = client.get("/api/gmail/auth")

    assert res.status_code == 200
    auth_url = res.json()["auth_url"]
    assert "gmail.metadata" in auth_url
    assert "gmail.readonly" not in auth_url
    assert "gmail.modify" not in auth_url
    # PKCE が有効なこと（保存しないと invalid_grant になる）
    assert "code_challenge=" in auth_url
    assert "code_challenge_method=S256" in auth_url

    token = gmail.get_token(session)
    session.refresh(token)
    assert token.code_verifier
    assert len(token.code_verifier) >= 43  # RFC 7636 の下限


@patch.dict("os.environ", GMAIL_ENV)
def test_callback_injects_code_verifier_into_flow(client, session: Session) -> None:
    """保存した code_verifier を fetch_token の前に Flow へ戻していること。"""
    _connect(session, auth_state="s-1", code_verifier="verifier-123")

    flow = MagicMock()
    flow.credentials = MagicMock(
        token="new-at", refresh_token="new-rt", expiry=FAR_FUTURE, scopes=list(gmail.SCOPES)
    )
    with patch("google_auth_oauthlib.flow.Flow.from_client_config", return_value=flow):
        client.get(
            "/api/gmail/callback",
            params={"code": "c", "state": "s-1"},
            follow_redirects=False,
        )

    assert flow.code_verifier == "verifier-123"
    assert flow.fetch_token.call_count == 1

    token = gmail.get_token(session)
    session.refresh(token)
    assert token.code_verifier is None  # 使い終わったら消す


@patch.dict("os.environ", GMAIL_ENV)
def test_auth_requests_offline_access(client, session: Session) -> None:
    """offline でないと `refresh_token` が返らないので引数も確かめる。"""
    flow = MagicMock()
    flow.authorization_url.return_value = ("https://accounts.google.com/o/oauth2/auth?x=1", "st")
    flow.code_verifier = "verifier-abc"
    with patch("google_auth_oauthlib.flow.Flow.from_client_config", return_value=flow):
        res = client.get("/api/gmail/auth")

    assert res.status_code == 200
    assert flow.authorization_url.call_args.kwargs["access_type"] == "offline"

    token = session.exec(select(OAuthToken).where(OAuthToken.provider == "gmail")).first()
    assert token is not None
    assert token.auth_state == "st"
    assert token.code_verifier == "verifier-abc"


@patch.dict("os.environ", GMAIL_ENV)
def test_auth_does_not_request_incremental_scopes(client, session: Session) -> None:
    """`include_granted_scopes` を渡さないこと（実測した認可失敗の回帰防止）。

    渡すと Google が同じクライアントで許可済みの `calendar.readonly` を合わせて返し、
    要求と戻りが食い違って oauthlib が `Warning: Scope has changed ...` を投げる。
    """
    flow = MagicMock()
    flow.authorization_url.return_value = ("https://accounts.google.com/o/oauth2/auth?x=1", "st")
    flow.code_verifier = "verifier-abc"
    with patch("google_auth_oauthlib.flow.Flow.from_client_config", return_value=flow):
        client.get("/api/gmail/auth")

    assert "include_granted_scopes" not in flow.authorization_url.call_args.kwargs


@patch.dict("os.environ", GMAIL_ENV)
def test_extra_granted_scope_does_not_break_auth(client, session: Session) -> None:
    """カレンダーのスコープが混ざって返っても認可が通ること（同上の回帰防止）。

    `fetch_token` の実行中だけ `OAUTHLIB_RELAX_TOKEN_SCOPE` が立っていることと、
    呼び出しの前後で環境変数が元に戻ること（`services/gcal.py` に影響しない）を見る。
    """
    _connect(session, auth_state="s-1", code_verifier="verifier-123")
    seen: dict[str, str | None] = {}

    flow = MagicMock()
    flow.credentials = MagicMock(
        token="new-at",
        refresh_token="new-rt",
        expiry=FAR_FUTURE,
        # Google が付与済みのカレンダースコープを合わせて返してくる状況
        scopes=[
            "https://www.googleapis.com/auth/calendar.readonly",
            "https://www.googleapis.com/auth/gmail.metadata",
        ],
    )
    flow.fetch_token.side_effect = lambda **_: seen.update(
        relax=os.environ.get("OAUTHLIB_RELAX_TOKEN_SCOPE")
    )

    before = os.environ.get("OAUTHLIB_RELAX_TOKEN_SCOPE")
    with patch("google_auth_oauthlib.flow.Flow.from_client_config", return_value=flow):
        res = client.get(
            "/api/gmail/callback",
            params={"code": "c", "state": "s-1"},
            follow_redirects=False,
        )

    assert res.status_code == 302  # 502 にならない
    assert seen["relax"] == "1"  # fetch_token の最中は緩めている
    # 呼び出しが終われば元に戻っている（カレンダー側の挙動を変えない）
    assert os.environ.get("OAUTHLIB_RELAX_TOKEN_SCOPE") == before

    token = gmail.get_token(session)
    session.refresh(token)
    assert "gmail.metadata" in token.scope


# ------------------------------------------------------------------ フォールバック


def test_auth_returns_503_when_not_configured(client, session: Session) -> None:
    """未設定なら例外を投げずに 503 を返す。"""
    with patch.dict("os.environ", {}, clear=True):
        res = client.get("/api/gmail/auth")

    assert res.status_code == 503


def _real_sdk_errors() -> list:
    """実際の SDK 例外を使う（自作のダミー例外では形が乖離するため）。"""
    from google.auth.exceptions import RefreshError
    from googleapiclient.errors import HttpError

    return [
        RefreshError("トークンを更新できません"),
        HttpError(MagicMock(status=500), b"internal error"),
        TimeoutError("タイムアウト"),
    ]


@pytest.mark.parametrize("error", _real_sdk_errors(), ids=["refresh", "http", "timeout"])
@patch.dict("os.environ", GMAIL_ENV)
def test_fetch_failure_falls_back_to_seed(client, session: Session, error: Exception) -> None:
    """取得に失敗しても例外を投げず、seed のメールを表示し続ける（デモを止めない）。"""
    _connect(session)

    with patch("googleapiclient.discovery.build", side_effect=error):
        res = client.post("/api/gmail/sync")

    assert res.status_code == 200
    assert res.json()["source"] == "seed"


@patch.dict("os.environ", GMAIL_ENV)
def test_fetch_stops_after_two_attempts(client, session: Session) -> None:
    """再試行は1回だけ（無限に叩かない）。2回失敗したら seed に落ちる。"""
    _connect(session)
    from google.auth.exceptions import RefreshError

    with patch("googleapiclient.discovery.build", side_effect=RefreshError("失効")) as build:
        body = client.post("/api/gmail/sync").json()

    assert build.call_count == gmail.MAX_ATTEMPTS == 2
    assert body["source"] == "seed"


@patch.dict("os.environ", GMAIL_ENV)
def test_fetch_retries_once_then_succeeds(client, session: Session) -> None:
    """1回目が失敗しても2回目で取れれば seed に落ちない。"""
    _connect(session)
    from googleapiclient.errors import HttpError

    results = [HttpError(MagicMock(status=503), b"unavailable"), _mock_service([_gmsg("m1")])]

    def build_service(*_args, **_kwargs):
        result = results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    with patch("googleapiclient.discovery.build", side_effect=build_service):
        body = client.post("/api/gmail/sync").json()

    assert body["source"] == "gmail"
    assert body["added"] == 1
    assert results == []  # 2回試行している


@patch.dict("os.environ", GMAIL_ENV)
def test_token_without_env_falls_back_to_seed(client, session: Session) -> None:
    """DB にトークンだけ残り `.env` が消えた状態でも 500 にしない。"""
    _connect(session)
    with patch.dict("os.environ", {}, clear=True):
        res = client.post("/api/gmail/sync")

    assert res.status_code == 200
    assert res.json()["source"] == "seed"


# ------------------------------------------------------------------ トークンの露出


@patch.dict("os.environ", GMAIL_ENV)
def test_status_never_exposes_tokens(client, session: Session) -> None:
    """応答は connected / configured / scope / expires_at のみ。"""
    _connect(session)
    body = client.get("/api/gmail/status").json()

    assert body["connected"] is True
    assert "access_token" not in body
    assert "refresh_token" not in body
    assert "auth_state" not in body
    # 値としても混ざっていない
    assert "at-1" not in str(body)
    assert "rt-1" not in str(body)


# ------------------------------------------------------------------ カレンダーとの独立性


@patch.dict("os.environ", GMAIL_ENV)
def test_gmail_token_is_separate_from_calendar(client, session: Session) -> None:
    """`provider` が別なので、Gmail 連携がカレンダー連携に影響しないこと。"""
    session.add(
        OAuthToken(
            provider="google",
            access_token="cal-at",
            refresh_token="cal-rt",
            expires_at=FAR_FUTURE,
            updated_at=BASE,
        )
    )
    session.commit()
    _connect(session)

    assert client.get("/api/gmail/status").json()["connected"] is True
    assert client.get("/api/calendar/status").json()["connected"] is True

    client.delete("/api/gmail/auth")

    assert client.get("/api/gmail/status").json()["connected"] is False
    # カレンダー側は繋がったまま
    assert client.get("/api/calendar/status").json()["connected"] is True


# ------------------------------------------------------------------ 連携解除


@patch.dict("os.environ", GMAIL_ENV)
def test_disconnect_keeps_emails(client, session: Session) -> None:
    """連携解除でメールを消さない（CLAUDE.md §0-⑥）。"""
    _connect(session)
    with patch(
        "googleapiclient.discovery.build",
        return_value=_mock_service([_gmsg("m1"), _gmsg("m2", subject="説明会のご案内")]),
    ):
        client.post("/api/gmail/sync")
    before = len(session.exec(select(Email)).all())
    assert before == 2

    res = client.delete("/api/gmail/auth")

    assert res.status_code == 200
    assert res.json()["disconnected"] is True
    assert gmail.get_token(session) is None
    assert len(session.exec(select(Email)).all()) == before
