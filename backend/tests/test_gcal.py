"""Google カレンダー実連携のテスト（docs/spec.md §5.7 / §7 の ⑤）。

方針は §3「AI 部分のテスト方針」と同じ。**実 API を叩かない。**
`services/gcal.py` の `Flow` / `build` をモックに差し替え、
テストするのは「Google の周りのコードが正しいか」だけに絞る。
"""

import os
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from sqlmodel import Session, select

from models import Event, OAuthToken
from services import gcal

GOOGLE_ENV = {
    "GOOGLE_CLIENT_ID": "test-client-id",
    "GOOGLE_CLIENT_SECRET": "test-client-secret",
    "GOOGLE_REDIRECT_URI": "http://localhost:8000/api/calendar/callback",
}

BASE = datetime(2026, 7, 30, 12, 20)  # 仕様書の基準日時

#: 既定のトークン失効時刻（naive UTC）。**実時刻より未来**にしておく。
#: 過去にすると `_service()` が本物の `credentials.refresh()` を呼び、
#: pytest が実ネットワークへ出てしまう（§3「実 API を叩かない」に反する）。
FAR_FUTURE = datetime(2099, 1, 1)


def _connect(session: Session, **kwargs) -> OAuthToken:
    """認可済みの状態を作る。"""
    token = OAuthToken(
        provider="google",
        access_token=kwargs.pop("access_token", "at-1"),
        refresh_token=kwargs.pop("refresh_token", "rt-1"),
        expires_at=kwargs.pop("expires_at", FAR_FUTURE),
        scope=kwargs.pop("scope", " ".join(gcal.SCOPES)),
        updated_at=BASE,
        **kwargs,
    )
    session.add(token)
    session.commit()
    return token


def _gitem(
    event_id: str,
    *,
    summary: str = "一次面接",
    start: str = "2026-07-31T15:00:00+09:00",
    end: str = "2026-07-31T16:00:00+09:00",
    **extra,
) -> dict:
    """Google の events.list が返す item を1件作る。"""
    item = {
        "id": event_id,
        "summary": summary,
        "start": {"dateTime": start},
        "end": {"dateTime": end},
    }
    item.update(extra)
    return item


def _mock_service(pages: list[dict]) -> MagicMock:
    """`build()` の戻り値を模した service。pages は events.list の応答を順に返す。"""
    service = MagicMock()
    service.events.return_value.list.return_value.execute.side_effect = pages
    return service


# ------------------------------------------------------------------ 未認可


def test_sync_without_token_never_calls_google(client, session: Session) -> None:
    """§7「未認可でも従来どおり動く」。モックの呼び出し回数 0 で検証する。"""
    with patch.object(gcal, "fetch_events") as fetch:
        res = client.post("/api/calendar/sync")

    assert res.status_code == 200
    body = res.json()
    assert body["source"] == "seed"
    assert body["added"] > 0
    assert fetch.call_count == 0  # Google を一切呼んでいない

    assert client.get("/api/calendar/status").json()["connected"] is False


# ------------------------------------------------------------------ 冪等性


@patch.dict("os.environ", GOOGLE_ENV)
def test_google_sync_is_idempotent(client, session: Session) -> None:
    """§7「Google 同期が冪等」。同じ3件を2回取り込んでも Event は3件のまま。"""
    _connect(session)
    items = [_gitem("g1"), _gitem("g2", summary="二次面接"), _gitem("g3", summary="研究室ゼミ")]

    def build_service(*_args, **_kwargs):
        return _mock_service([{"items": items}])

    with patch("googleapiclient.discovery.build", side_effect=build_service):
        first = client.post("/api/calendar/sync").json()
        second = client.post("/api/calendar/sync").json()

    assert first["source"] == "google"
    assert first["added"] == 3
    assert second["added"] == 0
    assert second["updated"] == 3
    assert len(session.exec(select(Event)).all()) == 3


@patch.dict("os.environ", GOOGLE_ENV)
def test_kind_is_derived_from_summary(client, session: Session) -> None:
    """§5.7.2 の kind 判定。ゼミ・課題はグレー表示になるよう 学業 にする。"""
    _connect(session)
    items = [
        _gitem("g1", summary="一次面接"),
        _gitem("g2", summary="研究室ゼミ"),
        _gitem("g3", summary="課題レポート作成"),
    ]

    with patch("googleapiclient.discovery.build", return_value=_mock_service([{"items": items}])):
        client.post("/api/calendar/sync")

    kinds = {e.external_id: e.kind for e in session.exec(select(Event)).all()}
    assert kinds == {"google:g1": "選考", "google:g2": "学業", "google:g3": "学業"}


