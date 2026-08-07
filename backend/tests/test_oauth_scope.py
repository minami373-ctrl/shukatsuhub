"""OAuth のスコープ検査を緩める共有ヘルパー（services/oauth_scope.py）。

`OAUTHLIB_RELAX_TOKEN_SCOPE` は**プロセス全体で共有される環境変数**なので、
カレンダーと Gmail のコールバックが同時に走っても互いの後始末が干渉しないこと、
抜けたら必ず元へ戻ることを確かめる（code-reviewer の指摘への回帰テスト）。
"""

import os
import threading

from services import oauth_scope

KEY = oauth_scope.ENV_KEY


def test_sets_flag_inside_and_restores_after() -> None:
    """中では立っていて、抜けたら元の「未設定」に戻る。"""
    os.environ.pop(KEY, None)

    with oauth_scope.relaxed_token_scope():
        assert os.environ[KEY] == "1"

    assert KEY not in os.environ


def test_restores_previous_value() -> None:
    """元から値があったら、その値に戻す（消してしまわない）。"""
    os.environ[KEY] = "0"
    try:
        with oauth_scope.relaxed_token_scope():
            assert os.environ[KEY] == "1"
        assert os.environ[KEY] == "0"
    finally:
        os.environ.pop(KEY, None)


def test_restores_even_when_body_raises() -> None:
    """`fetch_token` が例外を投げても環境変数を残さない。"""
    os.environ.pop(KEY, None)

    try:
        with oauth_scope.relaxed_token_scope():
            raise RuntimeError("fetch_token が失敗した")
    except RuntimeError:
        pass

    assert KEY not in os.environ


def test_concurrent_use_never_unsets_flag_mid_exchange() -> None:
    """同時に使っても、片方の後始末がもう片方の実行中に効かないこと。

    FastAPI は同期エンドポイントをスレッドプールで動かすため、カレンダーと Gmail の
    コールバックが並行しうる。ロックが無いと、中にいるのにフラグが消える瞬間ができる。
    """
    os.environ.pop(KEY, None)
    observed: list[str | None] = []
    barrier = threading.Barrier(2)

    def exchange() -> None:
        barrier.wait()  # 2スレッドの開始をそろえて競合しやすくする
        for _ in range(200):
            with oauth_scope.relaxed_token_scope():
                # 「中にいる間」に見えた値を記録する。1 以外が混じったら競合している
                observed.append(os.environ.get(KEY))

    threads = [threading.Thread(target=exchange) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert observed  # 実際に回っている
    assert set(observed) == {"1"}
    assert KEY not in os.environ  # 最後は必ず元に戻る
