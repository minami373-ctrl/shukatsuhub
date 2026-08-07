"""プロフィール機能のテスト（spec.md §7「プロフィール（②）」の受け入れ条件）。

- 充実度の算出：9項目中6項目が空でないとき 67%
- プロフィールの永続化：保存後に取得し直しても内容が残る（画面リロード相当）
  ※コピーボタン（navigator.clipboard）はフロント側の責務なので Vitest で検証する
"""

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from models import PROFILE_FIELDS, PROFILE_ID, Profile, completeness

# 6項目だけ埋めたプロフィール（受け入れ条件「9項目中6項目 → 67%」用）
SIX_FILLED = {
    "gakuchika": "研究室の輪講運営を担当しました。",
    "strengths": "散らばった情報を1か所に集めることです。",
    "self_pr": "手を動かして課題を切り分けます。",
    "academics": "時系列データの異常検知を研究しています。",
    "motivation_template": "",
    "job_axis": "",
    "skills": "基本情報技術者。Python と PyTorch。",
    "career_plan": "",
    "teamwork": "3人チームで前処理を担当しました。",
}


def body(**overrides: str) -> dict[str, str]:
    """9項目すべてを持つリクエストボディを作る。"""
    return {name: "" for name in PROFILE_FIELDS} | overrides


# --- 充実度の算出 -------------------------------------------------------


def test_completeness_is_67_when_6_of_9_filled(client: TestClient) -> None:
    """受け入れ条件：9項目のうち6項目が空でないとき 67%（6 / 9 の四捨五入）。"""
    res = client.put("/api/profile", json=SIX_FILLED)

    assert res.status_code == 200
    assert res.json()["completeness"] == 67


@pytest.mark.parametrize(
    ("filled_count", "expected"),
    [(0, 0), (1, 11), (2, 22), (3, 33), (4, 44), (5, 56), (6, 67), (7, 78), (8, 89), (9, 100)],
)
def test_completeness_for_each_filled_count(
    client: TestClient, filled_count: int, expected: int
) -> None:
    """0〜9項目それぞれの充実度が「空でない項目数 ÷ 9 の四捨五入」になる。"""
    payload = body(**{name: "入力あり" for name in PROFILE_FIELDS[:filled_count]})

    res = client.put("/api/profile", json=payload)

    assert res.json()["completeness"] == expected


def test_whitespace_only_field_counts_as_empty(client: TestClient) -> None:
    """空白のみの入力は未入力として数える（spec.md §5.5 補足）。"""
    payload = body(gakuchika="   ", strengths="　", self_pr="実際の入力")

    res = client.put("/api/profile", json=payload)

    assert res.json()["completeness"] == 11  # 1 / 9


def test_completeness_is_a_derived_value_not_a_column() -> None:
    """completeness は保存しない導出値（spec.md §6）。"""
    assert not hasattr(Profile(id=PROFILE_ID), "completeness")
    assert completeness(Profile(id=PROFILE_ID, gakuchika="a", strengths="b")) == 22


# --- 永続化 -------------------------------------------------------------


def test_saved_profile_is_returned_after_reload(client: TestClient) -> None:
    """受け入れ条件：保存した9項目が、取得し直しても保持されている（リロード相当）。"""
    payload = body(
        gakuchika="ガクチカの本文",
        strengths="強みの本文",
        self_pr="自己PRの本文",
        academics="学業の本文",
        motivation_template="志望動機テンプレの本文",
        job_axis="裁量,技術力,勤務地",
        skills="資格・スキルの本文",
        career_plan="キャリアプランの本文",
        teamwork="チームで活動した経験の本文",
    )

    client.put("/api/profile", json=payload)
    reloaded = client.get("/api/profile").json()

    for name in PROFILE_FIELDS:
        assert reloaded[name] == payload[name]
    assert reloaded["completeness"] == 100


def test_put_overwrites_previous_content(client: TestClient) -> None:
    """2回目の保存で内容が置き換わる（追記にならない）。"""
    client.put("/api/profile", json=body(gakuchika="1回目"))

    client.put("/api/profile", json=body(gakuchika="2回目"))

    assert client.get("/api/profile").json()["gakuchika"] == "2回目"


def test_put_keeps_single_record(client: TestClient, session: Session) -> None:
    """何度保存してもレコードは id = 1 の1件だけ（spec.md §6）。"""
    client.put("/api/profile", json=body(gakuchika="a"))
    client.put("/api/profile", json=body(gakuchika="b"))

    rows = session.exec(select(Profile)).all()
    assert [row.id for row in rows] == [PROFILE_ID]


def test_empty_string_is_allowed(client: TestClient) -> None:
    """空文字は許容する（spec.md §5.5）。"""
    client.put("/api/profile", json=body(gakuchika="いったん入力"))

    res = client.put("/api/profile", json=body())

    assert res.status_code == 200
    assert res.json()["completeness"] == 0


def test_get_returns_empty_profile_when_not_saved_yet(client: TestClient) -> None:
    """未保存でも 404 にせず空のプロフィールを返す（spec.md §5.5 補足）。"""
    res = client.get("/api/profile")

    assert res.status_code == 200
    assert all(res.json()[name] == "" for name in PROFILE_FIELDS)
    assert res.json()["completeness"] == 0


def test_get_does_not_create_a_record(client: TestClient, session: Session) -> None:
    """GET は DB に書き込まない（作成は PUT のときだけ）。"""
    client.get("/api/profile")

    assert session.get(Profile, PROFILE_ID) is None


# --- 文字数の上限 -------------------------------------------------------


def test_over_8000_chars_returns_422_with_field_label(client: TestClient) -> None:
    """8000 文字超は 422 と項目名を返す（spec.md §5.5）。"""
    res = client.put("/api/profile", json=body(gakuchika="あ" * 8001))

    assert res.status_code == 422
    assert "ガクチカ" in res.json()["detail"]


def test_exactly_8000_chars_is_accepted(client: TestClient) -> None:
    """境界値：ちょうど 8000 文字は保存できる。"""
    res = client.put("/api/profile", json=body(gakuchika="あ" * 8000))

    assert res.status_code == 200


def test_over_8000_chars_does_not_save_anything(client: TestClient) -> None:
    """1項目でも超過したら9項目とも保存しない（spec.md §5.5）。"""
    client.put("/api/profile", json=body(gakuchika="保存済みの本文"))

    client.put("/api/profile", json=body(gakuchika="上書き", strengths="あ" * 8001))

    assert client.get("/api/profile").json()["gakuchika"] == "保存済みの本文"
