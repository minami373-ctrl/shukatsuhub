"""選考ステータス管理ボード API（`03-today-focus/FEATURE_PAGE_SPECS.md` §7）。

conftest.py の session / client フィクスチャ（インメモリ DB）を使う。
基準日は 2026-07-30（木）・基準時刻は 12:20（services.freetime）。
"""

from datetime import datetime

from fastapi.testclient import TestClient
from sqlmodel import Session

from models import Company, Event, Task

STAGES = ["気になる", "エントリー", "書類選考", "面接", "最終・内定"]


def seed_pipeline(session: Session) -> dict[str, int]:
    """5列すべてに企業が入る状態を作り、名前 → id を返す。"""
    companies = [
        Company(name="アルファテック", domain="alphatech.co.jp", is_watched=True, stage="面接"),
        Company(name="ベータ社", domain="beta-inc.jp", is_watched=True, stage="エントリー"),
        Company(name="シータ電機", domain="theta-denki.co.jp", is_watched=True, stage="書類選考"),
        Company(name="カッパシステムズ", domain="kappa-systems.jp", is_watched=True, stage="最終・内定"),
        Company(name="イプシロン技研", domain="epsilon-giken.jp", is_watched=False, stage="気になる"),
    ]
    session.add_all(companies)
    session.commit()
    for c in companies:
        session.refresh(c)
    ids = {c.name: c.id or 0 for c in companies}

    session.add_all(
        [
            # アルファテックには未完了タスクと当日の予定を紐づける（状態タグの導出元）
            Task(
                title="アルファテック ES 提出",
                short_label="ES提出",
                due_at=datetime(2026, 7, 30, 23, 59),
                estimate_min=240,
                company_id=ids["アルファテック"],
            ),
            Task(
                title="アルファテック 完了済みの作業",
                due_at=datetime(2026, 7, 29, 10, 0),
                is_done=True,
                company_id=ids["アルファテック"],
            ),
            Event(
                external_id="alpha-interview",
                title="アルファテック 一次面接",
                kind="選考",
                start_at=datetime(2026, 7, 30, 15, 0),
                end_at=datetime(2026, 7, 30, 16, 0),
                company_id=ids["アルファテック"],
            ),
            # 基準時刻より前の予定は「次の予定」にしない
            Event(
                external_id="alpha-past",
                title="アルファテック 過去の説明会",
                kind="選考",
                start_at=datetime(2026, 7, 30, 9, 0),
                end_at=datetime(2026, 7, 30, 10, 0),
                company_id=ids["アルファテック"],
            ),
        ]
    )
    session.commit()
    return ids


def columns_of(payload: dict) -> dict[str, list[str]]:
    return {c["stage"]: [x["name"] for x in c["companies"]] for c in payload["columns"]}


def test_five_columns_always_returned(session: Session, client: TestClient) -> None:
    """列は常に5つ返す。空でも返さないと画面から列が消える（§7）。"""
    payload = client.get("/api/pipeline").json()

    assert [c["stage"] for c in payload["columns"]] == STAGES
    # 企業が0件でも5列
    assert all("companies" in c for c in payload["columns"])


def test_companies_go_to_their_stage(session: Session, client: TestClient) -> None:
    """企業が自分の段階の列に入る。"""
    seed_pipeline(session)

    cols = columns_of(client.get("/api/pipeline").json())

    assert cols["気になる"] == ["イプシロン技研"]
    assert cols["エントリー"] == ["ベータ社"]
    assert cols["書類選考"] == ["シータ電機"]
    assert cols["面接"] == ["アルファテック"]
    assert cols["最終・内定"] == ["カッパシステムズ"]


def test_header_counts(session: Session, client: TestClient) -> None:
    """ヘッダの `N社・選考中 N社・内定 N社`（§7）。

    「選考中」は エントリー / 書類選考 / 面接 の3段階。気になるは応募していないので除く。
    """
    seed_pipeline(session)

    counts = client.get("/api/pipeline").json()["counts"]

    assert counts["total"] == 5
    assert counts["in_progress"] == 3
    assert counts["offer"] == 1


