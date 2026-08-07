# 開発環境の作り方（Windows）

チーム全員が同じ環境で動かすための手順。所要 15 分程度。
仕様は `docs/spec.md` §3「技術スタック」に従う。

## 1. 必要なもの

| ソフト | バージョン | 確認コマンド |
|---|---|---|
| Python | 3.11 | `python --version` → `Python 3.11.x` |
| Node.js | 20 以上（LTS） | `node --version` |
| Git | 任意 | `git --version` |

インストールは PowerShell で winget を使うのが早い。

```powershell
winget install --id Python.Python.3.11 -e --accept-package-agreements --accept-source-agreements
winget install --id OpenJS.NodeJS.LTS -e --accept-package-agreements --accept-source-agreements
```

**インストール後は PowerShell（と VS Code）を開き直す。** PATH の変更は既に開いている
ターミナルには反映されない。`python --version` が `Python 3.11.x` を返せば成功。

> `python` と打っても何も起きない / Microsoft Store が開く場合は、
> Windows の「アプリ実行エイリアス」の `python.exe` を OFF にする
> （設定 → アプリ → アプリの詳細設定 → アプリ実行エイリアス）。

## 2. リポジトリを取得する

```powershell
git clone https://github.com/minami373-ctrl/shukatsuhub.git
cd shukatsuhub
```

## 3. バックエンド（FastAPI + SQLite）

```powershell
cd backend
pip install fastapi uvicorn sqlmodel python-dotenv pytest httpx anthropic
python -m seed.load                  # seed JSON を SQLite に投入（毎回作り直す）
uvicorn main:app --reload            # http://localhost:8000/docs で API を確認
```

別のターミナルでテスト:

```powershell
cd backend
python -m pytest -q                  # AI はモックなので ANTHROPIC_API_KEY 不要
```

`pip` が見つからない場合は `python -m pip install ...` と打つ。

## 4. フロントエンド（React + Vite）

```powershell
cd frontend
npm install
npm run dev                          # http://localhost:5173
npm run test                         # Vitest
```

バックエンドを起動した状態で `http://localhost:5173/calendar` を開き、
`同期` を押すと予定が表示される（`/api` は Vite が 8000 番へ転送する）。

## 5. Claude API キー（任意・AI 機能を試すときだけ）

```powershell
Copy-Item .env.example .env
# .env を開いて ANTHROPIC_API_KEY= に自分のキーを貼る
```

**`.env` はコミットしない**（`.gitignore` 済み）。キーが無くてもアプリは動く
（メール分類は `確認`、想定問答はテンプレにフォールバックする）。

## 6. 動作確認チェックリスト

- [ ] `python --version` が `3.11.x`
- [ ] `node --version` が `v20` 以上
- [ ] `cd backend; python -m pytest -q` が全て通る
- [ ] `uvicorn main:app --reload` で `http://localhost:8000/docs` が開く
- [ ] `cd frontend; npm run test` が全て通る
- [ ] `npm run dev` で `http://localhost:5173/calendar` が開き、`同期` で予定が出る
- [ ] ブラウザを縦に狭めても**スクロールバーが出ない**（1画面完結）

## つまずいたとき

| 症状 | 対処 |
|---|---|
| `python` が反応しない | ターミナルを開き直す。アプリ実行エイリアスを OFF にする |
| `pip` の警告 `Scripts is not on PATH` | 無視して良い（`python -m pip` / `python -m pytest` で使う） |
| `npm install` が固まる | 一度 Ctrl+C → `npm cache clean --force` → 再実行 |
| フロントで予定が出ない | バックエンド（8000番）が起動しているか、`同期` を押したかを確認 |
| `/api` が 404 | `frontend/vite.config.ts` の proxy 設定が効いているか、`npm run dev` を再起動 |

## 既に app.db を作ってある人向けのマイグレーション

`docs/spec.md` §6 にカラムを足したとき、**既存の `backend/app.db` には自動で反映されない**
（SQLModel の `create_all` はテーブルを作るだけで、既にあるテーブルを変更しない）。
`no such column` のエラーが出たら、下のように**追加だけ**を実行する。

`DROP TABLE` や `python -m seed.load` の作り直しはしない。他の担当者が画面から
保存したデータ（プロフィールなど）まで消えるため（CLAUDE.md §0-⑥）。

```bash
cd backend
python -c "import sqlite3; c=sqlite3.connect('app.db'); c.execute(\"ALTER TABLE task ADD COLUMN priority VARCHAR NOT NULL DEFAULT '中'\"); c.commit()"
```

| 日付 | 追加したもの | コマンド |
|---|---|---|
| 2026-08-04 | `task.priority`（重要度・高/中/低・既定「中」） | `ALTER TABLE task ADD COLUMN priority VARCHAR NOT NULL DEFAULT '中'` |
| 2026-08-04 | `company.stage`（選考段階・既定「気になる」） | `ALTER TABLE company ADD COLUMN stage VARCHAR NOT NULL DEFAULT '気になる'` |
| 2026-08-05 | `company.job_type` / `location` / `remote_ok`（マッチング用） | `ALTER TABLE company ADD COLUMN job_type VARCHAR` ／ `ALTER TABLE company ADD COLUMN location VARCHAR` ／ `ALTER TABLE company ADD COLUMN remote_ok BOOLEAN NOT NULL DEFAULT 0` |
| 2026-08-05 | `company.salary_min` / `holidays_per_year`（マッチング用。上の3列と同時に足りていないことがある） | `ALTER TABLE company ADD COLUMN salary_min INTEGER` ／ `ALTER TABLE company ADD COLUMN holidays_per_year INTEGER` |
| 2026-08-06 | `email.external_id`（Gmail 実連携の upsert キー。**`feature/gmail` を取り込んだ人だけ**） | `ALTER TABLE email ADD COLUMN external_id VARCHAR` ／ `CREATE UNIQUE INDEX ix_email_external_id ON email (external_id)` |
| 2026-08-04 | `oauthtoken.code_verifier`（Google カレンダー実連携。**`feature/calendar-suggest` を取り込んだ人だけ**） | `ALTER TABLE oauthtoken ADD COLUMN code_verifier VARCHAR` |

`company` の5列は `/companies` のマッチングで使う。`job_type` の3列だけ足して
`salary_min` / `holidays_per_year` を忘れると、`/api/emails` まで
`no such column: company.job_type` の形で 500 になる（企業を逆引きするため）。**5列まとめて足す。**

`email.external_id` は Gmail 実連携のブランチを取り込んだ場合だけ必要。
`no such column: email.external_id` で落ちたら実行する。seed 由来のメールは `null` のままでよい
（`UNIQUE` 制約は SQLite では `null` を重複と見なさない）。

`company` の3列を足したあとは `python -m seed.load` を実行すると、
拡充した `seed/companies.json`（17社・職種と勤務地つき）が入ってマッチングを試せる。
**`seed.load` は Email / Company / QA / Task を入れ替える**ので、画面から追加したデータは消える。
Gmail 実連携で取り込んだメールも消えるが、これは `同期` を押せば戻る。

`oauthtoken` の行は Google カレンダー実連携のブランチを取り込んだ場合だけ必要。
`no such column: oauthtoken.code_verifier` で落ちたら実行する。
まだ main にはマージされていないので、main しか見ていない人には `oauthtoken` テーブル自体が無い。
