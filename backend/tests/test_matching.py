"""企業マッチングの算出（docs/spec.md §5.9）と `/api/matching`。

マッチ率は AI を使わないので、**同じ入力なら常に同じ値**になることを前提にテストできる。
重みは 職種3 / 勤務地2 / 年収2 / 休日1 / リモート1 / 就活軸1つにつき1。
"""

from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlmodel import Session

from models import Company, Profile
from services.matching import MatchCriteria, MatchTarget, match, split_csv

ALPHA = MatchTarget(
    job_type="ソフトウェアエンジニア",
    location="東京",
    remote_ok=True,
    salary_min=450,
    holidays_per_year=125,
    tags="成長環境,若手裁量",
)


def test_all_conditions_met_is_100(session: Session) -> None:
    """指定した条件をすべて満たせば 100%。"""
    criteria = MatchCriteria(
        job_type="ソフトウェアエンジニア",
        location="東京",
        remote_only=True,
        salary_min=400,
        holidays_min=120,
        axes=("成長環境",),
    )

    result = match(criteria, ALPHA)

    assert result.rate == 100
    assert result.matched_axes == ["成長環境"]


def test_weights(session: Session) -> None:
    """満たした重み ÷ 指定した重み。職種3 / 勤務地2 / リモート1。"""
    criteria = MatchCriteria(job_type="ソフトウェアエンジニア", location="大阪", remote_only=True)

    # 分母 3+2+1=6、分子は職種3 + リモート1 = 4 → 67%
    assert match(criteria, ALPHA).rate == 67


def test_salary_and_holidays_weights(session: Session) -> None:
    """年収は重み2・休日は重み1。希望以上なら合致（企業側の値が下限を上回ればよい）。"""
    # 分母 2+1=3、年収は 450 >= 400 で合致・休日は 125 < 130 で不足 → 分子2 → 67%
    result = match(MatchCriteria(salary_min=400, holidays_min=130), ALPHA)

    assert result.rate == 67
    assert result.reasons == ["想定年収が希望以上：450万円"]


def test_salary_zero_is_a_condition(session: Session) -> None:
    """0 は「指定しない」ではない。0 万円以上という条件として数える（None だけが未指定）。"""
    assert MatchCriteria(salary_min=0).has_any is True
    assert match(MatchCriteria(salary_min=0), ALPHA).rate == 100


def test_unregistered_salary_and_holidays_never_match(session: Session) -> None:
    """企業側が未登録（None）なら合致しない（推測で埋めない。CLAUDE.md §E）。"""
    unknown = MatchTarget(job_type="総合職", salary_min=None, holidays_per_year=None)

    result = match(MatchCriteria(salary_min=300, holidays_min=100), unknown)

    assert result.rate == 0
    assert result.reasons == []


def test_axis_weight_is_one_each(session: Session) -> None:
    """就活軸は1つにつき重み1。合致した軸だけ理由に出る。"""
    criteria = MatchCriteria(axes=("成長環境", "若手裁量", "海外勤務"))

    result = match(criteria, ALPHA)

    # 分母3・分子2 → 67%
    assert result.rate == 67
    assert result.matched_axes == ["成長環境", "若手裁量"]
    # 合致しなかった軸は理由に出さない（推測で理由を作らない）
    assert all("海外勤務" not in r for r in result.reasons)


def test_empty_company_field_never_matches(session: Session) -> None:
    """会社側が空なら合致しない（推測で埋めない。CLAUDE.md §E）。"""
    empty = MatchTarget(job_type=None, location="", remote_ok=False, tags=None)

    result = match(MatchCriteria(job_type="ソフトウェアエンジニア", location="東京"), empty)

    assert result.rate == 0
    assert result.reasons == []


def test_no_criteria_is_zero(session: Session) -> None:
    """条件が0個なら 0%。条件なしで 100% と出すのは意味がない。"""
    assert match(MatchCriteria(), ALPHA).rate == 0


def test_remote_only_false_is_not_a_condition(session: Session) -> None:
    """「リモート必須」が false のときはリモートを条件に数えない。"""
    # 職種だけを条件にしたのと同じ結果になる
    with_flag = match(MatchCriteria(job_type="ソフトウェアエンジニア", remote_only=False), ALPHA)
    only_job = match(MatchCriteria(job_type="ソフトウェアエンジニア"), ALPHA)

    assert with_flag.rate == only_job.rate == 100


def test_job_type_is_partial_and_case_insensitive(session: Session) -> None:
    """表記ゆれに耐えるため職種と勤務地は部分一致・大文字小文字を区別しない。"""
    assert match(MatchCriteria(job_type="エンジニア"), ALPHA).rate == 100
    assert match(MatchCriteria(location="東京"), MatchTarget(location="東京都港区")).rate == 100


def test_result_is_deterministic(session: Session) -> None:
    """同じ入力なら常に同じ値（AI を使わないことの担保）。"""
    criteria = MatchCriteria(job_type="ソフトウェアエンジニア", axes=("成長環境",))

    assert [match(criteria, ALPHA).rate for _ in range(5)] == [100] * 5


def test_split_csv(session: Session) -> None:
    """カンマ区切りの分解。空要素と前後の空白を落とす。"""
    assert split_csv(" 成長環境 , 若手裁量 ,, ") == ["成長環境", "若手裁量"]
    assert split_csv(None) == []


# ===== API =====


