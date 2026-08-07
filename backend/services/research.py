"""企業研究の公開ページ取得を集約するモジュール。

**外部への HTTP 取得を行うのはここだけ**（`services/ai.py` が `openai` を、
`services/gcal.py` が `google-*` を import する唯一の場所であるのと同じ方針）。

守る約束（実装をここに閉じる理由）:

- 取得するのは **企業の登録ドメイン（`Company.domain`）配下の定番ページだけ**。
  検索エンジンで探したり、他のサイトへ回ったりしない
- `robots.txt` を読み、許可されていないパスは**取得しない**（`robots_denied` を返す）
- リダイレクトは同一サイトのみ。別ホストへ飛ぶものは追わない（狙っていないサイトを取らないため）。
  `www.` の有無だけの違いは同じサイトとして許可する（`sios.com` → `www.sios.com` のような正規化）
- `text/html` 以外と、本文が MAX_BYTES を超えるものは捨てる
- 1 URL ずつ順に取得し、間に SLEEP_SECONDS 空ける（相手サイトへの配慮）
- **例外を投げない。**失敗は理由付きで返し、呼び出し側がフォールバックに落とす（AI・Google と同じ）

新しい pip 依存は増やさない（`httpx` は既に依存にあり、`urllib.robotparser` と
`html.parser` は標準ライブラリ）。
"""

import logging
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urlparse, urlunparse
from urllib.robotparser import RobotFileParser

import httpx

logger = logging.getLogger(__name__)

#: 相手サイトに名乗る UA。誰が取得しているかを分かるようにする。
USER_AGENT = "ShukatsuHub-Research/0.1"

#: 1ページあたりの取得上限（バイト）。大きなページで固まらないようにする。
MAX_BYTES = 1_000_000

#: AI に渡すテキストの上限（文字）。これ以上は切る。
MAX_TEXT_CHARS = 8_000

#: 取得のタイムアウト（秒）。
TIMEOUT_SECONDS = 10.0

#: 連続取得の間隔（秒）。
SLEEP_SECONDS = 1.0

#: 受け付けるスキーム。
ALLOWED_SCHEMES = ("http", "https")

#: 企業ドメインの下で順に試す定番パス。存在したものだけを読む。
#: 会社案内・採用・ニュースは、企業研究で最初に見る3種類なので固定でよい。
CANDIDATE_PATHS = ("/", "/company/", "/recruit/", "/news/")

#: 1社あたり読むページ数の上限。相手サイトに負荷をかけないため。
MAX_PAGES_PER_COMPANY = 4


@dataclass(frozen=True)
class FetchResult:
    """1 URL の取得結果。status は models.RESEARCH_FETCH_STATUSES のいずれか。"""

    url: str
    status: str  # ok / robots_denied / error
    title: str | None = None
    text: str | None = None
    message: str | None = None  # 失敗の理由（画面に出す短い文）

    @property
    def ok(self) -> bool:
        return self.status == "ok"


class _TextExtractor(HTMLParser):
    """HTML から本文テキストと <title> を取り出す最小の抽出器。

    整形の精度より「依存を増やさないこと」を優先する。AI に渡すのは要約の材料なので、
    タグを落として文字を連結すれば足りる。
    """

    #: 中身を本文として扱わない要素。
    SKIP_TAGS = frozenset({"script", "style", "noscript", "template", "svg"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title: str | None = None
        self._parts: list[str] = []
        self._skip_depth = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: ANN001 (HTMLParser の型に合わせる)
        if tag in self.SKIP_TAGS:
            self._skip_depth += 1
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title and self.title is None:
            stripped = data.strip()
            if stripped:
                self.title = stripped
            return
        if self._skip_depth > 0:
            return
        stripped = data.strip()
        if stripped:
            self._parts.append(stripped)

    @property
    def text(self) -> str:
        return " ".join(self._parts)[:MAX_TEXT_CHARS]


def normalize_url(url: str) -> str | None:
    """登録できる形の URL なら正規化して返す。そうでなければ None。

    フラグメント（#以下）は取得に関係しないので落とす。
    """
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return None
    if parsed.scheme not in ALLOWED_SCHEMES or not parsed.netloc:
        return None
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path or "/", parsed.params, parsed.query, ""))


def same_site(a: str, b: str) -> bool:
    """2つのホストが同じサイトか。`www.` の有無だけの違いは同じ扱いにする。

    企業サイトは `sios.com` → `www.sios.com` のような正規化リダイレクトを持つことが多く、
    これを別サイトとして弾くと本文が1件も読めなくなる（実測で確認）。
    """

    def base(host: str) -> str:
        lowered = host.lower()
        return lowered[4:] if lowered.startswith("www.") else lowered

    return base(a) == base(b)