@patch.dict("os.environ", GOOGLE_ENV)
def test_other_timezone_events_are_converted_to_jst(client, session: Session) -> None:
    """offset を剥がすだけでは別時刻になるので、JST へ換算して保存すること。"""
    _connect(session)
    # UTC 06:00 = JST 15:00
    item = _gitem(
        "g1", start="2026-07-31T06:00:00+00:00", end="2026-07-31T07:00:00+00:00"
    )

    with patch("googleapiclient.discovery.build", return_value=_mock_service([{"items": [item]}])):
        client.post("/api/calendar/sync")

    event = session.exec(select(Event).where(Event.external_id == "google:g1")).one()
    assert event.start_at == datetime(2026, 7, 31, 15, 0)
    assert event.end_at == datetime(2026, 7, 31, 16, 0)


# ------------------------------------------------------------------ 除外と削除


@patch.dict("os.environ", GOOGLE_ENV)
def test_all_day_and_cancelled_events_are_excluded(client, session: Session) -> None:
    """§7「終日予定とキャンセル済みを取り込まない」。既存の cancelled は削除される。"""
    _connect(session)
    # 先に g2 を入れておき、次の同期で cancelled として消えることを確かめる
    session.add(
        Event(
            external_id="google:g2",
            title="消える予定",
            kind="選考",
            start_at=BASE,
            end_at=BASE + timedelta(hours=1),
        )
    )
    session.commit()

    items = [
        _gitem("g1"),
        _gitem("g2", status="cancelled"),
        # 終日予定は dateTime を持たない
        {
            "id": "g3",
            "summary": "終日イベント",
            "start": {"date": "2026-08-01"},
            "end": {"date": "2026-08-02"},
        },
    ]

    with patch("googleapiclient.discovery.build", return_value=_mock_service([{"items": items}])):
        body = client.post("/api/calendar/sync").json()

    assert body["deleted"] == 1
    external_ids = {e.external_id for e in session.exec(select(Event)).all()}
    assert external_ids == {"google:g1"}


@patch.dict("os.environ", GOOGLE_ENV)
def test_deleted_event_missing_from_response_is_also_removed(client, session: Session) -> None:
    """2026-08-05 追加。`events().list()` は削除済みの予定を `cancelled` 付きで返さず、
    そもそも結果に含めない。取得範囲内にあった既存イベントが結果から消えていたら、
    それも削除対象にすること（cancelled ステータスを待たずに検出する）。
    """
    _connect(session)
    # 取得範囲内（BASE は sync_window の範囲に収まる）に既存イベントを2つ用意する
    session.add(
        Event(
            external_id="google:vanished",
            title="Google側で完全に削除された予定",
            kind="選考",
            start_at=BASE,
            end_at=BASE + timedelta(hours=1),
        )
    )
    # 取得範囲の外にある既存イベントは対象にしない（誤って消さないことの確認）
    outside = BASE + timedelta(days=30)
    session.add(
        Event(
            external_id="google:outside-window",
            title="範囲外の予定",
            kind="選考",
            start_at=outside,
            end_at=outside + timedelta(hours=1),
        )
    )
    session.commit()

    # 応答には g1 だけが含まれ、vanished は含まれない（cancelled ステータスも付いていない）
    items = [_gitem("g1")]

    with patch("googleapiclient.discovery.build", return_value=_mock_service([{"items": items}])):
        rows, cancelled = gcal.fetch_events(session, now=BASE)

    assert "google:vanished" in cancelled
    assert "google:outside-window" not in cancelled
    assert {row["external_id"] for row in rows} == {"google:g1"}


@patch.dict("os.environ", GOOGLE_ENV)
def test_google_sync_keeps_seed_events(client, session: Session) -> None:
    """他人の seed データを Google 同期が壊さないこと（CLAUDE.md §0-⑥）。"""
    _connect(session)
    with patch.object(gcal, "is_connected", return_value=False):
        client.post("/api/calendar/sync")
    seed_count = len(session.exec(select(Event)).all())
    assert seed_count > 0

    with patch(
        "googleapiclient.discovery.build",
        return_value=_mock_service([{"items": [_gitem("g1")]}]),
    ):
        client.post("/api/calendar/sync")

    assert len(session.exec(select(Event)).all()) == seed_count + 1


