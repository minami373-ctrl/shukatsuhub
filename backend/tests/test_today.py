"""今日画面 API（docs/spec.md §4.1 / API 一覧）。

conftest.py の session / client フィクスチャ（インメモリ DB）を使う。
"""

from datetime import datetime

from fastapi.testclient import TestClient
from sqlmodel import Session

from models import Company, Email, Event, Task

DAY = "2026-07-30"


def seed_day(session: Session) -> None:
    """基準日 2026-07-30 の予定・タスク・メールを入れる（seed/*.json と同じ構成）。"""
    company = Company(name="アルファテック", domain="alphatech.co.jp", is_watched=True)
    session.add(company)
    session.commit()
    session.refresh(company)

    session.add_all(
        [
            Event(
                external_id="seminar",
                title="研究室ゼミ",
                kind="学業",
                start_at=datetime(2026, 7, 30, 10, 30),
                end_at=datetime(2026, 7, 30, 12, 0),
                location="B棟 402",
            ),
            Event(
                external_id="interview",
                title="アルファテック 一次面接",
                kind="選考",
                start_at=datetime(2026, 7, 30, 15, 0),
                end_at=datetime(2026, 7, 30, 16, 0),
                location="オンライン・Zoom",
                company_id=company.id,
            ),
            Event(
                external_id="briefing",
                title="ベータ社 説明会",
                kind="選考",
                start_at=datetime(2026, 7, 31, 10, 0),
                end_at=datetime(2026, 7, 31, 11, 30),
            ),
            Task(
                title="デルタ商事 面接日程を回答",
                short_label="日程回答",
                due_at=datetime(2026, 7, 30, 12, 0),
                estimate_min=15,
            ),
            Task(
                title="アルファテック ES 提出",
                short_label="ES提出",
                due_at=datetime(2026, 7, 30, 23, 59),
                estimate_min=240,
                badge="最優先",
                company_id=company.id,
            ),
            Task(
                title="スカウト3件を仕分け",
                due_at=datetime(2026, 7, 30, 9, 12),
                estimate_min=15,
                is_done=True,
            ),
            Email(
                account="gmail",
                from_address="recruit@alphatech.co.jp",
                from_name="アルファテック 採用",
                subject="一次面接 日程調整のご連絡",
                received_at=datetime(2026, 7, 30, 14, 20),
                category="重要",
                needs_reply=True,
                decided_by="rule",
                company_id=company.id,
                thread_key="1|一次面接 日程調整のご連絡",
            ),
        ]
    )
    session.commit()


class TestGetToday:
    def test_指標とタイムラインの素材が揃う(self, session: Session, client: TestClient):
        seed_day(session)

        body = client.get(f"/api/today?date={DAY}").json()

        assert body["date"] == DAY
        # 研究枠 10:00〜17:00（7h）− ゼミ1.5h − 面接1h = 4.5h
        assert body["research_hours"] == 4.5
        # 空き時間 = 7h（研究枠の外）− 未完了タスク（15分 + 240分 = 4.25h）→ 2.75h → 3.0h
        assert body["free_hours"] == 3.0
        assert body["open_task_count"] == 2
        assert body["event_count"] == 2  # 翌日の説明会は含めない
        assert body["needs_reply_count"] == 1
        # 締切が最も近い未完了タスク（§4.1 の1文に使う）
        assert body["nearest_task_label"] == "日程回答"
        # 翌日の先頭イベントを1件だけ返す（§4.1 タイムライン末尾）
        assert body["tomorrow_event"]["title"] == "ベータ社 説明会"

    def test_空きスロットは研究枠の外だけに出る(self, session: Session, client: TestClient):
        seed_day(session)

        slots = client.get(f"/api/today?date={DAY}").json()["free_slots"]

        # 08:00-10:00 / 17:00-22:00。10:00〜17:00 は研究にあてるので出さない
        assert [(s["start"][11:16], s["end"][11:16]) for s in slots] == [
            ("08:00", "10:00"),
            ("17:00", "22:00"),
        ]
        assert [s["suggested_task_label"] for s in slots] == ["日程回答", "ES提出"]

    def test_研究にあてられる区間を返す(self, session: Session, client: TestClient):
        seed_day(session)

        slots = client.get(f"/api/today?date={DAY}").json()["research_slots"]

        assert [(s["start"][11:16], s["end"][11:16]) for s in slots] == [
            ("10:00", "10:30"),
            ("12:00", "15:00"),
            ("16:00", "17:00"),
        ]

    def test_完了済みタスクも締切順のまま並ぶ(self, session: Session, client: TestClient):
        """チェックを付けた行を末尾に動かさない（打ち消し線で完了を表す）。"""
        seed_day(session)

        tasks = client.get(f"/api/today?date={DAY}").json()["tasks"]

        # 09:12（完了）→ 12:00 → 23:59 の締切順
        assert [t["due_at"][11:16] for t in tasks] == ["09:12", "12:00", "23:59"]
        assert [t["is_done"] for t in tasks] == [True, False, False]

    def test_締切を過ぎた未完了は_is_overdue(self, session: Session, client: TestClient):
        """基準時刻 12:20 を過ぎた未完了だけ true。完了済みは対象外。"""
        seed_day(session)

        tasks = client.get(f"/api/today?date={DAY}").json()["tasks"]
        overdue = {t["due_at"][11:16]: t["is_overdue"] for t in tasks}

        assert overdue == {"09:12": False, "12:00": True, "23:59": False}

    def test_データが無くても200で返る(self, client: TestClient):
        body = client.get("/api/today").json()

        assert body["research_hours"] == 7.0
        assert body["free_hours"] == 7.0  # タスクが無いので引くものがない
        assert body["open_task_count"] == 0
        assert body["nearest_task_label"] is None
        assert body["tomorrow_event"] is None
        assert len(body["free_slots"]) == 2
        assert len(body["research_slots"]) == 1

    def test_dateクエリで対象日を変えられる(self, session: Session, client: TestClient):
        seed_day(session)

        body = client.get("/api/today?date=2026-07-31").json()

        assert body["date"] == "2026-07-31"
        assert body["event_count"] == 1  # 説明会だけ


