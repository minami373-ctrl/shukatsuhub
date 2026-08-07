"""seed JSON を SQLite に投入する（docs/spec.md §3「起動・確認」）。

実行: cd backend && python -m seed.load

**DB 全体を作り直さない。**各投入関数が「自分が扱うテーブルだけ」を入れ替える。
全消しにすると、他の担当者が画面から保存したデータ（プロフィール等）まで消えてしまう。

データを足す担当者は LOADERS に「ファイル名 → 投入関数」を1行追加する。
"""

import json
from datetime import datetime
from pathlib import Path

from sqlmodel import Session, delete, select

import models  # noqa: F401  metadata にテーブルを登録するため必要
from db import engine, init_db
from models import (
    QA,
    PROFILE_FIELDS,
    PROFILE_ID,
    Company,
    Email,
    Knowledge,
    Profile,
    ResearchCheck,
    ResearchReport,
    Task,
)
from routers.events import sync_events_from_seed
from services import grouping
from services.classifier import classify_email

SEED_DIR = Path(__file__).resolve().parent


def _load_calendar(session: Session, path: Path) -> str:
    """external_id をキーに upsert するので、何度実行しても件数が増えない（§5.4）。"""
    result = sync_events_from_seed(session, path)
    return f"予定 追加 {result['added']} 件・更新 {result['updated']} 件"


def _load_companies(session: Session, path: Path) -> str:
    """企業とメールは seed が唯一の入力元。この2テーブルだけ入れ替える。

    Email と QA が Company を参照するので、参照する側 → Company の順に消す。
    QA も消すのは、企業を採番し直すと company_id が宙に浮いた行が残り、
    どの画面からも見えないまま DB に溜まってしまうため（想定問答は再生成できる）。
    企業研究（ResearchReport / ResearchCheck）も Company を参照するので同じ理由で消す。
    どちらも直後の research.json で入れ直される。
    """
    session.exec(delete(Email))
    session.exec(delete(QA))
    session.exec(delete(ResearchReport))
    session.exec(delete(ResearchCheck))
    session.exec(delete(Company))
    session.commit()

    # stage は 2026-08-04 に追加した項目。古い companies.json でも落ちないよう既定値に任せる
    data = json.loads(path.read_text(encoding="utf-8"))
    companies = [Company(**item) for item in data]
    session.add_all(companies)
    session.commit()
    return f"企業 {len(companies)} 件"


def _load_emails(session: Session, path: Path) -> str:
    companies = session.exec(select(Company)).all()
    data = json.loads(path.read_text(encoding="utf-8"))

    emails = []
    for item in data:
        category, needs_reply, decided_by = classify_email(item["from_address"], item["subject"])
        emails.append(
            Email(
                account=item["account"],
                from_address=item["from_address"],
                from_name=item["from_name"],
                subject=item["subject"],
                body=item["body"],
                received_at=datetime.fromisoformat(item["received_at"]),
                category=category,
                needs_reply=needs_reply,
                decided_by=decided_by,
                company_id=grouping.resolve_company_id(item["from_address"], companies),
                thread_key=grouping.build_thread_key(item["from_address"], item["subject"], companies),
            )
        )
    session.add_all(emails)
    session.commit()
    return f"メール {len(emails)} 件"


def _load_profile(session: Session, path: Path) -> str:
    """profile.json でプロフィール（単一レコード）を上書きする。"""
    data = json.loads(path.read_text(encoding="utf-8"))
    unknown = set(data) - set(PROFILE_FIELDS)
    if unknown:
        raise ValueError(f"profile.json に未知の項目があります: {sorted(unknown)}")

    profile = session.get(Profile, PROFILE_ID) or Profile(id=PROFILE_ID)
    for name in PROFILE_FIELDS:
        setattr(profile, name, data.get(name, ""))
    session.add(profile)
    session.commit()
    return f"{len(PROFILE_FIELDS)} 項目"


