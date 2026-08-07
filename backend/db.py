"""DB エンジンとセッション（docs/spec.md §3）。

SQLite 1ファイル（backend/app.db）。ここ以外で create_engine しない。
"""

from collections.abc import Generator
from pathlib import Path

from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine

DB_PATH = Path(__file__).resolve().parent / "app.db"

#: 書き込みロックの待ち時間（ミリ秒）。既定の5秒では、同期のような
#: 少し長い書き込みと画面のポーリングが重なったときに諦めてしまう。
BUSY_TIMEOUT_MS = 30_000

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    # FastAPI は複数スレッドから触るため SQLite の同一スレッド制約を外す
    connect_args={"check_same_thread": False},
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record) -> None:
    """接続のたびに WAL モードと待ち時間を設定する。

    既定のロールバックジャーナルでは**書き込み中に読み取りができない**ため、
    Gmail 同期のような少し長い書き込みと、画面が定期的に投げる GET が衝突して
    `sqlite3.OperationalError: database is locked` になった（実測で確認）。
    WAL なら読み取りと書き込みが同時に走れる。

    `journal_mode` はファイル DB に永続する設定なので1回効けばよいが、
    接続ごとに実行しても副作用はない。`busy_timeout` は接続ごとの設定なので毎回必要。
    ここで engine を差し替えないのは、テストが `conftest.py` で別の
    インメモリ engine を作っており、そちらに影響を出さないため。
    """
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    finally:
        cursor.close()


def init_db() -> None:
    """models.py の全テーブルを作成する（既存テーブルはそのまま）。"""
    # import しないと SQLModel.metadata にテーブルが登録されない
    import models  # noqa: F401

    SQLModel.metadata.create_all(engine)


def get_session() -> Generator[Session, None, None]:
    """FastAPI の依存性注入用。リクエストごとにセッションを開いて閉じる。"""
    with Session(engine) as session:
        yield session