def test_status_tag_is_derived_not_stored(session: Session, client: TestClient) -> None:
    """カードの状態タグの元になる値を Task / Event から導出する（保存しない）。"""
    seed_pipeline(session)

    cols = {
        c["stage"]: c["companies"]
        for c in client.get("/api/pipeline?date=2026-07-30").json()["columns"]
    }
    alpha = cols["面接"][0]

    # 未完了タスクの締切だけを見る（完了済みの 07/29 は選ばない）
    assert alpha["next_task_at"] == "2026-07-30T23:59:00"
    assert alpha["next_task_label"] == "ES提出"
    # 基準時刻 12:20 以降の予定だけを見る（09:00 の過去分は選ばない）
    assert alpha["next_event_at"] == "2026-07-30T15:00:00"
    assert alpha["next_event_title"] == "アルファテック 一次面接"


def test_no_task_or_event_means_no_tag(session: Session, client: TestClient) -> None:
    """紐づくタスクも予定も無い企業はタグ無し（推測でひも付けない）。"""
    seed_pipeline(session)

    cols = {c["stage"]: c["companies"] for c in client.get("/api/pipeline").json()["columns"]}
    epsilon = cols["気になる"][0]

    assert epsilon["next_task_at"] is None
    assert epsilon["next_event_at"] is None


def test_stage_change_moves_the_card(session: Session, client: TestClient) -> None:
    """段階を変えるとカードが別の列へ移り、ヘッダの件数も変わる。"""
    ids = seed_pipeline(session)

    res = client.patch(f"/api/companies/{ids['ベータ社']}", json={"stage": "最終・内定"})

    assert res.status_code == 200
    assert res.json()["stage"] == "最終・内定"
    payload = client.get("/api/pipeline").json()
    cols = columns_of(payload)
    assert cols["エントリー"] == []
    assert "ベータ社" in cols["最終・内定"]
    # 選考中が1減り、内定が1増える
    assert payload["counts"]["in_progress"] == 2
    assert payload["counts"]["offer"] == 2


def test_stage_must_be_one_of_five(session: Session, client: TestClient) -> None:
    """5値以外は 422。null で外すこともできない。"""
    ids = seed_pipeline(session)

    assert client.patch(f"/api/companies/{ids['ベータ社']}", json={"stage": "内定辞退"}).status_code == 422
    assert client.patch(f"/api/companies/{ids['ベータ社']}", json={"stage": None}).status_code == 422
    assert client.patch(f"/api/companies/{ids['ベータ社']}", json={}).status_code == 422
    # 弾いたあとも元の段階が残っている
    cols = columns_of(client.get("/api/pipeline").json())
    assert cols["エントリー"] == ["ベータ社"]


def test_create_company(session: Session, client: TestClient) -> None:
    """企業を追加すると指定した列に入る。既定は「気になる」。"""
    seed_pipeline(session)

    res = client.post(
        "/api/companies", json={"name": "オミクロン商会", "domain": "omicron.jp", "stage": "エントリー"}
    )

    assert res.status_code == 201
    assert res.json()["stage"] == "エントリー"
    assert "オミクロン商会" in columns_of(client.get("/api/pipeline").json())["エントリー"]

    # 段階を省略すると「気になる」
    default = client.post("/api/companies", json={"name": "ラムダ工業", "domain": "lambda.jp"}).json()
    assert default["stage"] == "気になる"


def test_create_rejects_bad_input(session: Session, client: TestClient) -> None:
    """空白だけの名前、`@` を含むドメイン、重複ドメインは保存しない。"""
    seed_pipeline(session)

    assert client.post("/api/companies", json={"name": "　 ", "domain": "x.jp"}).status_code == 422
    assert (
        client.post("/api/companies", json={"name": "テスト", "domain": "info@x.jp"}).status_code
        == 422
    )
    # domain は一意（spec.md §6）
    assert (
        client.post(
            "/api/companies", json={"name": "別名", "domain": "alphatech.co.jp"}
        ).status_code
        == 422
    )


def test_delete_only_when_nothing_is_linked(session: Session, client: TestClient) -> None:
    """タスク・予定が紐づく企業は消さない。参照が迷子になるのを防ぐ。"""
    ids = seed_pipeline(session)

    # アルファテックにはタスクと予定が紐づいている
    assert client.delete(f"/api/companies/{ids['アルファテック']}").status_code == 422
    # イプシロン技研は何も紐づいていないので消せる
    assert client.delete(f"/api/companies/{ids['イプシロン技研']}").status_code == 204
    assert columns_of(client.get("/api/pipeline").json())["気になる"] == []
    assert client.delete("/api/companies/9999").status_code == 404


