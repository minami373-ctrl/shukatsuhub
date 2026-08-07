"""pytest 共通フィクスチャ。

このファイルが backend/ にあることで pytest が backend/ を import パスに追加する
（`from main import app` が通る）。
"""

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import models  # noqa: F401  metadata にテーブルを登録するため必要
from db import get_session
from main import app


@pytest.fixture(name="session")
def session_fixture() -> Generator[Session, None, None]:
    """テストごとに使い捨てのインメモリ DB を作る（app.db を汚さない）。"""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,  # インメモリ DB を全接続で共有する
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture(name="client")
def client_fixture(session: Session) -> Generator[TestClient, None, None]:
    """API 経由のテスト用。DB セッションを上のインメモリ DB に差し替える。"""

    def get_session_override() -> Session:
        return session

    app.dependency_overrides[get_session] = get_session_override
    # あえて with を使わない（lifespan の init_db が走って app.db が作られるのを避ける）
    yield TestClient(app)
    app.dependency_overrides.clear()
