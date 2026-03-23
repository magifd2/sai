# SAI — Slack AI コマンドインタープリタ

> 🇬🇧 English version: [README.md](README.md)

チームの会話を記憶し、過去のやりとりを根拠にした質問回答と、自然言語によるコマンド実行ができる Slack ボットです。ローカルLLMで完全に動作します。

---

## SAI にできること

### 1. 会話履歴から質問に答える

SAIは参加しているチャンネルに投稿されたすべてのメッセージを自動的に記憶します。@メンションされると、関連する過去の会話を検索して回答の根拠として使用します。

**例: 過去の発言を聞く**

```
Alice  │ @SAI Bobがデプロイのスケジュールについて何か言ってたっけ？
───────┼──────────────────────────────────────────────────────────────────
SAI    │ 先週火曜日の会話によると、Bobは金曜日の14:00 JSTにデプロイを予定
       │ していると言っていました。ただ、木曜日までにステージングのテストが
       │ 通らなければ遅れる可能性があるとも述べていました。
```

**例: 特定のトピックについて聞く**

```
Alice  │ @SAI Redisのマイグレーションについて誰か議論してた？
───────┼──────────────────────────────────────────────────────────────────
SAI    │ はい。月曜日にCarolが話題にしていました。25日のメンテナンス時間中に
       │ Redis 6 から Redis 7 への移行を提案していました。Daveが破壊的変更を
       │ 先に確認したいと返答し、週末までにサマリーを共有するとのことでした。
```

**例: 複数人の意見をまとめる**

```
Bob    │ @SAI 新しいAPIの認証方式について、みんなどんな意見だった？
───────┼──────────────────────────────────────────────────────────────────
SAI    │ 先週の議論では主に3つの意見が出ていました：
       │
       │ • Alice: JWTベースの実装を推奨。既存ライブラリが豊富なため。
       │ • Carol: OAuth 2.0を使うべきと主張。将来的な外部連携を見越して。
       │ • Dave: 実装コストを考えるとAPIキー認証で十分という立場。
       │
       │ 最終的にはAliceの案を叩き台にして水曜日に再議論することになった
       │ ようです。
```

---

### 2. 自然言語でコマンドを実行する

事前に登録したシェルスクリプトを自然言語のリクエストで実行できます。コマンド名を覚える必要はありません。やりたいことを言葉で伝えるだけです。

**例: サーバー状態確認**

```
Bob    │ @SAI サーバーの状態を教えて
───────┼──────────────────────────────────────────────────────────────────
SAI    │ ✅ `server_status`:
       │ ```
       │ Hostname : prod-server-01
       │ Uptime   : 14日 3時間 稼働中
       │ Load avg : 0.42, 0.38, 0.35
       │
       │ メモリ:
       │ 合計   使用中   空き
       │ 32Gi    12Gi   18Gi
       │ ```
```

**例: ディスク使用量確認**

```
Carol  │ @SAI /var/logのディスク残量どのくらいある？
───────┼──────────────────────────────────────────────────────────────────
SAI    │ ✅ `disk_usage`:
       │ ```
       │ ファイルシステム  容量  使用  残り  使用率
       │ /dev/sda1          50G   31G   19G     62%
       │
       │ 上位ディレクトリ:
       │ 8.2G  /var/log/nginx
       │ 4.1G  /var/log/app
       │ 1.3G  /var/log/syslog
       │ ```
```

**例: 疎通確認**

```
Dave   │ @SAI google.comに疎通確認して
───────┼──────────────────────────────────────────────────────────────────
SAI    │ ✅ `ping_host`:
       │ ```
       │ PING google.com: 4パケット送信、損失0%
       │ min/avg/max = 4.2/4.8/5.3 ms
       │ ```
```

**例: コマンドが見つからない場合**

```
Eve    │ @SAI データベースをバックアップして
───────┼──────────────────────────────────────────────────────────────────
SAI    │ 「データベースのバックアップ」に対応するコマンドは現在登録されて
       │ いません。過去の会話の中でバックアップに関連する情報があれば
       │ お伝えできます。コマンドの追加については管理者にお問い合わせ
       │ ください。
```

---

### 3. 重要なメッセージをピン留めして永続記憶に残す

