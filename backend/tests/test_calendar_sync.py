"""カレンダー同期とイベント取得のテスト（docs/spec.md §7 受け入れ条件「カレンダー・今日」）。

- 同期が冪等（2回押しても件数が増えない）
- 選考 / 学業 の kind が保持される（画面の色分けの元になる）
- seed が壊れていても DB を変更しない（§5.4 エラー時）
- GET /api/events が期間で絞れる
"""

import json
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from models import Event
from routers.events import SEED_PATH, SeedError, sync_events_from_seed


def _count_events(session: Session) -> int:
    return len(list(session.exec(select(Event))))


# --- 同期 ---------------------------------------------------------------


def test_sync_is_idempotent(session: Session) -> None:
    """2回同期しても件数が増えず、2回目は全件 updated になる。"""
    first = sync_events_from_seed(session, SEED_PATH)
    count_after_first = _count_events(session)

    second = sync_events_from_seed(session, SEED_PATH)

    assert first["added"] == count_after_first
    assert first["updated"] == 0
    assert second["added"] == 0
    assert second["updated"] == count_after_first
    assert _count_events(session) == count_after_first


def test_sync_updates_changed_event(session: Session, tmp_path: Path) -> None:
    """同じ external_id で内容が変わっていたら更新される。"""
    seed = tmp_path / "calendar.json"
    base = {
        "external_id": "evt-1",
        "title": "一次面接",
        "kind": "選考",
        "start_at": "2026-07-30T15:00:00",
        "end_at": "2026-07-30T16:00:00",
        "location": "オンライン・Zoom",
    }
    seed.write_text(json.dumps([base], ensure_ascii=False), encoding="utf-8")
    sync_events_from_seed(session, seed)

    seed.write_text(
        json.dumps([{**base, "start_at": "2026-07-30T16:00:00", "end_at": "2026-07-30T17:00:00"}],
                   ensure_ascii=False),
        encoding="utf-8",
    )
    result = sync_events_from_seed(session, seed)

    event = session.exec(select(Event).where(Event.external_id == "evt-1")).one()
    assert result == {"added": 0, "updated": 1}
    assert event.start_at == datetime(2026, 7, 30, 16, 0)


def test_sync_keeps_kind_for_color(session: Session) -> None:
    """選考と学業の両方が取り込まれる（画面はこの kind で色を分ける）。"""
    sync_events_from_seed(session, SEED_PATH)

    kinds = {e.kind for e in session.exec(select(Event))}
    assert kinds == {"選考", "学業"}


# --- seed が壊れているとき（§5.4 エラー時）-------------------------------


@pytest.mark.parametrize(
    "content",
    [
        "{ not json",  # パースできない
        '{"external_id": "x"}',  # 配列でない
        '[{"title": "件名なし", "kind": "選考", "start_at": "2026-07-30T10:00:00", "end_at": "2026-07-30T11:00:00"}]',  # external_id 欠落
        '[{"external_id": "x", "title": "t", "kind": "会食", "start_at": "2026-07-30T10:00:00", "end_at": "2026-07-30T11:00:00"}]',  # kind が不正
        '[{"external_id": "x", "title": "t", "kind": "選考", "start_at": "2026-07-30T10:00:00", "end_at": "2026-07-30T09:00:00"}]',  # end <= start
    ],
)
def test_broken_seed_raises_and_keeps_db_unchanged(
    session: Session, tmp_path: Path, content: str
) -> None:
    sync_events_from_seed(session, SEED_PATH)
    before = _count_events(session)

    broken = tmp_path / "calendar.json"
    broken.write_text(content, encoding="utf-8")

    with pytest.raises(SeedError):
        sync_events_from_seed(session, broken)

    assert _count_events(session) == before


def test_missing_seed_raises(session: Session, tmp_path: Path) -> None:
    with pytest.raises(SeedError):
        sync_events_from_seed(session, tmp_path / "存在しない.json")


# --- API ---------------------------------------------------------------


def test_sync_endpoint_returns_counts(client: TestClient) -> None:
    first = client.post("/api/calendar/sync")
    second = client.post("/api/calendar/sync")

    assert first.status_code == 200
    assert first.json()["added"] > 0
    # deleted / source は spec.md §5.7.2 で追加された項目。未認可なので source は seed
    assert second.json() == {
        "added": 0,
        "updated": first.json()["added"],
        "deleted": 0,
        "source": "seed",
    }


def test_list_events_filters_by_period(client: TestClient) -> None:
    """期間に重なるイベントだけが開始時刻の昇順で返る。"""
    client.post("/api/calendar/sync")

    res = client.get("/api/events", params={"from": "2026-07-30T00:00:00", "to": "2026-07-31T00:00:00"})

    assert res.status_code == 200
    events = res.json()
    assert [e["title"] for e in events] == [
        "研究室ゼミ",
        "デルタ商事 カジュアル面談",  # ゼミと重なる予定（衝突の可視化のデモ用）
        "アルファテック 一次面接",
        "課題レポート作成",
    ]
    assert all(e["start_at"].startswith("2026-07-30") for e in events)


def test_list_events_includes_events_overlapping_the_boundary(client: TestClient) -> None:
    """期間の境界をまたぐ予定は消えない（週表示で切れないようにするため）。"""
    client.post("/api/calendar/sync")

    # 10:35〜10:50 は 10:30〜12:00 のゼミの内側。開始も終了も期間外だが重なっている。
    # 11:00 以降はカジュアル面談も重なるため、ゼミだけが返る区間を選んでいる
    res = client.get("/api/events", params={"from": "2026-07-30T10:35:00", "to": "2026-07-30T10:50:00"})

    assert [e["title"] for e in res.json()] == ["研究室ゼミ"]


def test_list_events_rejects_reversed_period(client: TestClient) -> None:
    res = client.get("/api/events", params={"from": "2026-07-31T00:00:00", "to": "2026-07-30T00:00:00"})

    assert res.status_code == 422