# ------------------------------------------------------------------ トークン更新


@patch.dict("os.environ", GOOGLE_ENV)
def test_credentials_carry_expiry(session: Session) -> None:
    """`expiry` を渡さないと google-auth は永久に失効しないと判断する（回帰防止）。"""
    token = _connect(session, expires_at=datetime.utcnow() - timedelta(hours=1))

    creds = gcal._credentials(token)

    assert creds.expiry is not None
    assert creds.expired is True  # ここが False だと自動更新が一度も走らない


@patch.dict("os.environ", GOOGLE_ENV)
def test_expired_token_is_refreshed_and_saved(client, session: Session) -> None:
    """失効していれば refresh し、新しい値を DB に保存する（§5.7 の規約）。"""
    _connect(session, expires_at=datetime.utcnow() - timedelta(hours=1))
    new_expiry = datetime.utcnow() + timedelta(hours=1)

    def fake_refresh(self, _request):
        self.token = "refreshed-at"
        self.expiry = new_expiry

    with (
        patch("google.oauth2.credentials.Credentials.refresh", fake_refresh) as _,
        patch(
            "googleapiclient.discovery.build",
            return_value=_mock_service([{"items": [_gitem("g1")]}]),
        ),
    ):
        body = client.post("/api/calendar/sync").json()

    assert body["source"] == "google"
    token = gcal.get_token(session)
    session.refresh(token)
    assert token.access_token == "refreshed-at"
    assert token.expires_at == new_expiry


@patch.dict("os.environ", GOOGLE_ENV)
def test_refresh_failure_falls_back_to_seed(client, session: Session) -> None:
    """更新に失敗しても例外を投げず seed に落ちる（デモを止めない）。"""
    _connect(session, expires_at=datetime.utcnow() - timedelta(hours=1))
    from google.auth.exceptions import RefreshError

    with patch(
        "google.oauth2.credentials.Credentials.refresh", side_effect=RefreshError("失効")
    ) as refresh:
        res = client.post("/api/calendar/sync")

    assert res.status_code == 200
    assert res.json()["source"] == "seed"
    assert refresh.call_count == gcal.MAX_ATTEMPTS  # 1回だけ再試行して諦める


@patch.dict("os.environ", GOOGLE_ENV)
def test_valid_token_is_not_refreshed(client, session: Session) -> None:
    """失効していないトークンで無駄に refresh しない。"""
    _connect(session)  # expires_at は FAR_FUTURE

    with (
        patch("google.oauth2.credentials.Credentials.refresh") as refresh,
        patch(
            "googleapiclient.discovery.build",
            return_value=_mock_service([{"items": [_gitem("g1")]}]),
        ),
    ):
        client.post("/api/calendar/sync")

    assert refresh.call_count == 0


# ------------------------------------------------------------------ 取得範囲


def test_sync_window_keeps_jst_offset() -> None:
    """§5.7.2。`Z` を付けると 9 時間ずれて当日朝の予定が漏れるので付けないこと。"""
    time_min, time_max = gcal.sync_window(BASE)

    assert time_min == "2026-07-30T00:00:00+09:00"
    assert time_max == "2026-08-13T23:59:59+09:00"
    assert not time_min.endswith("Z")
    assert not time_max.endswith("Z")


@patch.dict("os.environ", GOOGLE_ENV)
def test_sync_passes_window_to_google(client, session: Session) -> None:
    """組み立てた timeMin / timeMax が実際に events.list へ渡っていること。"""
    _connect(session)
    service = _mock_service([{"items": []}])

    with patch("googleapiclient.discovery.build", return_value=service):
        gcal.fetch_events(session, now=BASE)

    kwargs = service.events.return_value.list.call_args.kwargs
    assert kwargs["timeMin"] == "2026-07-30T00:00:00+09:00"
    assert kwargs["timeMax"] == "2026-08-13T23:59:59+09:00"
    assert kwargs["singleEvents"] is True
    assert kwargs["orderBy"] == "startTime"


