# 共有したくないファイルの置き場所と開き方

自分だけが使うメモ・実験用スクリプト・動作確認用データを、
GitHub に上げずにリポジトリ内に置いておくための設定です。
**この設定はチームには共有されません**（自分の PC だけに効きます）。

---

## 1. 置き場所：`_local/` フォルダ

```
C:\Users\stuser00428\project\internship-2026-team-a\_local\
```

すでに作成・除外設定済みです。ここに入れたファイルは

- `git status` に出てこない
- `git add .` しても追加されない
- `git push` しても GitHub に上がらない
- 他のメンバーの環境には存在しない

自由にメモやテストコードを置いてください。

**注意**: このフォルダは Git で管理されていないため、**バックアップされません**。
PC が壊れると消えます。残したいものは別途保存してください。

---

## 2. 開き方

### エクスプローラーで開く

エクスプローラーのアドレスバーに貼り付けて Enter:

```
C:\Users\stuser00428\project\internship-2026-team-a\_local
```

または VS Code のターミナルで:

```powershell
explorer _local
```

### VS Code で開く

左の Explorer（ファイル一覧）に `_local` フォルダが表示されているので、
普通にクリックして開けます。新規ファイルもそこに作れます。

ターミナルから直接開く場合:

```powershell
code _local\memo.md
```

---

## 3. 除外設定ファイルの場所と開き方

除外ルールは以下のファイルに書かれています。

```
C:\Users\stuser00428\project\internship-2026-team-a\.git\info\exclude
```

`.git` は隠しフォルダで、**VS Code の Explorer には既定で表示されません**。
そのためターミナルから開きます。

### VS Code で開く

```powershell
code .git\info\exclude
```

### メモ帳で開く

```powershell
notepad .git\info\exclude
```

### エクスプローラーで開く（隠しフォルダを見せる）

エクスプローラー上部の **表示** → **表示** → **隠しファイル** にチェックを入れると
`.git` フォルダが見えるようになり、`.git\info\exclude` を辿れます。

現在の中身（末尾）:

```
# ==== 個人用（自分だけ無視する。チームには共有されない）====
_local/
```

---

## 4. 除外するものを追加したいとき

`.git\info\exclude` に1行ずつ書き足します。書式は `.gitignore` と同じです。

```
_local/          フォルダごと除外
memo.txt         ファイル名を指定
tmp_*.py         tmp_ で始まる .py ファイル
*.log            拡張子で指定
scratch/         別の作業用フォルダ
```

ターミナルから追記する場合:

```powershell
Add-Content .git\info\exclude "memo.txt"
```

---

## 5. `.gitignore` との使い分け

| | `.git\info\exclude` | `.gitignore` |
|---|---|---|
| 効く範囲 | 自分の PC だけ | チーム全員 |
| GitHub に上がるか | 上がらない | 上がる（コミットする） |
| 使うもの | 自分のメモ・実験ファイル | `node_modules/` `.env` `*.log` `dist/` など全員に不要なもの |

**チーム全員に不要なもの**は `.gitignore` に書いて共有します。
**自分だけのもの**は `.git\info\exclude` に書きます。

---

## 6. 確認コマンド

```powershell
git status                       # 除外されていれば出てこない
git status --ignored             # 除外されているファイルも含めて表示
git check-ignore -v _local\memo.md   # どのルールで除外されたか表示
```

`git check-ignore` の出力例（これが出れば除外できています）:

```
.git/info/exclude:9:_local/     _local/memo.md
```

何も表示されない場合は除外できていません。

---

## 7. よくあるトラブル

### 除外設定を書いたのに `git status` に出てくる

**すでにコミット済みのファイルには ignore が効きません。**
追跡を外してください（ファイル自体は消えません）。

```powershell
git rm --cached <ファイル名>
git commit -m "chore: 追跡対象から除外"
```

### 秘密情報（`.env` など）を push してしまった

**履歴に残るため、ファイルを消しただけでは対処になりません。**
すぐにそのキー・パスワードを無効化して再発行してください。
その上でチームに共有し、履歴からの削除が必要か相談してください。

### `.env` をチームで共有したい

`.env` 自体はコミットせず、キー名だけ書いた `.env.example` をコミットします。
値は口頭や別の安全な手段で共有します。