任意のメッセージに 📌 のリアクションを付けると（⭐ 🔖 📝 も可）、そのメッセージは**ピン留め記憶**として保存されます。ピン留めされた記憶は要約されず、アーカイブされることもなく、いつまでも参照できます。

**例: 重要な決定事項をピン留め**

```
Eve    │ 本番DBのパスワードローテーションは12月1日に実施予定。
       │ 全サービスは11月30日17:00までに資格情報を更新すること。
       │
       │  [📌 リアクション付与]
       │
 ── 数週間後 ──
       │
Alice  │ @SAI DBのパスワードローテーションはいつだっけ？
───────┼──────────────────────────────────────────────────────────────────
SAI    │ 本番DBのパスワードローテーションは12月1日です。
       │ 全サービスは11月30日17:00までに資格情報の更新が必要です。
```

> 📌 ピン留めのリアクションは設定で変更できます（デフォルト: `pushpin`, `star`, `bookmark`, `memo`）

---

### 4. スマートな記憶管理と自動忘却

SAIのメモリは自動的に管理されます。通常のメッセージは以下のライフサイクルをたどります：

```
HOT    (24時間以内)   原文をそのまま保持 — すべての詳細を記憶
  ↓
WARM   (1〜7日)       LLMによる要約 — 重要なポイントのみ残す
  ↓
COLD   (7日以降)      アーカイブ待ち状態
  ↓
ARCHIVE              アーカイブテーブルへ移動、通常検索から除外

PINNED               リアクションによる永続化 — 永遠に記憶
```

これにより、最近の出来事は細かく、古い出来事は要点だけを記憶しながら、LLMのコンテキストウィンドウに収まるようにメモリを管理します。

---

### 5. スレッド継続

SAIがすでに参加しているスレッドへの返信は、改めて @メンションしなくても会話が続きます。親メッセージがメモリに存在することを検出して、自動的にメンションとして処理します。

---

### SAI にできないこと

- 自分からメッセージを送ることはしません（@メンションされたときだけ返答します）
- 任意のシェルコマンドは実行しません（`scripts/commands.json` に登録済みのスクリプトのみ実行可能）
- インターネットには接続しません（ローカルLLMを使用）

---

## 必要なもの

