"""OAuth のトークン交換中だけ oauthlib のスコープ検査を緩めるための共有ヘルパー。

`services/gcal.py`（カレンダー）と `services/gmail.py`（Gmail）の両方が使う。

**なぜ緩める必要があるか**
同じ Google クライアント ID で2つの連携を持つと、片方を認可済みの状態でもう片方を認可したとき、
Google が「過去に許可済みのスコープ」を合わせて返す。要求したスコープと戻りが食い違うため、
oauthlib が `Warning: Scope has changed from ... to ...` を投げて認可を失敗させる（実測で確認）。

**なぜ共有モジュールに置くか**
緩めるスイッチが `OAUTHLIB_RELAX_TOKEN_SCOPE` という**プロセス全体で共有される環境変数**だから。
FastAPI は同期の `def` エンドポイントをスレッドプールで動かすので、カレンダーと Gmail の
コールバックがほぼ同時に来ると、片方の後始末がもう片方の `fetch_token` 中に走り、
検査が意図せず復活しうる。各モジュールに別々のロックを置いても直列化できないため、
**ロックと環境変数の操作をここ1箇所に集約する。**

緩めても**要求より広い権限が付く方向にしか動かない**（Google は要求していないスコープを
新たに付与しない）。実際に付与された値は呼び出し側が検証してから保存する。
"""

import contextlib
import os
import threading

#: 環境変数はプロセス共有なので、トークン交換を直列化して後始末の取りこぼしを防ぐ。
_LOCK = threading.Lock()

ENV_KEY = "OAUTHLIB_RELAX_TOKEN_SCOPE"


@contextlib.contextmanager
def relaxed_token_scope():
    """`fetch_token()` の呼び出しをこれで囲む。

    ロックを取っている間だけ環境変数を立て、抜けるときに必ず元へ戻す。
    複数の連携が同時に認可されても、互いの後始末が干渉しない。
    """
    with _LOCK:
        previous = os.environ.get(ENV_KEY)
        os.environ[ENV_KEY] = "1"
        try:
            yield
        finally:
            if previous is None:
                os.environ.pop(ENV_KEY, None)
            else:
                os.environ[ENV_KEY] = previous
