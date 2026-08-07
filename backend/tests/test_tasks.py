"""タスク・締め切りページの一覧 API（`03-today-focus/FEATURE_PAGE_SPECS.md` §6）。

conftest.py の session / client フィクスチャ（インメモリ DB）を使う。

基準日は 2026-07-30（木）。この週は 07/27（月）〜08/02（日）。
期限切れ判定の基準時刻は services.freetime.SEED_NOW_TIME = 12:20。
"""

from datetime import datetime

from fastapi.testclient import TestClient
from sqlmodel import Session

from models import Company, Task

DAY = "2026-07-30"


def seed_tasks(session: Session) -> None:
    """週の内外・完了済み・期限切れが混ざった状態を作る。

    | タスク | 締切 | 状態 | 今週(07/27-08/02) |
    |---|---|---|---|
    | 先週のレポート | 07/24 18:00 | 未完了・期限切れ | 外 |
    | 日程回答 | 07/30 12:00 | 未完了・期限切れ（12:20 基準） | 内 |
    | ES提出 | 07/30 23:59 | 未完了 | 内 |
    | スカウト仕分け | 07/30 09:12 | 完了 | 内 |
    | 想定問答の確認 | 08/02 10:00 | 未完了 | 内 |
    | 来週の説明会予約 | 08/05 10:00 | 未完了 | 外 |
    """
    company = Company(name="アルファテック", domain="alphatech.co.jp", is_watched=True)
    session.add(company)
    session.commit()
    session.refresh(company)

    session.add_all(
        [
            Task(
                title="先週のレポート提出",
                short_label="レポート",
                due_at=datetime(2026, 7, 24, 18, 0),
                estimate_min=60,
            ),
            Task(
                title="デルタ商事 面接日程を回答",
                short_label="日程回答",
                due_at=datetime(2026, 7, 30, 12, 0),
                estimate_min=15,
                badge="要返信",
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
            Task(
                title="ガンマ工業 想定問答を確認",
                short_label="想定問答",
                due_at=datetime(2026, 8, 2, 10, 0),
                estimate_min=45,
                badge="準備",
            ),
            Task(
                title="来週の説明会を予約",
                due_at=datetime(2026, 8, 5, 10, 0),
                estimate_min=15,
            ),
        ]
    )
    session.commit()


def titles(payload: dict) -> list[str]:
    return [task["title"] for task in payload["tasks"]]


def test_scope_defaults_to_today(session: Session, client: TestClient) -> None:
    """既定は「今日」。締切が対象日以前の未完了 ＋ 当日締切の完了分（§6 / spec.md §4.1）。"""
    seed_tasks(session)

    payload = client.get(f"/api/tasks?date={DAY}").json()

    assert payload["scope"] == "today"
    # 先週のレポートは「締切が対象日以前の未完了」なので今日にも出る。08/02 と 08/05 は出ない。
    # 並びは締切順の一列（完了済みを末尾へ寄せない。spec.md §4.1）
    assert titles(payload) == [
        "先週のレポート提出",
        "スカウト3件を仕分け",
        "デルタ商事 面接日程を回答",
        "アルファテック ES 提出",
    ]


def test_scope_week_is_calendar_week(session: Session, client: TestClient) -> None:
    """「今週」は暦の週（月曜〜日曜）。07/24 と 08/05 は範囲外（§6）。"""
    seed_tasks(session)

    payload = client.get(f"/api/tasks?scope=week&date={DAY}").json()

    assert payload["scope"] == "week"
    assert titles(payload) == [
        "スカウト3件を仕分け",
        "デルタ商事 面接日程を回答",
        "アルファテック ES 提出",
        "ガンマ工業 想定問答を確認",
    ]


def test_scope_all_and_done(session: Session, client: TestClient) -> None:
    """「すべて」は完了済みも含む全件、「完了」は完了済みだけ（§6）。"""
    seed_tasks(session)

    assert len(client.get(f"/api/tasks?scope=all&date={DAY}").json()["tasks"]) == 6
    assert titles(client.get(f"/api/tasks?scope=done&date={DAY}").json()) == ["スカウト3件を仕分け"]


def test_counts_do_not_change_with_scope(session: Session, client: TestClient) -> None:
    """ページヘッダの件数は絞り込みと独立（§6 の「今日 5件・期限切れ 1件・今週 12件」）。"""
    seed_tasks(session)

    for scope in ("today", "week", "all", "done"):
        counts = client.get(f"/api/tasks?scope={scope}&date={DAY}").json()["counts"]
        # 今日 = 締切が 07/30 以前の未完了3件（レポート・日程回答・ES提出）
        assert counts["today"] == 3
        # 期限切れ = そのうち 12:20 を過ぎている2件（07/24 18:00・07/30 12:00）
        assert counts["overdue"] == 2
        # 今週 = 07/27〜08/02 締切の4件（完了済みも数える）
        assert counts["week"] == 4


def test_overdue_flag_uses_seed_now(session: Session, client: TestClient) -> None:
    """期限タグの色分けに使う is_overdue と now。基準時刻は 12:20（spec.md §5.3）。"""
    seed_tasks(session)

    payload = client.get(f"/api/tasks?scope=all&date={DAY}").json()

    assert payload["now"] == "2026-07-30T12:20:00"
    overdue = {task["title"]: task["is_overdue"] for task in payload["tasks"]}
    assert overdue["先週のレポート提出"] is True
    assert overdue["デルタ商事 面接日程を回答"] is True
    # 23:59 締切はまだ超過していない
    assert overdue["アルファテック ES 提出"] is False
    # 完了済みは 09:12 締切だが超過扱いにしない
    assert overdue["スカウト3件を仕分け"] is False


def test_company_name_is_included(session: Session, client: TestClient) -> None:
    """§6「企業名を必ず表示する」ため、一覧が company_name を返すこと。"""
    seed_tasks(session)

    tasks = {t["title"]: t for t in client.get(f"/api/tasks?scope=all&date={DAY}").json()["tasks"]}

    assert tasks["アルファテック ES 提出"]["company_name"] == "アルファテック"
    # 企業に紐づかないタスクは null（推測でひも付けない）
    assert tasks["スカウト3件を仕分け"]["company_name"] is None


def test_unknown_scope_is_rejected(session: Session, client: TestClient) -> None:
    """scope は4値のみ。想定外の値は 422 にする（黙って既定へ落とさない）。"""
    seed_tasks(session)

    assert client.get(f"/api/tasks?scope=yesterday&date={DAY}").status_code == 422


# ===== 追加・変更・削除（FEATURE_PAGE_SPECS.md §6） =====


def test_create_task(session: Session, client: TestClient) -> None:
    """内容・期限・重要度だけで登録できる（口頭で言われた予定をその場で入れるため）。"""
    seed_tasks(session)

    res = client.post(
        "/api/tasks",
        json={"title": "ベータ社 面接の日程を返信", "due_at": "2026-07-31T18:00:00", "badge": "要返信"},
    )

    assert res.status_code == 201
    created = res.json()
    assert created["title"] == "ベータ社 面接の日程を返信"
    assert created["badge"] == "要返信"
    # 見積りは省略時 30 分（spec.md §6 の既定値）
    assert created["estimate_min"] == 30
    assert created["is_done"] is False
    # 一覧にも増えている
    assert len(client.get(f"/api/tasks?scope=all&date={DAY}").json()["tasks"]) == 7


def test_create_rejects_blank_title_and_bad_badge(session: Session, client: TestClient) -> None:
    """空白だけのタイトルと、3値以外の重要度は保存しない。"""
    blank = client.post("/api/tasks", json={"title": "　 ", "due_at": "2026-07-31T18:00:00"})
    bad_badge = client.post(
        "/api/tasks",
        json={"title": "テスト", "due_at": "2026-07-31T18:00:00", "badge": "至急"},
    )
    negative = client.post(
        "/api/tasks",
        json={"title": "テスト", "due_at": "2026-07-31T18:00:00", "estimate_min": -1},
    )

    assert blank.status_code == 422
    assert bad_badge.status_code == 422
    assert negative.status_code == 422
    assert client.get(f"/api/tasks?scope=all&date={DAY}").json()["tasks"] == []


def test_create_rejects_unknown_company(session: Session, client: TestClient) -> None:
    """存在しない企業には紐づけない（推測でひも付けないのと同じ理由）。"""
    seed_tasks(session)

    res = client.post(
        "/api/tasks",
        json={"title": "テスト", "due_at": "2026-07-31T18:00:00", "company_id": 999},
    )

    assert res.status_code == 422


def test_patch_updates_only_given_fields(session: Session, client: TestClient) -> None:
    """変更は渡した項目だけ。badge を送らなければ消えない。"""
    seed_tasks(session)
    target = next(
        t for t in client.get(f"/api/tasks?scope=all&date={DAY}").json()["tasks"]
        if t["title"] == "アルファテック ES 提出"
    )

    res = client.patch(
        f"/api/tasks/{target['id']}",
        json={"title": "アルファテック ES を提出する", "due_at": "2026-07-31T23:59:00"},
    )

    assert res.status_code == 200
    updated = res.json()
    assert updated["title"] == "アルファテック ES を提出する"
    assert updated["due_at"] == "2026-07-31T23:59:00"
    # 送っていない項目は保持される
    assert updated["badge"] == "最優先"
    assert updated["company_name"] == "アルファテック"


def test_patch_can_clear_badge_explicitly(session: Session, client: TestClient) -> None:
    """null を明示すれば重要度を外せる（未指定と null を区別する）。"""
    seed_tasks(session)
    target = next(
        t for t in client.get(f"/api/tasks?scope=all&date={DAY}").json()["tasks"]
        if t["title"] == "アルファテック ES 提出"
    )

    updated = client.patch(f"/api/tasks/{target['id']}", json={"badge": None}).json()

    assert updated["badge"] is None


def test_patch_is_done_only_still_works(session: Session, client: TestClient) -> None:
    """今日画面のチェックボックス（is_done だけを送る）と互換であること。"""
    seed_tasks(session)
    target = next(
        t for t in client.get(f"/api/tasks?scope=all&date={DAY}").json()["tasks"]
        if t["title"] == "アルファテック ES 提出"
    )

    updated = client.patch(f"/api/tasks/{target['id']}", json={"is_done": True}).json()

    assert updated["is_done"] is True
    assert updated["title"] == "アルファテック ES 提出"


def test_patch_empty_body_is_rejected(session: Session, client: TestClient) -> None:
    """空の変更は 422。黙って200を返すと保存できたように見える。"""
    seed_tasks(session)
    target = client.get(f"/api/tasks?scope=all&date={DAY}").json()["tasks"][0]

    assert client.patch(f"/api/tasks/{target['id']}", json={}).status_code == 422


def test_delete_task(session: Session, client: TestClient) -> None:
    """削除は指定した1件だけ。他のタスクは残る。"""
    seed_tasks(session)
    target = next(
        t for t in client.get(f"/api/tasks?scope=all&date={DAY}").json()["tasks"]
        if t["title"] == "来週の説明会を予約"
    )

    res = client.delete(f"/api/tasks/{target['id']}")

    assert res.status_code == 204
    remaining = titles(client.get(f"/api/tasks?scope=all&date={DAY}").json())
    assert "来週の説明会を予約" not in remaining
    assert len(remaining) == 5


def test_missing_task_is_404(session: Session, client: TestClient) -> None:
    """存在しない id への変更・削除は 404。"""
    seed_tasks(session)

    assert client.patch("/api/tasks/9999", json={"is_done": True}).status_code == 404
    assert client.delete("/api/tasks/9999").status_code == 404


# ===== 重要度（priority。docs/spec.md §6・2026-08-04 追加） =====


def test_priority_defaults_to_middle(session: Session, client: TestClient) -> None:
    """省略したら「中」。seed で作ったタスクも既定値になる。"""
    seed_tasks(session)

    created = client.post(
        "/api/tasks", json={"title": "重要度を省略", "due_at": "2026-07-31T18:00:00"}
    ).json()

    assert created["priority"] == "中"
    assert all(t["priority"] == "中" for t in client.get(f"/api/tasks?scope=all&date={DAY}").json()["tasks"])


def test_priority_is_independent_from_badge(session: Session, client: TestClient) -> None:
    """重要度（度合い）とタグ（行動の種類）は別の軸。片方を変えても他方は動かない。"""
    seed_tasks(session)

    created = client.post(
        "/api/tasks",
        json={
            "title": "アルファテック 最終面接の準備",
            "due_at": "2026-08-01T09:00:00",
            "priority": "高",
            "badge": "準備",
        },
    ).json()
    assert (created["priority"], created["badge"]) == ("高", "準備")

    # タグだけ外しても重要度は残る
    cleared = client.patch(f"/api/tasks/{created['id']}", json={"badge": None}).json()
    assert (cleared["priority"], cleared["badge"]) == ("高", None)

    # 重要度だけ下げてもタグは戻らない
    lowered = client.patch(f"/api/tasks/{created['id']}", json={"priority": "低"}).json()
    assert (lowered["priority"], lowered["badge"]) == ("低", None)


def test_priority_rejects_bad_values(session: Session, client: TestClient) -> None:
    """3値以外は 422。null で外すこともできない（必須項目なので）。"""
    seed_tasks(session)
    target = client.get(f"/api/tasks?scope=all&date={DAY}").json()["tasks"][0]

    assert (
        client.post(
            "/api/tasks",
            json={"title": "x", "due_at": "2026-07-31T18:00:00", "priority": "最高"},
        ).status_code
        == 422
    )
    assert client.patch(f"/api/tasks/{target['id']}", json={"priority": None}).status_code == 422
    # 弾いたあとも元の値が残っている
    assert client.get(f"/api/tasks?scope=all&date={DAY}").json()["tasks"][0]["priority"] == "中"


def test_priority_does_not_change_ordering(session: Session, client: TestClient) -> None:
    """並びは締切順のまま。重要度で追い越さない（spec.md §6 の注記）。"""
    seed_tasks(session)
    target = next(
        t for t in client.get(f"/api/tasks?scope=all&date={DAY}").json()["tasks"]
        if t["title"] == "来週の説明会を予約"
    )
    before = titles(client.get(f"/api/tasks?scope=all&date={DAY}").json())

    client.patch(f"/api/tasks/{target['id']}", json={"priority": "高"})

    assert titles(client.get(f"/api/tasks?scope=all&date={DAY}").json()) == before