- Python 3.12+
- [uv](https://github.com/astral-sh/uv)
- [LM Studio](https://lmstudio.ai/)（またはOpenAI互換のローカルAPI）
- Socket Modeが有効なSlackアプリ — [docs/slack-setup.md](docs/slack-setup.md) を参照

---

## クイックスタート

```bash
# 1. 依存関係のインストール
uv sync

# 2. 認証情報の設定
cp .env.example .env
# .env に SAI_SLACK_BOT_TOKEN と SAI_SLACK_APP_TOKEN を記入

# 3. （任意）設定ファイルのカスタマイズ
cp sai.toml.example sai.toml
# sai.toml を編集 — workspace_name、response_language、モデル名などを設定
# sai.toml は `uv run sai start` を実行したカレントディレクトリから読み込まれます

# 4. データベースの初期化
uv run sai init-db

# 5. LLMへの接続確認
uv run sai check

# 6. 起動
uv run sai start
```

---

## 設定

設定は `sai.toml`（デフォルトはカレントディレクトリ、`--config` で変更可）と `SAI_*` 環境変数から読み込まれます。環境変数が設定ファイルより優先されます。

| 環境変数 | デフォルト | 説明 |
|---------|-----------|------|
| `SAI_SLACK_BOT_TOKEN` | *(必須)* | Slack ボットトークン (`xoxb-...`) |
| `SAI_SLACK_APP_TOKEN` | *(必須)* | Socket Mode アプリトークン (`xapp-...`) |
| `SAI_SLACK_RESPONSE_LANGUAGE` | *(自動検出)* | ボットの返答言語（例: `Japanese`、`English`） |
| `SAI_LLM_BASE_URL` | `http://localhost:1234/v1` | LM Studio エンドポイント |
| `SAI_LLM_API_KEY` | `lm-studio` | APIキー |
| `SAI_LLM_MODEL` | `openai/gpt-oss-20b` | チャットモデル |
| `SAI_LLM_EMBED_MODEL` | `text-embedding-nomic-embed-text-v1.5` | 埋め込みモデル |
| `SAI_LLM_MAX_CONCURRENT_REQUESTS` | `4` | LLM同時リクエスト数の上限 |
| `SAI_MEMORY_PIN_REACTIONS` | `pushpin,star,bookmark,memo` | ピン留めに使うリアクション名 |
| `SAI_LOG_LEVEL` | `INFO` | ログレベル |

全設定項目（説明・デフォルト値付き）は [`sai.toml.example`](sai.toml.example) を参照してください。
シークレット（トークン、APIキー）は `.env` に記載できます — [`.env.example`](.env.example) を参照。

---

## カスタムコマンドの追加

**1.** `scripts/` にシェルスクリプトを作成します。パラメータは標準入力からJSONで受け取ります：

```bash
#!/usr/bin/env bash
# scripts/my_command.sh
params=$(cat)
target=$(echo "$params" | python3 -c "
import json, sys
print(json.load(sys.stdin)['args']['target'])
")
echo "$target の確認結果："
# ... 実際の処理
```

**2.** `scripts/commands.json` に登録します：

```json
{
  "name": "my_command",
  "description": "指定されたサービスの死活監視を実行する",
  "script_path": "my_command.sh",
  "required_args": ["target"],
  "max_runtime_seconds": 30
}
```

「nginxの状態を確認して」のような自然言語リクエストが自動的にこのコマンドにマッピングされます。

---

## セキュリティ

- **ACL** — SlackユーザーIDによるホワイトリスト/ブラックリスト制御
- **レートリミット** — ユーザーごとのスライディングウィンドウ（分・時間単位で設定可能）
- **プロンプトインジェクション対策** — リクエストごとのnonce XMLカプセル化、入力サニタイザー、ロール分離
- **コマンドサンドボックス** — 登録済みスクリプトのみ実行可能、パラメータはstdin JSON経由（CLIアーグメント不使用）、リソース制限あり
- **レスポンスサニタイズ** — `<think>` / `[THINK]` / `<reasoning>` などのモデル内部タグをSlack投稿前に除去

詳細は [docs/development-rules.md](docs/development-rules.md) を参照してください。

---

## メモリのモニタリング

SAI停止中に、CLIからメモリデータベースの内容を確認できます：

```bash
# 状態別レコード件数
uv run sai memory stats

# レコード一覧（--state / --user / --channel / --limit でフィルタ可能）
uv run sai memory list
uv run sai memory list --state pinned
uv run sai memory list --channel C09BLA40DFY --limit 50

# 1件の詳細表示（list の ID 列の先頭数文字でもOK）
uv run sai memory show <id-prefix>
```

メモリの状態遷移：`hot`（24時間以内、原文）→ `warm`（1〜7日、要約）→ `cold` → アーカイブ。`pinned` は永続。

---

## テストの実行

```bash
uv run pytest
uv run pytest --cov=sai --cov-report=term-missing
```

---

## プロジェクト構成

```
sai/
├── config/              # 設定スキーマとローダー
├── sai/
│   ├── app.py           # アプリケーション統合 — イベント処理パイプライン
│   ├── db/              # DuckDB + VSS リポジトリ層（非同期インターフェース）
│   ├── llm/             # LLMクライアント、プロンプト、nonce、サニタイザー
│   ├── memory/          # メモリモデル、ライフサイクル状態機械、スケジューラー
│   ├── rag/             # 埋め込み生成と検索
│   ├── security/        # ACL、レートリミット、インジェクション検出
│   ├── slack/           # Socket Modeハンドラー、イベントパーサー、キャッシュ
│   ├── commands/        # レジストリ、NLインタープリタ、エグゼキューター
│   └── utils/           # ログ、時刻ユーティリティ、ID生成
├── scripts/             # コマンドスクリプト + commands.json マニフェスト
├── tests/               # ユニットテスト・統合テスト
└── docs/                # セットアップガイド、アーキテクチャ、開発ルール
```

---

## ドキュメント

| ドキュメント | 内容 |
|------------|------|
| [docs/slack-setup.ja.md](docs/slack-setup.ja.md) / [en](docs/slack-setup.md) | Slackアプリセットアップ手順（ステップバイステップ） |
| [docs/development-rules.ja.md](docs/development-rules.ja.md) / [en](docs/development-rules.md) | コーディング規約、セキュリティルール、Git規約 |
