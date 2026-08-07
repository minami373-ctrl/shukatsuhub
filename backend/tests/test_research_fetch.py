"""公開ページ取得（services/research.py）のテスト。

**実サイトを叩かない。**`httpx.Client` をモックに差し替える
（`services/ai.py` を `_get_client` のモックで試すのと同じ方針。docs/spec.md §3）。

ここで確かめるのは「取ってはいけないものを取らないこと」と
「失敗しても例外を投げないこと」の2点。
"""

from unittest.mock import MagicMock

import httpx

from services.research import (
    CANDIDATE_PATHS,
    MAX_BYTES,
    MAX_PAGES_PER_COMPANY,
    USER_AGENT,
    candidate_urls,
    fetch_page,
    fetch_pages,
    is_allowed_by_robots,
    normalize_url,
    same_site,
)

HTML = """
<html><head><title>アルファテック 採用情報</title>
<style>.a{color:red}</style></head>
<body><script>var x = 1;</script>
<h1>募集職種</h1><p>研究開発職を募集しています。</p></body></html>
"""


def _response(
    *,
    text: str = HTML,
    status_code: int = 200,
    content_type: str = "text/html; charset=utf-8",
    url: str = "https://example.com/recruit",
    content: bytes | None = None,
) -> MagicMock:
    res = MagicMock()
    res.text = text
    res.status_code = status_code
    res.headers = {"content-type": content_type}
    res.url = url
    res.content = content if content is not None else text.encode("utf-8")
    return res


def _client(pages: dict[str, MagicMock], robots: str | None = None) -> MagicMock:
    """URL → レスポンスの辞書で応答するクライアント。robots は本文（None なら 404）。"""
    client = MagicMock()

    def get(url: str, **kwargs):
        if url.endswith("/robots.txt"):
            if robots is None:
                return _response(text="", status_code=404, url=url)
            return _response(text=robots, content_type="text/plain", url=url)
        if url in pages:
            return pages[url]
        return _response(text="", status_code=404, url=url)

    client.get.side_effect = get
    return client


def test_candidate_urls_stay_inside_company_domain() -> None:
    """読むのは企業ドメイン配下の定番パスだけ。件数も上限で切る。"""
    urls = candidate_urls("sios.com")

    assert urls == [f"https://sios.com{path}" for path in CANDIDATE_PATHS]
    assert len(urls) <= MAX_PAGES_PER_COMPANY
    assert all(url.startswith("https://sios.com/") for url in urls)


def test_candidate_urls_rejects_broken_domain() -> None:
    """ホスト部以外（パス付き・空）が来たら何も返さない（spec.md §6 の domain はホスト部のみ）。"""
    assert candidate_urls("") == []
    assert candidate_urls("sios.com/recruit") == []


def test_normalize_url_rejects_other_schemes() -> None:
    assert normalize_url("https://example.com/a") == "https://example.com/a"
    # フラグメントは取得に関係しないので落とす
    assert normalize_url("https://example.com/a#top") == "https://example.com/a"
    # パスが無ければ / を補う
    assert normalize_url("https://example.com") == "https://example.com/"
    assert normalize_url("file:///etc/passwd") is None
    assert normalize_url("javascript:alert(1)") is None
    assert normalize_url("example.com/a") is None


def test_extracts_title_and_text_without_script_and_style() -> None:
    url = "https://example.com/recruit"
    result = fetch_page(url, _client({url: _response()}))

    assert result.status == "ok"
    assert result.title == "アルファテック 採用情報"
    assert "研究開発職を募集しています。" in (result.text or "")
    # script / style の中身は本文に入れない
    assert "var x" not in (result.text or "")
    assert "color:red" not in (result.text or "")


def test_sends_user_agent() -> None:
    url = "https://example.com/recruit"
    client = _client({url: _response()})
    fetch_page(url, client)

    # robots.txt と本体の両方に UA を付けて名乗る
    for call in client.get.call_args_list:
        assert call.kwargs["headers"]["User-Agent"] == USER_AGENT


