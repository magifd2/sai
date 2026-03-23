# Slack App Setup Guide

> 🇯🇵 日本語版: [slack-setup.ja.md](slack-setup.ja.md)

Step-by-step instructions for connecting SAI to your Slack workspace.

---

## Prerequisites

- Admin rights in your Slack workspace (or permission to add apps)
- Access to the [Slack API site](https://api.slack.com/apps)

---

## Step 1: Create a Slack App

1. Open [https://api.slack.com/apps](https://api.slack.com/apps)
2. Click **"Create New App"**
3. Select **"From scratch"**
4. Enter an app name (e.g. `SAI`) and select the target workspace, then click **"Create App"**

---

## Step 2: Enable Socket Mode

Socket Mode lets SAI receive real-time events without exposing a public HTTP endpoint.

1. Click **"Socket Mode"** in the left menu
2. Toggle **"Enable Socket Mode"** on
3. Enter `SAI_APP_TOKEN` as the token name and click **"Generate"**
4. Copy the `xapp-1-...` token and save it

   > This becomes your `SAI_SLACK_APP_TOKEN`

---

## Step 3: Configure Bot Token Scopes

1. Click **"OAuth & Permissions"** in the left menu
2. Under **"Scopes" → "Bot Token Scopes"**, add the following:

   | Scope | Purpose |
   |-------|---------|
   | `channels:history` | Read message history in public channels |
   | `channels:read` | List public channels |
   | `chat:write` | Post messages |
   | `groups:history` | Read message history in private channels |
   | `groups:read` | List private channels |
   | `im:history` | Read DM history (optional) |
   | `reactions:read` | Receive reaction events (required for pinning) |
   | `users:read` | Fetch user information |
   | `app_mentions:read` | Receive @mention events |

---

## Step 4: Configure Event Subscriptions

1. Click **"Event Subscriptions"** in the left menu
2. Toggle **"Enable Events"** on
3. Under **"Subscribe to bot events"**, add:

   | Event | Purpose |
   |-------|---------|
   | `message.channels` | Monitor public channel messages |
   | `message.groups` | Monitor private channel messages |
   | `app_mention` | Receive @mentions |
   | `reaction_added` | Receive reaction events (required for pinning) |

4. Click **"Save Changes"**

---

## Step 5: Install the App to Your Workspace

1. Click **"OAuth & Permissions"** in the left menu
2. Click **"Install to Workspace"**
3. Review the permissions and click **"Allow"**
4. Copy the **"Bot User OAuth Token"** (`xoxb-...`) and save it

   > This becomes your `SAI_SLACK_BOT_TOKEN`

---

## Step 6: Configure SAI Environment Variables

Create a `.env` file in the project root:

```bash
cp .env.example .env
```

Edit `.env` with the tokens you collected:

```env
SAI_SLACK_BOT_TOKEN=xoxb-xxxxxxxxxxxx-xxxxxxxxxxxx-xxxxxxxxxxxxxxxxxxxxxxxx
SAI_SLACK_APP_TOKEN=xapp-1-xxxxxxxxxxxx-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

---

## Step 7: Invite SAI to Channels

In Slack, invite SAI to every channel it should monitor:

```
/invite @SAI
```

Or use the channel's **"Add members"** option.

---

## Step 8: Start SAI

```bash
# Initialize the database (first time only)
uv run sai init-db

# Verify LLM connectivity
uv run sai check

# Start the bot
uv run sai start
```

The bot is ready when `sai.ready` appears in the log.

---

## Step 9: Verify It Works

1. In a channel SAI has joined, send `@SAI hello`
2. SAI should reply — if it does, setup is complete

### Try the pinning feature

Add a 📌 (`:pushpin:`) reaction to any message. That message will be stored in permanent memory and will never be aged out or archived.

---

## Troubleshooting

### `invalid_auth` error
→ Check that `SAI_SLACK_BOT_TOKEN` was copied correctly

### Events not arriving
→ Confirm Socket Mode is enabled
→ Confirm `SAI_SLACK_APP_TOKEN` (`xapp-...`) is set correctly

### @mentions not answered
→ Confirm `app_mention` is in "Subscribe to bot events"
→ Confirm SAI has been invited to the channel

### Reactions ignored
→ Confirm `reaction_added` is in "Subscribe to bot events"
→ Check that the reaction name matches `SAI_MEMORY_PIN_REACTIONS`
  (defaults: `pushpin`, `star`, `bookmark`, `memo`)

---

## Slack Plan Requirements

Socket Mode is available on **all plans** including the free tier.
Private channel history access may require additional workspace-level settings depending on your plan.
