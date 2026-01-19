# Discord LLM Translation Bot

A simple Discord bot that automatically translates messages between Chinese and English using a local LLM.

## Features

- Detects Chinese text → translates to English
- Detects English text → translates to Chinese
- Replies directly to messages with translations
- Supports any OpenAI-compatible LLM API

## Setup

### 1. Create Discord Bot

1. Go to https://discord.com/developers/applications
2. Click "New Application" and give it a name
3. Go to "Bot" section
4. Enable "Message Content Intent" under Privileged Gateway Intents
5. Click "Reset Token" and copy the token

### 2. Invite Bot to Server

1. Go to "OAuth2" → "URL Generator"
2. Select scopes: `bot`
3. Select permissions: `Send Messages`, `Read Message History`
4. Copy the generated URL and open it to invite the bot

### 3. Get Channel IDs (Optional)

To monitor specific channels only:
1. Enable Developer Mode in Discord (Settings → App Settings → Advanced)
2. Right-click on the channel → "Copy Channel ID"

### 4. Configure Environment

```bash
cp .env.example .env
# Edit .env with your values
```

### 5. Run with Docker

```bash
docker-compose up -d
```

### 6. View Logs

```bash
docker-compose logs -f
```

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `DISCORD_TOKEN` | Bot token (required) | - |
| `LLM_URL` | OpenAI-compatible API endpoint | `http://llm.home.cameron.in:8080/v1/chat/completions` |
| `LLM_MODEL` | Model name | `mlx-community/Qwen3-30B-A3B-4bit` |
| `MONITORED_CHANNELS` | Comma-separated channel IDs | Empty (all channels) |

## License

MIT