@patch.dict("os.environ", GOOGLE_ENV)
def test_fetch_retries_once_then_succeeds(client, session: Session) -> None:
    """§5.7.2「1回だけ再試行する」。1回目が失敗しても2回目で取れれば seed に落ちない。"""
    _connect(session)
    from googleapiclient.errors import HttpError

    error = HttpError(MagicMock(status=503), b"unavailable")
    build_results = [error, _mock_service([{"items": [_gitem("g1")]}])]

    def build_service(*_args, **_kwargs):
        result = build_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    with patch("googleapiclient.discovery.build", side_effect=build_service):
        body = client.post("/api/calendar/sync").json()

    assert body["source"] == "google"
    assert body["added"] == 1
    assert build_results == []  # 2回試行している


@patch.dict("os.environ", GOOGLE_ENV)
def test_fetch_stops_after_two_attempts(client, session: Session) -> None:
    """再試行は1回だけ（無限に叩かない）。2回失敗したら seed に落ちる。"""
    _connect(session)
    from google.auth.exceptions import RefreshError

    with patch("googleapiclient.discovery.build", side_effect=RefreshError("失効")) as build:
        body = client.post("/api/calendar/sync").json()

    assert build.call_count == gcal.MAX_ATTEMPTS == 2
    assert body["source"] == "seed"


@patch.dict("os.environ", GOOGLE_ENV)
def test_sync_follows_page_tokens(client, session: Session) -> None:
    """nextPageToken がある限り取得を続ける（§5.7.2）。"""
    _connect(session)
    pages = [
        {"items": [_gitem("g1")], "nextPageToken": "p2"},
        {"items": [_gitem("g2", summary="二次面接")]},
    ]

    with patch("googleapiclient.discovery.build", return_value=_mock_service(pages)):
        body = client.post("/api/calendar/sync").json()

    assert body["added"] == 2


# ------------------------------------------------------------------ 認可


@patch.dict("os.environ", GOOGLE_ENV)
def test_state_mismatch_never_fetches_token(client, session: Session) -> None:
    """§7「state 不一致を拒否する」。モックの呼び出し回数で検証する。"""
    _connect(session, auth_state="expected-state")

    flow = MagicMock()
    with patch("google_auth_oauthlib.flow.Flow.from_client_config", return_value=flow):
        res = client.get("/api/calendar/callback", params={"code": "c", "state": "wrong-state"})

    assert res.status_code == 400
    assert flow.fetch_token.call_count == 0


@patch.dict("os.environ", GOOGLE_ENV)
def test_callback_without_saved_state_is_rejected(client, session: Session) -> None:
    """認可を開始していない状態のコールバックを受け付けない。"""
    flow = MagicMock()
    with patch("google_auth_oauthlib.flow.Flow.from_client_config", return_value=flow):
        res = client.get("/api/calendar/callback", params={"code": "c", "state": "s"})

    assert res.status_code == 400
    assert flow.fetch_token.call_count == 0


@patch.dict("os.environ", GOOGLE_ENV)
def test_callback_saves_token_and_clears_state(client, session: Session) -> None:
    """state が一致すれば fetch_token → credentials を保存し、state を消す。"""
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
        expiry=BASE + timedelta(hours=1),
        scopes=list(gcal.SCOPES),
    )
    with patch("google_auth_oauthlib.flow.Flow.from_client_config", return_value=flow):
        res = client.get(
            "/api/calendar/callback",
            params={"code": "code-1", "state": "s-1"},
            follow_redirects=False,
        )

    assert res.status_code == 302
    # 相対パスにすると 8000番（API）の /calendar へ飛んで 404 になる（Gmail 側で実測）。
    # 画面を持つのは 5173番なので絶対 URL で返すこと
    assert res.headers["location"] == "http://localhost:5173/calendar?connected=1"

    token = gcal.get_token(session)
    session.refresh(token)
    assert token.access_token == "new-at"
    assert token.refresh_token == "new-rt"
    assert token.auth_state is None  # 使い終わった state は消える


@patch.dict("os.environ", GOOGLE_ENV)
def test_auth_does_not_request_incremental_scopes(client, session: Session) -> None:
    """`include_granted_scopes` を渡さないこと（Gmail 側で実測した認可失敗の回帰防止）。

    渡すと Google が同じクライアントで許可済みの `gmail.metadata` を合わせて返し、
    要求と戻りが食い違って oauthlib が `Warning: Scope has changed ...` を投げる。
    """
    flow = MagicMock()
    flow.authorization_url.return_value = ("https://accounts.google.com/o/oauth2/auth?x=1", "st")
    flow.code_verifier = "verifier-abc"
    with patch("google_auth_oauthlib.flow.Flow.from_client_config", return_value=flow):
        client.get("/api/calendar/auth")

    assert "include_granted_scopes" not in flow.authorization_url.call_args.kwargs


