# GitHub 上で変更を main に反映する手順書

対象リポジトリ: `minami373-ctrl/shukatsuhub`
前提: 自分のブランチに `git push` 済みであること（コマンド手順は `git_cmm.md`）

---

## 全体の流れ

```
自分のPC          GitHub
--------          ------------------------------------
git push  ──▶  ① 自分のブランチが GitHub に上がる
                 ② Pull Request（PR）を作成
                 ③ メンバーがレビュー → 承認
                 ④ Merge ボタンで main に反映
                 ⑤ ブランチを削除
git pull  ◀──  ⑥ 手元の main を最新にする
```

**重要**: `git push` した時点では main には反映されていません。
GitHub 上で **PR を作り、Merge する** ことで初めて main に入ります。

---

## ① push できたか確認する

1. ブラウザで https://github.com/minami373-ctrl/shukatsuhub を開く
2. 左上のブランチ選択（`main ▾`）をクリックし、自分のブランチ名を選ぶ
3. 自分の変更したファイルが表示されていれば push 成功

---

## ② Pull Request を作成する

**方法A: 黄色いバナーから（push 直後はこれが一番早い）**

1. リポジトリのトップページを開く
2. 「`murata` had recent pushes」という黄色い帯の
   **`Compare & pull request`** ボタンをクリック

**方法B: Pull requests タブから**

1. 上部メニューの **`Pull requests`** タブをクリック
2. 緑の **`New pull request`** ボタンをクリック
3. 比較元・先を選ぶ（**向きを間違えないよう注意**）
   - **base**: `main` ← 反映先
   - **compare**: `murata` ← 自分のブランチ
4. 下に表示される差分（Files changed）が意図した内容か確認
5. **`Create pull request`** をクリック

**PR の書き方**

| 項目 | 書く内容 |
|---|---|
| Title | 何をしたか一文で（例: ログイン画面を追加） |
| 本文 | 目的 / 変更内容 / 動作確認したこと / レビューしてほしい点 |
| Reviewers | 右サイドバーからメンバーを指定（歯車アイコン） |
| Assignees | 自分を指定 |

本文テンプレート:

```
## 目的
ログイン機能の実装

## 変更内容
- ログインフォームを追加
- 入力バリデーションを追加

## 動作確認
- 正しいID/PWでログインできることを確認
- 空欄でエラーが出ることを確認

## レビューしてほしい点
- バリデーションの実装方法
```

6. 最後に緑の **`Create pull request`** をクリック → PR 完成

---

## ③ レビューを受ける / する

**自分の PR がレビューされたら**

- 指摘は PR の **Conversation** タブにコメントとして付く
- 修正は**手元で作業して同じブランチに push するだけ**（PR は自動更新される）

```
git switch murata
（修正する）
git add <file>
git commit -m "fix: レビュー指摘を修正"
git push
```

- 対応したコメントには返信し、**`Resolve conversation`** を押す

**他人の PR をレビューするとき**

1. `Pull requests` タブ → 対象の PR を開く
2. **`Files changed`** タブで差分を見る
3. 気になる行の左の **`+`** をクリックしてコメントを書く
4. 右上 **`Review changes`** →
   - `Comment` … 単なる意見
   - `Approve` … 承認（マージ可能になる）
   - `Request changes` … 修正が必要

---

## ④ main にマージする

PR ページ下部の表示を確認します。

| 表示 | 意味 | 対応 |
|---|---|---|
| `This branch has no conflicts` | マージ可能 | Merge して OK |
| `This branch has conflicts` | main と衝突 | 下の「衝突したとき」へ |
| `Review required` | 承認待ち | レビューを依頼する |

1. 承認が付いたら緑の **`Merge pull request`** をクリック
2. マージ方法を選ぶ（**チームで統一しておく**）
   - **Squash and merge**（推奨）… 複数コミットを1つにまとめて main に入る。履歴がきれい
   - `Create a merge commit` … コミット履歴をそのまま残す
   - `Rebase and merge` … 履歴を一直線にする
3. **`Confirm merge`** をクリック → **main に反映完了**

---

## ⑤ ブランチを削除する

1. マージ直後に表示される **`Delete branch`** ボタンをクリック
   （GitHub 上のブランチが消えるだけ。コミットは main に残っています）
2. 手元のブランチも消す場合:

```
git switch main
git pull origin main
git branch -d murata
git fetch --prune
```

※ そのブランチで作業を続けるなら削除しなくてもよい。
　 その場合も `git switch murata && git merge main` で main を取り込んでおく。

---

## ⑥ 手元を最新にする（全員が行う）

誰かの PR がマージされたら、各自これを実行して最新の main を取り込みます。

```
git switch main
git pull origin main
git switch murata
git merge main
git push
```

---

## 衝突（Conflict）したとき

GitHub 上で `This branch has conflicts that must be resolved` と出た場合、
**手元で解消するのが安全**です。

```
git switch main
git pull origin main
git switch murata
git merge main            # ここで衝突が出る
```

1. `git status` で衝突ファイルを確認
2. ファイルを開き、以下のマーカーを手で直す（マーカー行は必ず削除）

```
<<<<<<< HEAD
自分のブランチの内容
=======
main の内容
>>>>>>> main
```

3. 動作確認してから

```
git add <file>
git commit
git push
```

→ GitHub の PR ページが自動で更新され、マージ可能になります。

※ 解消をやめて元に戻したいとき: `git merge --abort`

---

## 画面の見方（用語）

| 場所 | 何ができるか |
|---|---|
| `Code` タブ | ファイル閲覧。左上でブランチを切り替え |
| `Issues` タブ | やることリスト・バグ報告の管理 |
| `Pull requests` タブ | PR の作成・レビュー・マージ |
| PR の `Conversation` | コメントのやり取り |
| PR の `Commits` | この PR に含まれるコミット一覧 |
| PR の `Files changed` | 差分（レビューはここで行う） |
| `Insights` > `Network` | ブランチの分岐・合流を図で確認 |

---

## やってはいけないこと

- main に直接 commit / push する（GitHub 上でファイルを直接編集するのも同じ）
- PR の base と compare を逆にする（main の内容を自分のブランチに入れてしまう）
- 差分を確認せずにマージする
- 他人の PR を本人の承認なしにマージする
- `.env` など秘密情報をコミットする（一度 push すると履歴に残る）
