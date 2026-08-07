"""企業一覧の取得元（docs/spec.md §5.10）。

**実データへ移行するときは、このファイルの `fetch_companies` の中身だけを差し替える。**
マッチ率の算出（`services/matching.py`）・API（`routers/companies.py`）・画面は変更しなくてよい。

今回は `Company` テーブル（seed 由来）をそのまま返す。Gmail / iCloud と同じ
「モック＋差し替え口」の方針（§2）。カレンダーが「認可済みなら Google・未認可なら seed」に
分岐しているのと同じ作法（§5.7）で、後から分岐を足せる形にしてある。

移行時の懸念（利用規約・ハルシネーション・取得項目の難易度）は
Notion「企業マッチング：実データ取得への移行検討」に整理した。
"""

from collections import Counter
from dataclasses import dataclass
from datetime import datetime

from sqlmodel import Session, select

from models import Company, Email
from services.grouping import domain_of

#: 取得元の名前。画面に出して「どこから来たデータか」を示す（実データ移行後は 'api' などになる）
SOURCE_SEED = "seed"

#: 企業として提案するメールの分類（§5.11）。`広告` は入れない。
#: エージェント・メルマガ配信元を企業にすると選考ボードが埋まって使えなくなるため
SUGGEST_CATEGORIES = ("重要", "確認")


def fetch_companies(session: Session) -> tuple[list[Company], str]:
    """企業一覧と、その取得元を返す。

    戻り値の2つ目を返すのは、実データに切り替えたときに画面で出典を出せるようにするため。
    取得に失敗したら seed に落とす、という分岐もここに足す（`services/gcal.py` の前例と同じ）。
    """
    companies = list(session.exec(select(Company).order_by(Company.name, Company.id)))
    return companies, SOURCE_SEED


@dataclass(frozen=True)
class CompanySuggestion:
    """受信箱から見つけた「まだ登録していない企業」の候補（§5.11）。"""

    domain: str
    #: 送信者表示名の最頻値。無ければドメインそのまま。**ドメインから企業名を推測しない**
    suggested_name: str
    email_count: int
    latest_received_at: datetime
    #: そのドメインから届いた分類（重要 / 確認）。強い順
    categories: list[str]


def suggest_from_emails(emails: list[Email], companies: list[Company]) -> list[CompanySuggestion]:
    """未登録ドメインからの受信メールを、企業の登録候補にまとめる（§5.11）。

    **AI もスクレイピングも使わない。**既に受信しているメールだけを材料にする。
    分類（重要 / 確認 / 広告）は既存のメール分類（§5.1）の結果をそのまま使い、
    ここで判定をやり直さない。候補が0件なら空リスト（エラーにしない）。
    """
    known = {c.domain for c in companies if c.domain}

    by_domain: dict[str, list[Email]] = {}
    for email in emails:
        # company_id が付いているものは登録済み。ドメイン側でも二重に弾く
        # （メールを先に読み込んで後から企業を作った場合に company_id が空のまま残るため）
        if email.company_id is not None or email.category not in SUGGEST_CATEGORIES:
            continue
        domain = domain_of(email.from_address).strip().lower()
        if not domain or domain in known:
            continue
        by_domain.setdefault(domain, []).append(email)

    suggestions = [
        CompanySuggestion(
            domain=domain,
            suggested_name=_suggested_name(domain, group),
            email_count=len(group),
            latest_received_at=max(e.received_at for e in group),
            categories=[c for c in SUGGEST_CATEGORIES if any(e.category == c for e in group)],
        )
        for domain, group in by_domain.items()
    ]
    # 受信の新しい順。同時刻はドメイン順にして並びが毎回変わらないようにする
    suggestions.sort(key=lambda s: (-s.latest_received_at.timestamp(), s.domain))
    return suggestions


def _suggested_name(domain: str, emails: list[Email]) -> str:
    """企業名の候補＝送信者表示名の最頻値。同数なら名前順（並びが毎回変わらないように）。

    表示名が1つも無ければドメインをそのまま候補にする。
    採用担当の署名などが混ざるので、あくまで**候補**として画面に出し、人が直せる形にする。
    """
    names = Counter(e.from_name.strip() for e in emails if e.from_name and e.from_name.strip())
    if not names:
        return domain
    return min(names.items(), key=lambda item: (-item[1], item[0]))[0]