def test_robots_disallow_blocks_fetch() -> None:
    """robots.txt が禁止していれば本体を取得しない（呼び出し回数で確認）。"""
    url = "https://example.com/recruit"
    client = _client({url: _response()}, robots="User-agent: *\nDisallow: /recruit\n")

    result = fetch_page(url, client)

    assert result.status == "robots_denied"
    assert result.text is None
    # 取得したのは robots.txt だけ
    assert [c.args[0] for c in client.get.call_args_list] == ["https://example.com/robots.txt"]


def test_robots_missing_is_treated_as_allowed() -> None:
    """robots.txt が 404 のときは許可として扱う（標準的な運用に合わせる）。"""
    url = "https://example.com/recruit"
    allowed, reason = is_allowed_by_robots(url, _client({}))
    assert allowed is True
    assert reason is None


def test_robots_fetch_failure_is_treated_as_allowed() -> None:
    """robots.txt の取得自体が失敗しても例外にしない。"""
    client = MagicMock()
    client.get.side_effect = httpx.ConnectError("boom")
    allowed, _ = is_allowed_by_robots("https://example.com/a", client)
    assert allowed is True


def test_rejects_non_html() -> None:
    url = "https://example.com/doc.pdf"
    result = fetch_page(url, _client({url: _response(content_type="application/pdf", url=url)}))
    assert result.status == "error"
    assert result.message == "HTML ではないため読み取れません"


def test_rejects_too_large_page() -> None:
    url = "https://example.com/big"
    big = _response(url=url, content=b"x" * (MAX_BYTES + 1))
    result = fetch_page(url, _client({url: big}))
    assert result.status == "error"
    assert result.message == "ページが大きすぎるため読み取りません"


def test_rejects_cross_host_redirect() -> None:
    """別サイトへ転送されたら捨てる（狙っていないサイトを取らないため）。"""
    url = "https://example.com/recruit"
    redirected = _response(url="https://other.example.net/recruit")
    result = fetch_page(url, _client({url: redirected}))
    assert result.status == "error"
    assert result.message == "別のサイトへ転送されたため取得を中止しました"


def test_allows_www_redirect() -> None:
    """`www.` の有無だけの違いは同じサイトとして通す（sios.com → www.sios.com の実測ケース）。"""
    url = "https://example.com/recruit"
    redirected = _response(url="https://www.example.com/recruit")
    result = fetch_page(url, _client({url: redirected}))
    assert result.status == "ok"
    assert "研究開発職を募集しています。" in (result.text or "")


def test_same_site_helper() -> None:
    assert same_site("sios.com", "www.sios.com") is True
    assert same_site("WWW.SIOS.COM", "sios.com") is True
    assert same_site("sios.com", "other.example.net") is False
    # サブドメインは別サイト扱い（www だけを例外にする）
    assert same_site("sios.com", "blog.sios.com") is False


def test_rejects_http_error_status() -> None:
    url = "https://example.com/gone"
    result = fetch_page(url, _client({url: _response(status_code=500, url=url)}))
    assert result.status == "error"
    assert "HTTP 500" in (result.message or "")


def test_connection_error_does_not_raise() -> None:
    client = MagicMock()

    def get(url: str, **kwargs):
        if url.endswith("/robots.txt"):
            return _response(text="", status_code=404, url=url)
        raise httpx.ReadTimeout("timeout")

    client.get.side_effect = get
    result = fetch_page("https://example.com/slow", client)
    assert result.status == "error"
    assert result.message == "ページを取得できませんでした"


def test_fetch_pages_continues_after_failure(monkeypatch) -> None:
    """1件失敗しても残りを取得する。取得の間隔は sleep で空ける。"""
    ok_url = "https://example.com/recruit"
    ng_url = "https://example.com/doc.pdf"
    client = _client({ok_url: _response(), ng_url: _response(content_type="application/pdf", url=ng_url)})

    monkeypatch.setattr("services.research.httpx.Client", lambda **kwargs: _as_context(client))

    results = fetch_pages([ng_url, ok_url], sleep_seconds=0)
    assert [r.status for r in results] == ["error", "ok"]


def _as_context(client: MagicMock) -> MagicMock:
    """with 文で使えるように __enter__ / __exit__ を持たせる。"""
    wrapper = MagicMock()
    wrapper.__enter__ = MagicMock(return_value=client)
    wrapper.__exit__ = MagicMock(return_value=False)
    return wrapper
