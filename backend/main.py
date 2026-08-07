"""FastAPI エントリ（docs/spec.md §3）。

起動: cd backend && uvicorn main:app --reload  → http://localhost:8000/docs

ルーターは機能ごとに routers/ に分けて、ここで include するだけにする。
他の担当者は routers/ にファイルを足して下の include_router を1行追加する。
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from db import init_db
from routers import (
    companies,
    emails,
    events,
    gmail,
    knowledge,
    profile,
    qa,
    research,
    tasks,
    today,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()  # テーブルが無ければ作る
    yield


app = FastAPI(title="ShukatsuHub API", lifespan=lifespan)

app.include_router(events.router)
app.include_router(emails.router)
app.include_router(profile.router)
app.include_router(tasks.router)
app.include_router(today.router)
app.include_router(qa.router)
app.include_router(knowledge.router)
app.include_router(research.router)
app.include_router(companies.router)
app.include_router(gmail.router)