# ===== 企業追加時の締切（Task として登録する） =====


def test_create_with_deadline_registers_a_task(session: Session, client: TestClient) -> None:
    """締切を渡すと Task として登録され、カードの状態タグの元になる。"""
    seed_pipeline(session)

    created = client.post(
        "/api/companies",
        json={
            "name": "オミクロン商会",
            "domain": "omicron.jp",
            "stage": "エントリー",
            "deadline_at": "2026-08-01T23:59:00",
            "deadline_label": "ES提出",
            "deadline_estimate_min": 120,
        },
    ).json()

    assert created["next_task_at"] == "2026-08-01T23:59:00"
    assert created["next_task_label"] == "ES提出"

    # タスク一覧にも出る（同じ Task なので今日画面・空き時間算出にも効く）
    tasks = client.get("/api/tasks?scope=all").json()["tasks"]
    added = next(t for t in tasks if t["company_name"] == "オミクロン商会")
    assert added["title"] == "オミクロン商会 ES提出"
    assert added["estimate_min"] == 120
    assert added["is_done"] is False


def test_deadline_label_defaults(session: Session, client: TestClient) -> None:
    """締切の名前を省略しても既定の文言で登録される。"""
    seed_pipeline(session)

    created = client.post(
        "/api/companies",
        json={"name": "ラムダ工業", "domain": "lambda.jp", "deadline_at": "2026-08-10T18:00:00"},
    ).json()

    assert created["next_task_label"] == "選考の締切"


def test_create_without_deadline_makes_no_task(session: Session, client: TestClient) -> None:
    """締切は任意。渡さなければ Task を勝手に作らない（気になる段階では未定のこともある）。"""
    seed_pipeline(session)
    before = len(client.get("/api/tasks?scope=all").json()["tasks"])

    created = client.post("/api/companies", json={"name": "ミュー電子", "domain": "mu.jp"}).json()

    assert created["next_task_at"] is None
    assert len(client.get("/api/tasks?scope=all").json()["tasks"]) == before


def test_company_with_deadline_cannot_be_deleted(session: Session, client: TestClient) -> None:
    """締切つきで登録した企業は Task が紐づくので、そのままでは削除できない。"""
    seed_pipeline(session)
    created = client.post(
        "/api/companies",
        json={"name": "ニュー工業", "domain": "nu.jp", "deadline_at": "2026-08-10T18:00:00"},
    ).json()

    assert client.delete(f"/api/companies/{created['id']}").status_code == 422


# ===== マッチング用の条件（job_type / location / remote_ok / tags）=====


def test_create_and_patch_matching_fields(session: Session, client: TestClient) -> None:
    """追加時にも変更時にも条件を入れられる（§5.9 の照合対象）。"""
    seed_pipeline(session)

    created = client.post(
        "/api/companies",
        json={
            "name": "オミクロン解析",
            "domain": "omicron-analytics.jp",
            "job_type": "データサイエンティスト",
            "location": "東京",
            "remote_ok": True,
            "tags": "研究開発,成長環境",
        },
    ).json()
    assert created["job_type"] == "データサイエンティスト"
    assert created["remote_ok"] is True
    assert created["tags"] == "研究開発,成長環境"

    updated = client.patch(
        f"/api/companies/{created['id']}", json={"location": "福岡", "remote_ok": False}
    ).json()
    assert updated["location"] == "福岡"
    assert updated["remote_ok"] is False
    # 送っていない項目は保持される
    assert updated["job_type"] == "データサイエンティスト"
    assert updated["tags"] == "研究開発,成長環境"


def test_matching_fields_can_be_cleared_but_not_remote_ok(
    session: Session, client: TestClient
) -> None:
    """職種・勤務地・タグは空文字で未登録に戻せる。remote_ok は必須なので null 不可。"""
    ids = seed_pipeline(session)

    cleared = client.patch(f"/api/companies/{ids['ベータ社']}", json={"job_type": ""}).json()
    assert cleared["job_type"] == ""

    assert (
        client.patch(f"/api/companies/{ids['ベータ社']}", json={"remote_ok": None}).status_code
        == 422
    )
