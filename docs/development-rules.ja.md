# SAI 開発ルール

> 🇬🇧 English version: [development-rules.md](development-rules.md)

このドキュメントはSAIプロジェクトにおける開発規約・ルールを定義します。
機能追加・変更時は必ずこのドキュメントも更新してください。

---

## 1. 言語・環境

| 項目 | 規約 |
|------|------|
| 言語 | Python 3.12+ |
| 仮想環境 | uv（`uv run` 経由で実行） |
| パッケージ管理 | `pyproject.toml` + `uv.lock` |
| 設定 | `sai.toml` + 環境変数（`SAI_` プレフィックス） |

---

## 2. コーディング規約

### 型アノテーション
- 全パブリック関数・メソッドに型アノテーションを付ける
- データモデルはすべて Pydantic v2 の `BaseModel` を使う
- `dict` をモジュール境界をまたいで渡さない

### 非同期
- イベントループをブロックしない。DB・ファイルIO は `asyncio.to_thread()` 経由（`sai/db` の `BaseRepository` が提供）
- 外部HTTPは `httpx.AsyncClient` を使う
- 呼び出し側は async/await のみ使う（DB内部の同期処理を意識しない）

### データベースアクセス
- DuckDB への直接アクセスは `sai/db/` モジュールのみ許可
- 生SQLは `sai/db/repositories/` 内のみに書く
- SQLは必ずパラメータバインド（`?`）を使う。文字列フォーマットでのSQL構築禁止
- `connection_manager` の直接呼び出しは `BaseRepository` のみ

### プロンプト・LLM
- ユーザー入力を直接 f-string でプロンプトに埋め込まない
- プロンプトテンプレートは `sai/llm/prompts.py` のみに記述
- ユーザー入力は必ず `sanitize()` → `nonce_mod.wrap()` を通してからプロンプトへ

### シェル実行
- `subprocess.run()` は `shell=False`、引数リスト形式のみ
- `eval()`, `exec()`, `__import__()` 使用禁止
- コマンド実行は `sai/commands/executor.py` 経由のみ（事前登録済みスクリプトのみ実行可能）

---

## 3. セキュリティ規約

処理パイプラインの順序は厳守すること：

```
イベント受信
  → ACLチェック（最初に必ず実行）
  → レートリミットチェック
  → 入力サニタイズ（Sanitizer）
  → Nonce生成・XMLカプセル化
  → LLM呼び出し
  → レスポンス後処理（think/reasoningタグ除去）
  → Slackへ返信
```

- **ACLチェックより前に処理を行わない**
- **レートリミットチェックはACL通過後に必ず実施**
- Nonce は `secrets.token_hex(16)` で生成（推測不可能であること）
- LLM出力をSlackに返す際は長さ制限・コードブロック内容に注意
- ログに秘密情報（トークン・APIキー）を出力しない

---

## 4. テスト規約

- `sai/` 配下の各モジュールに対応するテストファイルを `tests/unit/` に作成する
  - 例：`sai/security/acl.py` → `tests/unit/test_acl.py`
- LLM呼び出しはすべてモック（`respx` または `unittest.mock`）
- DuckDB はテスト用インメモリDB（`:memory:`）を使う（`tests/conftest.py` で提供）
- セキュリティ系テストには必ず攻撃的入力（インジェクション試行・超長文字列・Unicode攻撃）を含める
- `uv run pytest` が全テストパスしてからコミット

### テスト実行
```bash
uv run pytest                        # 全テスト
uv run pytest tests/unit/            # ユニットテストのみ
uv run pytest tests/integration/     # 統合テストのみ
uv run pytest --cov=sai --cov-report=term-missing  # カバレッジ
```

---

## 5. Git・チェンジログ規約

### コミットメッセージ

[Conventional Commits](https://www.conventionalcommits.org/) 形式を使用：

```
<type>: 変更内容の簡潔な説明（英語）

type: feat, fix, chore, docs, refactor, test, perf
```

例：
```
feat: add response_language config with auto-detect fallback
fix: correct Slack table block cell format
chore: prepare v0.1.0 release
docs: update development rules
```

### ブランチ戦略
- `main` ブランチは常に動作するコードを維持
- 機能開発は `feature/<name>` ブランチで行う
- バグ修正は `fix/<name>` ブランチで行う

### CHANGELOG.md
[Keep a Changelog](https://keepachangelog.com/ja/1.0.0/) 形式を使用。

リリース時の記載項目：
- `Added` — 新機能
- `Changed` — 既存機能の変更
- `Fixed` — バグ修正
- `Security` — セキュリティ関連の変更
- `Deprecated` — 非推奨になった機能
- `Removed` — 削除された機能

---

## 6. ドキュメント規約

| ドキュメント | 場所 | 更新タイミング |
|-------------|------|---------------|
| ユーザーガイド（英語） | `README.md` | ユーザー向け機能追加・変更時 |
| ユーザーガイド（日本語） | `README.ja.md` | 同上 — 英語版と常に同期する |
| Slackアプリセットアップ | `docs/slack-setup.md` / `.ja.md` | セットアップ手順変更時 |
| 開発ルール | `docs/development-rules.md` / `.ja.md` | ルール変更時 |
| チェンジログ | `CHANGELOG.md` | リリース時 |
| AIエージェント向けルール | `AGENTS.md` | アーキテクチャ・ルール変更時 |

- **機能追加・変更があれば必ずドキュメントを更新する**
- ユーザー向けドキュメントはすべて英語版・日本語版の両方を提供する
- コードのコメントは自明でないロジックにのみ付ける
- 公開関数には簡潔なdocstringを付ける（型は型アノテーションで表現）

---

## 7. 禁止事項

- `.env` ファイルをコミットに含めない（`.env.example` のみ許可）
- `data/` ディレクトリの `*.db`、`chroma/` をコミットに含めない
- `--no-verify` でコミットフックをスキップしない
- ハードコードされたシークレット（トークン・パスワード）
- `shell=True` でのsubprocess実行
- DB層以外からの `connection_manager` 直接アクセス
