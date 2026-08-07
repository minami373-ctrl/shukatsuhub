"""企業マッチング（docs/spec.md §5.9）。純関数。DB もネットワークも触らない。

**AI は使わない**（§2「AI を使うのは2箇所だけ」）。同じ入力なら常に同じマッチ率になる。
LLM に出させると実行のたびに値が変わり、ユーザーにも発表でも説明できなくなるため。

マッチ率 = 満たした重みの合計 ÷ 指定された条件の重みの合計。
会社側の項目が空なら「合致しない」として扱う（推測で埋めない。CLAUDE.md §E）。
"""

from dataclasses import dataclass, field

#: 条件ごとの重み（§5.9）。職種を最も重くするのは、就活生が最初に絞る軸だから。
#: 年収を勤務地と同格にするのは、就活生が実際に強く見る条件だから
WEIGHT_JOB_TYPE = 3
WEIGHT_LOCATION = 2
WEIGHT_SALARY = 2
WEIGHT_HOLIDAYS = 1
WEIGHT_REMOTE = 1
WEIGHT_AXIS = 1


@dataclass(frozen=True)
class MatchCriteria:
    """画面のテンプレ質問の回答。空・None の項目は条件に数えない。"""

    job_type: str | None = None
    location: str | None = None
    #: 「リモート勤務は必須？」が true のときだけ条件になる
    remote_only: bool = False
    #: 希望年収の下限（万円）。None なら条件に数えない
    salary_min: int | None = None
    #: 希望する年間休日の下限（日）。None なら条件に数えない
    holidays_min: int | None = None
    #: 就活軸。プロフィールの job_axis 由来。1つにつき重み 1
    axes: tuple[str, ...] = ()

    @property
    def has_any(self) -> bool:
        return bool(
            self.job_type
            or self.location
            or self.remote_only
            or self.salary_min is not None
            or self.holidays_min is not None
            or self.axes
        )


@dataclass(frozen=True)
class MatchTarget:
    """照合される企業側の値。Company からそのまま作る。"""

    job_type: str | None = None
    location: str | None = None
    remote_ok: bool = False
    #: 想定年収の下限（万円）。未登録は None＝合致しない
    salary_min: int | None = None
    #: 年間休日数（日）。未登録は None＝合致しない
    holidays_per_year: int | None = None
    #: Company.tags（カンマ区切り）
    tags: str | None = None


@dataclass
class MatchResult:
    #: 0〜100 の整数
    rate: int
    #: 合致した条件だけを文言にしたもの。合致しなかった条件は入れない
    reasons: list[str] = field(default_factory=list)
    matched_axes: list[str] = field(default_factory=list)


def _norm(value: str | None) -> str:
    """前後の空白を落として小文字にする。全角空白も落とす。"""
    return (value or "").strip().strip("　").lower()


def split_csv(value: str | None) -> list[str]:
    """カンマ区切りを配列にする。空の要素は捨てる。就活軸とタグの両方で使う。"""
    return [part.strip().strip("　") for part in (value or "").split(",") if part.strip()]


def _round_half_up(value: float) -> int:
    """半数切り上げ。Python の round() は偶数丸めなので使わない（§5.3 と同じ理由）。"""
    return int(value + 0.5)


def match(criteria: MatchCriteria, target: MatchTarget) -> MatchResult:
    """1社ぶんのマッチ率と理由を返す（§5.9）。

    指定された条件が0個なら 0%。分母が0になるうえ、条件なしで「100%一致」と
    出すのは意味がないため。
    """
    if not criteria.has_any:
        return MatchResult(rate=0)

    total = 0
    got = 0
    reasons: list[str] = []
    matched_axes: list[str] = []

    if criteria.job_type:
        total += WEIGHT_JOB_TYPE
        # 表記ゆれ（「SE」「ソフトウェアエンジニア」）に耐えるため部分一致にする
        if _norm(criteria.job_type) and _norm(criteria.job_type) in _norm(target.job_type):
            got += WEIGHT_JOB_TYPE
            reasons.append(f"職種が一致：{target.job_type}")

    if criteria.location:
        total += WEIGHT_LOCATION
        if _norm(criteria.location) and _norm(criteria.location) in _norm(target.location):
            got += WEIGHT_LOCATION
            reasons.append(f"勤務地が一致：{target.location}")

    if criteria.salary_min is not None:
        total += WEIGHT_SALARY
        # 企業側が未登録（None）なら合致しない。0 万円として扱って落とすのも推測になる
        if target.salary_min is not None and target.salary_min >= criteria.salary_min:
            got += WEIGHT_SALARY
            reasons.append(f"想定年収が希望以上：{target.salary_min}万円")

    if criteria.holidays_min is not None:
        total += WEIGHT_HOLIDAYS
        if (
            target.holidays_per_year is not None
            and target.holidays_per_year >= criteria.holidays_min
        ):
            got += WEIGHT_HOLIDAYS
            reasons.append(f"年間休日が希望以上：{target.holidays_per_year}日")

    if criteria.remote_only:
        total += WEIGHT_REMOTE
        if target.remote_ok:
            got += WEIGHT_REMOTE
            reasons.append("リモート勤務が可能")

    if criteria.axes:
        tags = {_norm(t) for t in split_csv(target.tags)}
        for axis in criteria.axes:
            total += WEIGHT_AXIS
            if _norm(axis) and _norm(axis) in tags:
                got += WEIGHT_AXIS
                matched_axes.append(axis)
                reasons.append(f"就活軸「{axis}」に一致")

    rate = _round_half_up(got / total * 100) if total else 0
    return MatchResult(rate=rate, reasons=reasons, matched_axes=matched_axes)
