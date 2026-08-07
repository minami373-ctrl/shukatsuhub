"""SQLModel テーブル定義（docs/spec.md §6）。

仕様書 §6 に無いカラムを勝手に足さない。追加が必要なら先に仕様書を直す。
"""

from datetime import datetime

from sqlmodel import Field, SQLModel


class Company(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    domain: str = Field(unique=True, index=True)  # ホスト部のみ（@ を含めない）
    tags: str | None = None  # カンマ区切り。/companies のマッチ率で就活軸と照合する
    is_watched: bool = Field(default=False)
    # 選考段階。気になる / エントリー / 書類選考 / 面接 / 最終・内定（/pipeline のカンバンの列）
    stage: str = Field(default="気になる")
    # マッチング用（/companies）。空文字なら「その条件は合致しない」として扱う
    job_type: str | None = None  # 職種
    location: str | None = None  # 勤務地
    remote_ok: bool = Field(default=False)  # リモート勤務可否
    # 年収・休日は AI に生成させない。ここに保存した値だけを使う（spec.md §5.9）
    salary_min: int | None = None  # 想定年収の下限（万円）
    holidays_per_year: int | None = None  # 年間休日数（日）


class Email(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    # Gmail 実連携の upsert キー（`gmail:{message_id}`）。seed 由来のメールは None。
    # Event.external_id と同じ役割。**仕様書 §6 Email に無い追加なので人の承認待ち**
    external_id: str | None = Field(default=None, unique=True, index=True)
    account: str  # gmail / icloud
    from_address: str
    from_name: str | None = None
    subject: str
    body: str | None = None  # 分類には使わない（§5.1）
    received_at: datetime
    category: str  # 重要 / 確認 / 広告（§5.1 の導出値）
    needs_reply: bool = Field(default=False)
    decided_by: str = Field(default="rule")  # rule / ai
    company_id: int | None = Field(default=None, foreign_key="company.id")
    thread_key: str = Field(index=True)  # §5.2 の正規化結果


class Event(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    external_id: str = Field(unique=True, index=True)  # 同期の upsert キー（§5.4）
    title: str
    kind: str  # 選考 / 学業（表示色を決める）
    start_at: datetime
    end_at: datetime  # start_at より後
    location: str | None = None
    company_id: int | None = Field(default=None, foreign_key="company.id")


class Task(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    title: str
    short_label: str | None = None  # ヒーローの1文に使う短縮名
    due_at: datetime
    estimate_min: int = Field(default=30, ge=0)
    is_done: bool = Field(default=False)
    priority: str = Field(default="中")  # 高 / 中 / 低。重要度（度合い）
    badge: str | None = None  # 最優先 / 要返信 / 準備。表示タグ（行動の種類。重要度ではない）
    company_id: int | None = Field(default=None, foreign_key="company.id")


#: プロフィールの9項目。順序は spec.md §4.4 の表示順（3列 × 3行）に合わせる。
PROFILE_FIELDS: tuple[str, ...] = (
    "gakuchika",
    "strengths",
    "self_pr",
    "academics",
    "teamwork",
    "skills",
    "motivation_template",
    "career_plan",
    "job_axis",
)

#: 422 の detail とヒーローの1文で使う日本語の項目名。
PROFILE_FIELD_LABELS: dict[str, str] = {
    "gakuchika": "ガクチカ",
    "strengths": "強み",
    "self_pr": "自己PR",
    "academics": "学業",
    "motivation_template": "志望動機テンプレ",
    "job_axis": "就活軸",
    "skills": "資格・スキル",
    "career_plan": "キャリアプラン",
    "teamwork": "チームで活動した経験",
}

#: 1項目あたりの最大文字数（spec.md §5.5 / §6 Profile）。
PROFILE_MAX_LENGTH = 8000

#: Profile は単一レコード。id は常に 1（spec.md §6）。
PROFILE_ID = 1


class Profile(SQLModel, table=True):
    """プロフィール・自己分析（単一レコード・id = 1 固定）。

    completeness は保存しない導出値（下の completeness() で算出する）。
    """

    id: int | None = Field(default=PROFILE_ID, primary_key=True)
    gakuchika: str = ""
    strengths: str = ""
    self_pr: str = ""
    academics: str = ""
    motivation_template: str = ""
    job_axis: str = ""
    skills: str = ""
    career_plan: str = ""
    teamwork: str = ""


def filled_fields(profile: Profile) -> list[str]:
    """空でない項目のフィールド名を、PROFILE_FIELDS の順で返す。

    空白のみの入力は「未入力」として扱う（見た目が空なのに充実度が上がるのを避けるため）。
    """
    return [name for name in PROFILE_FIELDS if getattr(profile, name, "").strip()]


def completeness(profile: Profile) -> int:
    """充実度%（空でない項目数 ÷ 9 を四捨五入した整数）。spec.md §5.5 の導出値。"""
    ratio = len(filled_fields(profile)) / len(PROFILE_FIELDS) * 100
    return int(ratio + 0.5)


class QA(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="company.id")
    question: str
    answer_draft: str
    category: str  # 志望動機 / ガクチカ / 逆質問
    is_prepared: bool = Field(default=False)
    source: str  # ai / template
    generated_at: datetime


#: 企業研究の情報の由来。
#: web=公開ページを取得して AI が整理した／ai=ページが取れず企業名とプロフィールだけで
#: AI が「調べる観点」を組み立てた／template=AI も使えずテンプレに落ちた／seed=ダミーデータ。
RESEARCH_SOURCES: tuple[str, ...] = ("web", "ai", "template", "seed")

#: 公開ページ取得の結果。robots_denied は robots.txt が許可していない場合。
RESEARCH_FETCH_STATUSES: tuple[str, ...] = ("ok", "robots_denied", "error")


class ResearchReport(SQLModel, table=True):
    """企業1社ぶんの研究メモ（マークダウン1枚）。

    企業ごとに1件。収集を実行すると同じ企業の行を上書きする（増えていかない）。
    分類ごとの行に分けないのは、画面がマークダウン1枚を読む形だから。
    """

    id: int | None = Field(default=None, primary_key=True)
    company_id: int = Field(unique=True, index=True, foreign_key="company.id")
    #: 本文（マークダウン）。見出し・箇条書き・リンクを含む
    markdown: str
    #: 根拠にした公開ページの URL。改行区切り。取得できなかったときは空文字
    source_urls: str = ""
    source: str  # RESEARCH_SOURCES のいずれか
    collected_at: datetime


class ResearchCheck(SQLModel, table=True):
    """企業研究の確認観点1点（画面左下のチェックリスト）。

    企業単位で持つ。収集のたびに同じ企業の行を入れ替える。
    """

    id: int | None = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="company.id")
    label: str
    is_done: bool = Field(default=False)
    source: str = Field(default="seed")  # RESEARCH_SOURCES のいずれか


class OAuthToken(SQLModel, table=True):
    """外部サービスの OAuth トークン（spec.md §6 OAuthToken / §5.7）。

    `.env` ではなくここに置くのは、アクセストークンが失効して書き換わるため。
    **このテーブルの値を API レスポンス・ログ・エラーメッセージに出さない。**
    """

    id: int | None = Field(default=None, primary_key=True)
    # google（カレンダー）/ gmail。provider ごとに1行なので、片方だけ解除できる
    provider: str = Field(unique=True, index=True)
    access_token: str | None = None  # 失効するので必須にしない
    refresh_token: str | None = None  # 初回認可時のみ返る。空で上書きしない
    # 他の datetime 列は JST の naive だが、これだけは **naive UTC**。
    # google-auth が Credentials.expiry を naive UTC として扱うため、変換せず往復させる
    expires_at: datetime | None = None
    scope: str | None = None  # 実際に付与されたスコープ
    auth_state: str | None = None  # 認可中の CSRF state。照合したら None に戻す
    # 認可中の PKCE code_verifier。Flow を作り直すと失われるので保存する（§5.7.1）
    code_verifier: str | None = None
    updated_at: datetime


class Knowledge(SQLModel, table=True):
    """ナレッジ蓄積（spec.md §6 Knowledge）。FEATURE_PAGE_SPECS.md §11 準拠。"""

    id: int | None = Field(default=None, primary_key=True)
    title: str
    category: str  # 面接振り返り / 企業メモ / テンプレート / 学び
    company_id: int | None = Field(default=None, foreign_key="company.id")
    content: str
    updated_at: datetime
