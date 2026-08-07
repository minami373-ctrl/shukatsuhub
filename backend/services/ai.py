"""Azure OpenAI（Responses API）呼び出し＋フォールバックを集約するモジュール。
`openai` を import するのはここだけ。

2026-08-03: Anthropic から Azure OpenAI へ切り替えた（docs/decisions.md 参照）。
このプロジェクトのAzureエンドポイントは Chat Completions API ではなく
Responses API（`/openai/responses`）向けのため、`client.responses.parse()` を使う。
"""

import logging
import os
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()

logger = logging.getLogger(__name__)


def _get_client():
    api_key = os.getenv("AZURE_OPENAI_API_KEY")
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    api_version = os.getenv("OPENAI_API_VERSION")
    if not api_key or not endpoint or not api_version:
        return None
    from openai import AzureOpenAI

    return AzureOpenAI(api_key=api_key, azure_endpoint=endpoint, api_version=api_version)


def _get_deployment() -> str:
    return os.getenv("AZURE_OPENAI_DEPLOYMENT", "")


def _extract_refusal(res) -> str | None:
    """Responses API の出力からrefusalコンテンツがあれば取り出す（無ければNone）。"""
    for output in res.output:
        if getattr(output, "type", None) != "message":
            continue
        for content in output.content:
            if getattr(content, "type", None) == "refusal":
                return content.refusal
    return None


class EmailCategory(BaseModel):
    category: Literal["重要", "確認", "広告"]
    needs_reply: bool
    reason: str


def classify_email_ai(from_address: str, subject: str) -> tuple[str, bool, str]:
    """ルールで保留になったメールをAIで分類する。

    戻り値は (category, needs_reply, decided_by)。フォールバック時は
    実際にはAIが判定していないため decided_by="rule" を返す。
    """
    client = _get_client()
    if client is None:
        logger.info("Azure OpenAIの認証情報未設定のためメール分類をフォールバックにします")
        return "確認", False, "rule"

    for attempt in range(2):
        try:
            res = client.responses.parse(
                model=_get_deployment(),
                instructions=(
                    "あなたは就活生のメールを3カテゴリに分類する。"
                    "重要=面接や選考結果など今日中に見る必要があるもの。"
                    "確認=ESや説明会など期限があるが即応でないもの。"
                    "広告=スカウトやメルマガなど読まなくても支障がないもの。"
                ),
                input=f"送信元: {from_address}\n件名: {subject}",
                text_format=EmailCategory,
            )
        except Exception:
            logger.exception("メール分類のAPI呼び出しに失敗しました（試行%d回目）", attempt + 1)
            continue

        if _extract_refusal(res) or res.status in ("failed", "incomplete"):
            logger.warning("メール分類がrefusalのためフォールバックにします")
            return "確認", False, "rule"

        result = res.output_parsed
        if result is None or result.category not in ("重要", "確認", "広告"):
            logger.warning("メール分類の出力が想定外のためフォールバックにします")
            return "確認", False, "rule"

        return result.category, result.needs_reply, "ai"

    logger.warning("メール分類のAPI呼び出しが2回とも失敗したためフォールバックにします")
    return "確認", False, "rule"


class QAItem(BaseModel):
    question: str
    answer_draft: str
    category: Literal["志望動機", "ガクチカ", "逆質問"]


class QASheet(BaseModel):
    items: list[QAItem]


def generate_qa(
    profile_fields: dict[str, str],
    company_name: str,
    company_tags: str,
    template_items: list[dict[str, str]],
) -> tuple[list[dict[str, str]], str]:
    """プロフィールと企業情報から想定問答を生成する（docs/spec.md §5.6）。

    戻り値は (items, source)。items は {question, answer_draft, category} の辞書のリスト。
    source は "ai"（生成成功時）または "template"（フォールバック時）。

    DB への保存（既存レコードの削除→入れ替え）はこの関数の責務ではなく、
    呼び出し側（routers/qa.py）が行う。
    """
    client = _get_client()
    if client is None:
        logger.info("Azure OpenAIの認証情報未設定のため想定問答生成をテンプレにフォールバックします")
        return template_items, "template"

    profile_text = "\n".join(f"{key}: {value}" for key, value in profile_fields.items() if value)
    prompt = f"企業名: {company_name}\n企業タグ: {company_tags}\nプロフィール:\n{profile_text}"

    for attempt in range(2):
        try:
            res = client.responses.parse(
                model=_get_deployment(),
                instructions=(
                    "あなたは就活生の面接対策を手伝う。渡されたプロフィールと企業情報から、"
                    "その企業の面接で実際に聞かれそうな想定質問と、回答の骨子を作る。"
                    "回答骨子はプロフィールに書かれた事実だけを使い、経歴を創作しない。"
                    "質問は6〜8問、各カテゴリを少なくとも1問含める。"
                ),
                input=prompt,
                text_format=QASheet,
            )
        except Exception:
            logger.exception("想定問答生成のAPI呼び出しに失敗しました（試行%d回目）", attempt + 1)
            continue

        if _extract_refusal(res) or res.status in ("failed", "incomplete"):
            logger.warning("想定問答生成がrefusalのためテンプレにフォールバックします")
            return template_items, "template"

        sheet = res.output_parsed
        if sheet is None:
            logger.warning("想定問答生成の出力が空のためテンプレにフォールバックします")
            return template_items, "template"

        return [item.model_dump() for item in sheet.items], "ai"

    logger.warning("想定問答生成のAPI呼び出しが2回とも失敗したためテンプレにフォールバックします")
    return template_items, "template"