class TestTasksApi:
    def test_今日のタスク一覧を締切順で返す(self, session: Session, client: TestClient):
        seed_day(session)

        tasks = client.get(f"/api/tasks/today?date={DAY}").json()

        assert [t["short_label"] for t in tasks] == [None, "日程回答", "ES提出"]

    def test_チェックで完了フラグが反転する(self, session: Session, client: TestClient):
        """研究時間は予定だけで決まるので、チェックしても変わらない（2026-08-03 の決定）。"""
        seed_day(session)
        before = client.get("/api/today").json()

        target = next(t for t in client.get("/api/tasks/today").json() if t["short_label"] == "ES提出")
        patched = client.patch(f"/api/tasks/{target['id']}", json={"is_done": True})

        assert patched.status_code == 200
        assert patched.json()["is_done"] is True

        after = client.get("/api/today").json()
        # 研究時間は予定だけで決まるので動かない
        assert after["research_hours"] == before["research_hours"]
        assert after["open_task_count"] == before["open_task_count"] - 1
        # 空き時間は片付けた見積り（240分 = 4h）だけ増える
        assert after["free_hours"] - before["free_hours"] == 4.0

    def test_存在しないタスクは404(self, client: TestClient):
        res = client.patch("/api/tasks/9999", json={"is_done": True})
        assert res.status_code == 404


class TestSeedTasks:
    """seed/tasks.json が実際に投入でき、デモの数字になることを確かめる。

    seed を書き換えたときに気付けるようにしておく（デモ動線1〜3 が壊れると痛いため）。
    """

    def test_seedを投入するとデモの値になる(self, session: Session, client: TestClient):
        from pathlib import Path

        from seed.load import _load_companies, _load_tasks
        from routers.events import sync_events_from_seed

        seed_dir = Path(__file__).resolve().parent.parent / "seed"
        _load_companies(session, seed_dir / "companies.json")
        sync_events_from_seed(session, seed_dir / "calendar.json")
        _load_tasks(session, seed_dir / "tasks.json")

        body = client.get(f"/api/today?date={DAY}").json()

        # 研究枠 7h − ゼミ1.5h − 面接1h = 4.5h（レポート 18:00〜20:00 は枠外）。
        # カジュアル面談 11:00〜12:00 はゼミの内側なので、重なりを二重に数えず 4.5h のまま
        assert body["research_hours"] == 4.5
        # 空き時間 = 5h（7h − レポート2h）− 未完了タスク 210 分（3.5h）= 1.5h
        assert body["free_hours"] == 1.5
        assert body["open_task_count"] == 5
        assert body["event_count"] == 4
        # 空きスロットは研究枠の外に3つ出て、それぞれ別のタスクが差し込まれる
        labels = [s["suggested_task_label"] for s in body["free_slots"]]
        assert labels == ["日程回答", "説明会予習", "想定問答"]