@patch.dict("os.environ", GOOGLE_ENV)
def test_extra_granted_scope_does_not_break_auth(client, session: Session) -> None:
    """Gmail のスコープが混ざって返っても認可が通ること（同上の回帰防止）。

    `fetch_token` の実行中だけ `OAUTHLIB_RELAX_TOKEN_SCOPE` が立ち、
    呼び出しの前後で環境変数が元に戻ること（他所へ影響しない）を見る。
    """
    _connect(session, auth_state="s-1", code_verifier="verifier-123")
    seen: dict[str, str | None] = {}

    flow = MagicMock()
    flow.credentials = MagicMock(
        token="new-at",
        refresh_token="new-rt",
        expiry=FAR_FUTURE,
        # Google が付与済みの Gmail スコープを合わせて返してくる状況
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
            "/api/calendar/callback",
            params={"code": "c", "state": "s-1"},
            follow_redirects=False,
        )

    assert res.status_code == 302  # 502 にならない
    assert seen["relax"] == "1"
    assert os.environ.get("OAUTHLIB_RELAX_TOKEN_SCOPE") == before

    token = gcal.get_token(session)
    session.refresh(token)
    assert "calendar.readonly" in token.scope


@patch.dict("os.environ", {**GOOGLE_ENV, "FRONTEND_ORIGIN": "http://localhost:4000/"})
def test_redirect_origin_is_configurable(client, session: Session) -> None:
    """戻り先のオリジンを `.env` の FRONTEND_ORIGIN で差し替えられること（末尾の / も許容）。"""
    _connect(session, auth_state="s-1")

    flow = MagicMock()
    flow.credentials = MagicMock(
        token="new-at", refresh_token="new-rt", expiry=FAR_FUTURE, scopes=list(gcal.SCOPES)
    )
    with patch("google_auth_oauthlib.flow.Flow.from_client_config", return_value=flow):
        res = client.get(
            "/api/calendar/callback",
            params={"code": "c", "state": "s-1"},
            follow_redirects=False,
        )

    assert res.headers["location"] == "http://localhost:4000/calendar?connected=1"


@patch.dict("os.environ", GOOGLE_ENV)
def test_reauth_keeps_existing_refresh_token(client, session: Session) -> None:
    """§7「再認可で refresh_token を消さない」。空が返っても既存値を保持する。"""
    _connect(session, refresh_token="keep-me", auth_state="s-1")

    flow = MagicMock()
    flow.credentials = MagicMock(
        token="new-at",
        refresh_token=None,
        expiry=BASE + timedelta(hours=1),
        scopes=list(gcal.SCOPES),
    )
    with patch("google_auth_oauthlib.flow.Flow.from_client_config", return_value=flow):
        client.get(
            "/api/calendar/callback",
            params={"code": "c", "state": "s-1"},
            follow_redirects=False,
        )

    token = gcal.get_token(session)
    session.refresh(token)
    assert token.refresh_token == "keep-me"


@patch.dict("os.environ", GOOGLE_ENV)
def test_auth_saves_pkce_code_verifier(client, session: Session) -> None:
    """PKCE の code_verifier を保存する。

    保存しないと callback で Flow を作り直した時点で失われ、Google が
    `invalid_grant: Missing code verifier.` を返す（実測で確認した不具合の回帰防止）。
    ここは **本物の Flow** を使う（モックすると PKCE の有無を検証できない）。
    """
    res = client.get("/api/calendar/auth")

    assert res.status_code == 200
    auth_url = res.json()["auth_url"]
    assert "code_challenge=" in auth_url
    assert "code_challenge_method=S256" in auth_url

    token = gcal.get_token(session)
    session.refresh(token)
    assert token.code_verifier  # 空でない
    assert len(token.code_verifier) >= 43  # RFC 7636 の下限