def seed_companies(session: Session) -> None:
    session.add_all(
        [
            Company(
                name="アルファテック",
                domain="alphatech.co.jp",
                tags="成長環境,若手裁量",
                is_watched=True,
                stage="面接",
                job_type="ソフトウェアエンジニア",
                location="東京",
                remote_ok=True,
                salary_min=450,
                holidays_per_year=125,
            ),
            Company(
                name="ミュー精機",
                domain="mu-seiki.jp",
                tags="安定基盤",
                is_watched=False,
                stage="気になる",
                job_type="機械設計",
                location="静岡",
                remote_ok=False,
            ),
            Company(
                name="ラムダソフト",
                domain="lambda-soft.jp",
                tags="成長環境",
                is_watched=False,
                stage="気になる",
                job_type="ソフトウェアエンジニア",
                location="福岡",
                remote_ok=True,
                salary_min=460,
                holidays_per_year=130,
            ),
        ]
    )
    session.add(Profile(id=1, job_axis="成長環境,若手裁量"))
    session.commit()


def test_matching_api_sorts_by_rate(session: Session, client: TestClient) -> None:
    """マッチ率の高い順。同率は企業名順（並びが毎回変わらないように）。"""
    seed_companies(session)

    payload = client.post(
        "/api/matching",
        json={"job_type": "ソフトウェアエンジニア", "location": "東京", "scope": "search"},
    ).json()

    names = [i["name"] for i in payload["items"]]
    assert names[0] == "アルファテック"
    assert payload["items"][0]["rate"] >= payload["items"][-1]["rate"]
    # 何も合致しない企業は条件検索に出さない
    assert "ミュー精機" not in names


def test_matching_api_uses_profile_axes_by_default(session: Session, client: TestClient) -> None:
    """就活軸を省略したらプロフィールの job_axis を使う。"""
    seed_companies(session)

    payload = client.post("/api/matching", json={"scope": "search"}).json()

    assert payload["axes"] == ["成長環境", "若手裁量"]
    alpha = next(i for i in payload["items"] if i["name"] == "アルファテック")
    assert alpha["rate"] == 100


def test_matching_api_scopes(session: Session, client: TestClient) -> None:
    """おすすめ（70%以上）/ 条件検索（1つでも合致）/ 気になる の3セグメント。"""
    seed_companies(session)
    body = {"job_type": "ソフトウェアエンジニア", "location": "東京"}

    recommended = client.post("/api/matching", json={**body, "scope": "recommended"}).json()
    search = client.post("/api/matching", json={**body, "scope": "search"}).json()
    watched = client.post("/api/matching", json={**body, "scope": "watched"}).json()

    assert all(i["rate"] >= 70 for i in recommended["items"])
    assert len(search["items"]) >= len(recommended["items"])
    assert [i["name"] for i in watched["items"]] == ["アルファテック"]
    # 件数は絞り込みと独立（母数は常に全企業）
    for p in (recommended, search, watched):
        assert p["total_count"] == 3


def test_matching_api_uses_salary_and_holidays(session: Session, client: TestClient) -> None:
    """年収・休日も条件になる。企業側が未登録の会社は合致しない。"""
    seed_companies(session)

    # axes を空で渡して、年収・休日だけを条件にする（省略するとプロフィールの就活軸が入る）
    payload = client.post(
        "/api/matching",
        json={"salary_min": 460, "holidays_min": 130, "axes": [], "scope": "search"},
    ).json()

    # 450万のアルファテックと、年収が未登録のミュー精機は合致しない
    assert [i["name"] for i in payload["items"]] == ["ラムダソフト"]
    assert payload["items"][0]["salary_min"] == 460
    assert payload["items"][0]["holidays_per_year"] == 130


def test_matching_api_rejects_out_of_range_numbers(session: Session, client: TestClient) -> None:
    """桁を打ち間違えた年収・休日を受け付けない（変な値がマッチ率に混ざらないように）。"""
    seed_companies(session)

    assert client.post("/api/matching", json={"salary_min": 99999}).status_code == 422
    assert client.post("/api/matching", json={"holidays_min": 400}).status_code == 422


def test_matching_api_requires_a_condition(session: Session, client: TestClient) -> None:
    """条件が1つも無ければ 422。プロフィールの軸も空の場合。"""
    session.add(Company(name="テスト", domain="t.jp"))
    session.commit()

    assert client.post("/api/matching", json={}).status_code == 422


def test_matching_api_never_calls_ai(session: Session, client: TestClient) -> None:
    """AI を使うのは2箇所だけ（§2）。マッチングは Claude を1回も呼ばない。

    同じ条件で2回呼んでも結果が変わらないことも、ここで一緒に担保する。
    """
    seed_companies(session)
    body = {"job_type": "ソフトウェアエンジニア", "location": "東京", "remote_only": True}

    with patch("services.ai._get_client") as mocked:
        first = client.post("/api/matching", json=body).json()
        second = client.post("/api/matching", json=body).json()

    assert mocked.call_count == 0
    assert [(i["name"], i["rate"]) for i in first["items"]] == [
        (i["name"], i["rate"]) for i in second["items"]
    ]


def test_matching_api_reports_source(session: Session, client: TestClient) -> None:
    """取得元を返す（実データ移行後に画面で出典を出せるように。§5.10）。"""
    seed_companies(session)

    payload = client.post("/api/matching", json={"job_type": "エンジニア"}).json()

    assert payload["source"] == "seed"