def _load_tasks(session: Session, path: Path) -> str:
    """今日やること（Task）を入れ替える。Task テーブル以外は触らない。

    company_domain で企業を逆引きするのは、seed に採番済みの id を書くと
    companies.json の並びを変えたときに黙ってずれるため。
    """
    domain_to_id = {c.domain: c.id for c in session.exec(select(Company))}

    data = json.loads(path.read_text(encoding="utf-8"))
    tasks = []
    for item in data:
        domain = item.get("company_domain")
        if domain and domain not in domain_to_id:
            raise ValueError(f"tasks.json の company_domain が companies.json にありません: {domain}")
        tasks.append(
            Task(
                title=item["title"],
                short_label=item.get("short_label"),
                due_at=datetime.fromisoformat(item["due_at"]),
                estimate_min=item.get("estimate_min", 30),
                is_done=item.get("is_done", False),
                badge=item.get("badge"),
                company_id=domain_to_id.get(domain) if domain else None,
            )
        )

    session.exec(delete(Task))
    session.add_all(tasks)
    session.commit()
    return f"タスク {len(tasks)} 件"


def _load_knowledge(session: Session, path: Path) -> str:
    """ナレッジ蓄積（Knowledge）を入れ替える。Knowledge テーブル以外は触らない。

    company_domain で企業を逆引きするのは _load_tasks と同じ理由
    （companies.json の並びが変わっても company_id がずれないようにするため）。
    """
    domain_to_id = {c.domain: c.id for c in session.exec(select(Company))}

    data = json.loads(path.read_text(encoding="utf-8"))
    notes = []
    for item in data:
        domain = item.get("company_domain")
        if domain and domain not in domain_to_id:
            raise ValueError(f"knowledge.json の company_domain が companies.json にありません: {domain}")
        notes.append(
            Knowledge(
                title=item["title"],
                category=item["category"],
                company_id=domain_to_id.get(domain) if domain else None,
                content=item["content"],
                updated_at=datetime.fromisoformat(item["updated_at"]),
            )
        )

    session.exec(delete(Knowledge))
    session.add_all(notes)
    session.commit()
    return f"メモ {len(notes)} 件"


def _load_research(session: Session, path: Path) -> str:
    """企業研究のメモ（マークダウン）と確認観点を入れ替える。

    触るのは ResearchReport / ResearchCheck の2テーブルだけ。
    tasks.json と同じく company_domain で企業を逆引きする（採番済みの id を seed に書かない）。
    `template` ブロックは収集のフォールバック用なので、ここでは投入しない
    （読むのは routers/research.py）。
    """
    domain_to_id = {c.domain: c.id for c in session.exec(select(Company))}

    def company_id_of(item: dict, where: str) -> int:
        domain = item.get("company_domain")
        if not domain:
            raise ValueError(f"research.json（{where}）の company_domain は省略できません")
        if domain not in domain_to_id:
            raise ValueError(f"research.json（{where}）の company_domain が companies.json にありません: {domain}")
        return domain_to_id[domain]

    data = json.loads(path.read_text(encoding="utf-8"))

    # seed のデータは source="seed"。収集を実行するとその企業の分だけ上書きされる
    reports = [
        ResearchReport(
            company_id=company_id_of(item, "reports"),
            markdown=item["markdown"],
            source_urls="\n".join(item.get("source_urls", [])),
            source="seed",
            collected_at=datetime.fromisoformat(item["collected_at"]),
        )
        for item in data["reports"]
    ]
    checks = [
        ResearchCheck(
            company_id=company_id_of(item, "checks"),
            label=item["label"],
            is_done=item.get("is_done", False),
            source="seed",
        )
        for item in data["checks"]
    ]

    session.exec(delete(ResearchReport))
    session.exec(delete(ResearchCheck))
    session.add_all(reports)
    session.add_all(checks)
    session.commit()
    return f"企業研究メモ {len(reports)} 件・確認観点 {len(checks)} 件"


# ファイル名 → 投入関数。担当機能の seed が増えたらここに追加する。
# companies.json は emails.json / tasks.json より前に置くこと（企業の逆引きに使うため）。
LOADERS = {
    "calendar.json": _load_calendar,
    "companies.json": _load_companies,
    "emails.json": _load_emails,
    "tasks.json": _load_tasks,
    "profile.json": _load_profile,
    "knowledge.json": _load_knowledge,
    "research.json": _load_research,
}


def main() -> None:
    print("seed を投入します:", engine.url)
    init_db()  # テーブルが無ければ作る（既存データは消さない）

    with Session(engine) as session:
        for filename, loader in LOADERS.items():
            path = SEED_DIR / filename
            if not path.exists():
                print(f"  - {filename}: 見つからないのでスキップ")
                continue
            print(f"  - {filename}: {loader(session, path)}")

    print("完了")


if __name__ == "__main__":
    main()