class ResearchReportSheet(BaseModel):
    #: 本文（マークダウン）。画面はこれをそのまま描画する
    markdown: str
    #: 研究の確認観点（例「事業の柱を3つ言えるか」）。3点
    checks: list[str]


#: マークダウンの書き方の指定。画面側の描画に合わせて使う記法を絞る。
_MARKDOWN_RULES = (
    "本文は日本語のマークダウンで書く。使えるのは "
    "`## 見出し`・`### 小見出し`・`- 箇条書き`・`**強調**`・`[表示文字](URL)` だけ。"
    "表・画像・コードブロックは使わない。見出しは `## 事業・製品`／`## 求める人材`／"
    "`## 働き方・制度`／`## 最近の動き` の4つを必ず立て、各見出しの下に箇条書きを2〜4行置く。"
)

#: 企業研究の整理に使うシステムプロンプト。渡したページに書かれていないことを書かせない。
_RESEARCH_INSTRUCTIONS = (
    "あなたは就活生の企業研究を手伝う。渡された公開ページの本文と就活生のプロフィールから、"
    "選考で使える企業情報を1枚のメモに整理する。"
    "**渡されたページ本文に書かれている事実だけを使い、推測や創作をしない。**"
    "本文に無いことは書かず、書けない見出しには「公開ページからは分かりませんでした」と書く。"
    "各箇条書きの末尾に、根拠にしたページを `[出典](URL)` の形で必ず付ける（URL は渡されたもののみ）。"
    + _MARKDOWN_RULES
    + "checks は面接前に自分で確認すべき観点を3点、就活生のプロフィール（強み・就活軸）との"
    "重なりが分かる形で書く。"
)

#: 公開ページが1件も取れなかったときの指示。事実を作らせないため書き方を変える。
_RESEARCH_NO_PAGE_INSTRUCTIONS = (
    "あなたは就活生の企業研究を手伝う。**公開ページの本文は渡されていない。**"
    "そのため企業の実際の事業内容・制度・ニュースを断定して書いてはならない。"
    "代わりに「何を調べるべきか」「どこを見れば分かるか」という観点を、"
    "就活生のプロフィールと企業名・タグから組み立てる。"
    "箇条書きはすべて調べるべき観点として書き、出典リンクは付けない。"
    + _MARKDOWN_RULES
    + "checks は面接前に確認すべき観点を3点書く。"
)


def organize_research(
    company_name: str,
    company_tags: str,
    profile_fields: dict[str, str],
    pages: list[dict[str, str]],
    template_markdown: str,
    template_checks: list[str],
) -> tuple[str, list[str], str]:
    """公開ページの本文とプロフィールから企業研究のメモ（マークダウン）を作る。

    引数 pages は [{"url": ..., "title": ..., "text": ...}] のリスト。空リストなら
    「ページ本文なし」として、調べるべき観点だけを組み立てさせる（事実を創作させない）。

    戻り値は (markdown, checks, source)。
    source は "web"（ページ本文あり）／"ai"（ページ本文なし）／"template"（フォールバック）。
    DB への保存は呼び出し側（routers/research.py）が行う。
    """
    fallback = (template_markdown, template_checks, "template")

    client = _get_client()
    if client is None:
        logger.info("Azure OpenAIの認証情報未設定のため企業研究の整理をテンプレにフォールバックします")
        return fallback

    profile_text = "\n".join(f"{key}: {value}" for key, value in profile_fields.items() if value)
    page_text = "\n\n".join(
        f"URL: {page['url']}\nタイトル: {page.get('title') or '（無題）'}\n本文: {page['text']}"
        for page in pages
    )
    prompt = (
        f"企業名: {company_name}\n企業タグ: {company_tags}\n"
        f"プロフィール:\n{profile_text}\n\n"
        f"公開ページ:\n{page_text if pages else '（取得できたページはありません）'}"
    )
    source = "web" if pages else "ai"

    for attempt in range(2):
        try:
            res = client.responses.parse(
                model=_get_deployment(),
                instructions=_RESEARCH_INSTRUCTIONS if pages else _RESEARCH_NO_PAGE_INSTRUCTIONS,
                input=prompt,
                text_format=ResearchReportSheet,
            )
        except Exception:
            logger.exception("企業研究の整理のAPI呼び出しに失敗しました（試行%d回目）", attempt + 1)
            continue

        if _extract_refusal(res) or res.status in ("failed", "incomplete"):
            logger.warning("企業研究の整理がrefusalのためテンプレにフォールバックします")
            return fallback

        sheet = res.output_parsed
        if sheet is None or not sheet.markdown.strip():
            logger.warning("企業研究の整理の出力が空のためテンプレにフォールバックします")
            return fallback

        return sheet.markdown, list(sheet.checks), source

    logger.warning("企業研究の整理のAPI呼び出しが2回とも失敗したためテンプレにフォールバックします")
    return fallback
