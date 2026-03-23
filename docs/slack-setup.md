# Slack アプリセットアップガイド

SAIをSlackで動作させるためのステップバイステップ手順です。

---

## 前提条件

- Slackワークスペースの管理者権限（またはアプリ追加権限）
- [Slack API サイト](https://api.slack.com/apps) へのアクセス

---

## Step 1: Slack アプリを作成する

1. [https://api.slack.com/apps](https://api.slack.com/apps) を開く
2. **「Create New App」** をクリック
3. **「From scratch」** を選択
4. アプリ名（例: `SAI`）とインストール先のワークスペースを選んで **「Create App」**

---

## Step 2: Socket Mode を有効にする

Socket Mode を使うと、パブリックなエンドポイント（サーバー公開）なしにリアルタイムイベントを受信できます。

1. 左メニューの **「Socket Mode」** をクリック
2. **「Enable Socket Mode」** をオンにする
3. Token Name に `SAI_APP_TOKEN` と入力して **「Generate」**
4. 表示される `xapp-1-...` のトークンをコピーして保存

   > これが `SAI_SLACK_APP_TOKEN` になります

---

## Step 3: Bot Token Scopes を設定する

1. 左メニューの **「OAuth & Permissions」** をクリック
2. **「Scopes」** セクションの **「Bot Token Scopes」** で以下を追加:

   | Scope | 用途 |
   |-------|------|
   | `channels:history` | チャンネルのメッセージ履歴を読む |
   | `channels:read` | チャンネル一覧を取得する |
   | `chat:write` | メッセージを送信する |
   | `groups:history` | プライベートチャンネルの履歴を読む |
   | `groups:read` | プライベートチャンネル一覧を取得する |
   | `im:history` | DM履歴を読む（任意） |
   | `reactions:read` | リアクションイベントを受信する（ピン機能に必要） |
   | `users:read` | ユーザー情報を取得する |
   | `app_mentions:read` | @メンションを受信する |

---

## Step 4: Event Subscriptions を設定する

1. 左メニューの **「Event Subscriptions」** をクリック
2. **「Enable Events」** をオンにする
3. **「Subscribe to bot events」** に以下を追加:

   | Event | 用途 |
   |-------|------|
   | `message.channels` | パブリックチャンネルのメッセージを監視 |
   | `message.groups` | プライベートチャンネルのメッセージを監視 |
   | `app_mention` | @メンションを受信 |
   | `reaction_added` | リアクション追加を受信（ピン機能に必要） |

4. **「Save Changes」** をクリック

---

## Step 5: アプリをワークスペースにインストールする

1. 左メニューの **「OAuth & Permissions」** をクリック
2. **「Install to Workspace」** をクリック
3. 権限を確認して **「許可する」**
4. **「Bot User OAuth Token」**（`xoxb-...`）をコピーして保存

   > これが `SAI_SLACK_BOT_TOKEN` になります

---

## Step 6: SAI の環境変数を設定する

プロジェクトルートで `.env` ファイルを作成:

```bash
cp .env.example .env
```

`.env` を編集して取得したトークンを設定:

```env
SAI_SLACK_BOT_TOKEN=xoxb-xxxxxxxxxxxx-xxxxxxxxxxxx-xxxxxxxxxxxxxxxxxxxxxxxx
SAI_SLACK_APP_TOKEN=xapp-1-xxxxxxxxxxxx-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

---

## Step 7: SAI をチャンネルに招待する

Slack上でSAIを動作させたいチャンネルで:

```
/invite @SAI
```

または、チャンネルの「メンバーを追加」からSAIを追加してください。

---

## Step 8: SAI を起動する

```bash
# データベースの初期化（初回のみ）
uv run sai init-db

# LLMへの接続確認
uv run sai check

# 起動
uv run sai start
```

起動ログに `sai.ready` が表示されれば成功です。

---

## Step 9: 動作確認

1. SAIを招待したチャンネルで `@SAI こんにちは` とメッセージを送信
2. SAIから返答があれば正常に動作しています

### メモリのピン留めを試す

任意のメッセージに 📌（`:pushpin:`）のリアクションを付けてみてください。
そのメッセージは永続記憶に保存され、ライフサイクル管理の対象外になります。

---

## トラブルシューティング

### `invalid_auth` エラー
→ `SAI_SLACK_BOT_TOKEN` が正しくコピーされているか確認

### イベントが届かない
→ Socket Mode が有効になっているか確認
→ `SAI_SLACK_APP_TOKEN` (`xapp-...`) が正しく設定されているか確認

### @メンションに返答しない
→ `app_mention` イベントが Subscribe to bot events に追加されているか確認
→ SAIがそのチャンネルに招待されているか確認

### リアクションが無視される
→ `reaction_added` イベントが Subscribe to bot events に追加されているか確認
→ `SAI_MEMORY_PIN_REACTIONS` の設定でリアクション名が正しいか確認（デフォルト: `pushpin,star,bookmark,memo`）

---

## 必要なSlackプラン

Socket Modeは**全プラン**で利用可能です（フリープランを含む）。
ただし、プライベートチャンネルの履歴読み取りにはワークスペースの設定が必要な場合があります。