def _robots_url(url: str) -> str:
    parsed = urlparse(url)
    return urlunparse((parsed.scheme, parsed.netloc, "/robots.txt", "", "", ""))


def is_allowed_by_robots(url: str, client: httpx.Client) -> tuple[bool, str | None]:
    """robots.txt が取得を許可しているか。

    robots.txt が取得できない（404・通信失敗）ときは「許可」として扱う。これは
    robotparser と同じ扱いで、標準的な運用（robots.txt が無いサイトは制限なし）に合わせる。
    取得できて明示的に禁止されている場合だけ False を返す。
    """
    parser = RobotFileParser()
    try:
        res = client.get(_robots_url(url), headers={"User-Agent": USER_AGENT})
    except httpx.HTTPError as e:
        logger.info("robots.txt を取得できないため許可として扱います: %s (%s)", _robots_url(url), type(e).__name__)
        return True, None

    if res.status_code >= 400:
        return True, None

    parser.parse(res.text.splitlines())
    if parser.can_fetch(USER_AGENT, url):
        return True, None
    return False, "robots.txt がこのページの取得を許可していません"


def fetch_page(url: str, client: httpx.Client) -> FetchResult:
    """1ページを取得してテキストにする。例外は投げず FetchResult で返す。"""
    normalized = normalize_url(url)
    if normalized is None:
        return FetchResult(url=url, status="error", message="URL の形式が正しくありません")

    allowed, reason = is_allowed_by_robots(normalized, client)
    if not allowed:
        return FetchResult(url=normalized, status="robots_denied", message=reason)

    host = urlparse(normalized).netloc
    try:
        res = client.get(normalized, headers={"User-Agent": USER_AGENT})
    except httpx.HTTPError as e:
        logger.info("ページを取得できませんでした: %s (%s)", normalized, type(e).__name__)
        return FetchResult(url=normalized, status="error", message="ページを取得できませんでした")

    # リダイレクト先が別サイトなら捨てる（狙っていないサイトを取らないため）
    if not same_site(urlparse(str(res.url)).netloc, host):
        return FetchResult(url=normalized, status="error", message="別のサイトへ転送されたため取得を中止しました")

    if res.status_code >= 400:
        return FetchResult(url=normalized, status="error", message=f"取得に失敗しました（HTTP {res.status_code}）")

    content_type = res.headers.get("content-type", "")
    if "text/html" not in content_type.lower():
        return FetchResult(url=normalized, status="error", message="HTML ではないため読み取れません")

    body = res.content
    if len(body) > MAX_BYTES:
        return FetchResult(url=normalized, status="error", message="ページが大きすぎるため読み取りません")

    extractor = _TextExtractor()
    extractor.feed(res.text)
    text = extractor.text
    if not text:
        return FetchResult(url=normalized, status="error", message="本文を読み取れませんでした")

    return FetchResult(url=normalized, status="ok", title=extractor.title, text=text)


def candidate_urls(domain: str) -> list[str]:
    """企業ドメインの下で試す URL を組む（`Company.domain` はホスト部のみ。spec.md §6）。

    人が URL を登録しなくても読めるようにするための決め打ち。ここに無いパスは見に行かない。
    """
    host = domain.strip().strip("/")
    if not host or "/" in host:
        return []
    return [f"https://{host}{path}" for path in CANDIDATE_PATHS][:MAX_PAGES_PER_COMPANY]


def fetch_company_pages(domain: str, sleep_seconds: float = SLEEP_SECONDS) -> list[FetchResult]:
    """企業ドメインの定番ページを順に取得する。存在しないパスは失敗として捨てる。"""
    return fetch_pages(candidate_urls(domain), sleep_seconds=sleep_seconds)


def fetch_pages(urls: list[str], sleep_seconds: float = SLEEP_SECONDS) -> list[FetchResult]:
    """登録された URL を順に取得する。1件失敗しても他は続ける。

    `follow_redirects=True` にしているのは、同一ホスト内の正規化リダイレクト
    （http→https・末尾スラッシュ）を通すため。別ホストへの転送は fetch_page で弾く。
    """
    results: list[FetchResult] = []
    with httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=True) as client:
        for i, url in enumerate(urls):
            if i > 0 and sleep_seconds > 0:
                time.sleep(sleep_seconds)  # 相手サイトへの配慮。連続で叩かない
            results.append(fetch_page(url, client))
    return results