@patch.dict("os.environ", GOOGLE_ENV)
def test_callback_injects_code_verifier_into_flow(client, session: Session) -> None:
    """保存した code_verifier を fetch_token の前に Flow へ戻していること。"""
    _connect(session, auth_state="s-1", code_verifier="verifier-123")

    flow = MagicMock()
    flow.credentials = MagicMock(
        token="new-at",
        refresh_token="new-rt",
        expiry=FAR_FUTURE,
        scopes=list(gcal.SCOPES),
    )
    with patch("google_auth_oauthlib.flow.Flow.from_client_config", return_value=flow):
        client.get(
            "/api/calendar/callback",
            params={"code": "c", "state": "s-1"},
            follow_redirects=False,
        )

    # fetch_token を呼ぶ前に注入されている必要がある
    assert flow.code_verifier == "verifier-123"
    assert flow.fetch_token.call_count == 1

    token = gcal.get_token(session)
    session.refresh(token)
    assert token.code_verifier is None  # 使い終わったら消す


@patch.dict("os.environ", GOOGLE_ENV)
def test_auth_returns_url_and_saves_state(client, session: Session) -> None:
    """§5.7.1。offline でないと refresh_token が返らないので引数も確かめる。"""
    flow = MagicMock()
    flow.authorization_url.return_value = ("https://accounts.google.com/o/oauth2/auth?x=1", "st")
    flow.code_verifier = "verifier-abc"  # 本物の Flow は authorization_url でこれを埋める
    with patch("google_auth_oauthlib.flow.Flow.from_client_config", return_value=flow):
        res = client.get("/api/calendar/auth")

    assert res.status_code == 200
    assert res.json()["auth_url"].startswith("https://accounts.google.com/")
    assert flow.authorization_url.call_args.kwargs["access_type"] == "offline"

    token = session.exec(select(OAuthToken).where(OAuthToken.provider == "google")).first()
    assert token is not None
    assert token.auth_state == "st"
    assert token.code_verifier == "verifier-abc"


# ------------------------------------------------------------------ フォールバック


def test_auth_returns_503_when_not_configured(client, session: Session) -> None:
    """§5.7.1。例外を投げずに 503 を返す。"""
    with patch.dict("os.environ", {}, clear=True):
        res = client.get("/api/calendar/auth")

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
@patch.dict("os.environ", GOOGLE_ENV)
def test_fetch_failure_falls_back_to_seed(client, session: Session, error: Exception) -> None:
    """§7「Google が落ちてもデモが止まらない」。例外を投げず source = seed になる。"""
    _connect(session)

    with patch("googleapiclient.discovery.build", side_effect=error):
        res = client.post("/api/calendar/sync")

    assert res.status_code == 200
    body = res.json()
    assert body["source"] == "seed"
    assert body["added"] > 0


@patch.dict("os.environ", GOOGLE_ENV)
def test_token_without_env_falls_back_to_seed(client, session: Session) -> None:
    """DB にトークンだけ残り .env が消えた状態でも 500 にしない。"""
    _connect(session)
    with patch.dict("os.environ", {}, clear=True):
        res = client.post("/api/calendar/sync")

    assert res.status_code == 200
    assert res.json()["source"] == "seed"


# ------------------------------------------------------------------ トークンの露出


@patch.dict("os.environ", GOOGLE_ENV)
def test_status_never_exposes_tokens(client, session: Session) -> None:
    """§7「トークンを外に出さない」。応答は connected / scope / expires_at のみ。"""
    _connect(session)
    body = client.get("/api/calendar/status").json()

    assert body["connected"] is True
    assert "access_token" not in body
    assert "refresh_token" not in body
    assert "auth_state" not in body
    # 値としても混ざっていない
    assert "at-1" not in str(body)
    assert "rt-1" not in str(body)


# ------------------------------------------------------------------ 連携解除


@patch.dict("os.environ", GOOGLE_ENV)
def test_disconnect_keeps_events(client, session: Session) -> None:
    """§7「連携解除でイベントを消さない」（CLAUDE.md §0-⑥）。"""
    _connect(session)
    with patch(
        "googleapiclient.discovery.build",
        return_value=_mock_service([{"items": [_gitem("g1")]}]),
    ):
        client.post("/api/calendar/sync")
    before = len(session.exec(select(Event)).all())
    assert before > 0

    res = client.delete("/api/calendar/auth")

    assert res.status_code == 200
    assert res.json()["disconnected"] is True
    assert gcal.get_token(session) is None
    assert len(session.exec(select(Event)).all()) == before
