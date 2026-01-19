# Discord LLM Translation Bot

A Discord bot that automatically translates messages between Chinese and English channels using a local LLM, with intelligent channel pairing and rich embeds.

## Features

- **Automatic Channel Pairing** - Auto-detects paired channels by emoji prefix and language
- **Channel Topic Pairing** - Explicitly declare pairs in channel descriptions
- **Cross-Channel Translation** - Posts translations to paired channels (not replies)
- **Language Mismatch Detection** - Bot adds 🔄 reaction when wrong language is used
- **On-Demand Translation** - Click 🔄 to translate any message in-place
- **Edit Tracking** - Updates translations when original messages are edited
- **Direct Message Chat** - DM the bot or @mention it to chat with the LLM directly (no translation)
- **RAG Knowledge Base** - Bot learns facts from conversations and provides contextual responses
- **Designated RAG Channel** - Create #knowledge-base channel for explicit fact storage
- **Rich Embeds** - Shows author, original message, and translation with clickable links
- **Attachment Support** - Forwards images and files with translations
- **Multi-Guild Support** - Works across multiple Discord servers
- **Debug Mode** - Detailed logging for troubleshooting

## How It Works

The bot monitors paired channels and translates messages bidirectionally:
- 🏠-general (EN) ↔ 🏠-一般的 (CN)
- 📘-alaska-2026 (EN) ↔ 📘-阿拉斯加-2026 (CN)
- 🐶-pets (EN) ↔ 🐶-宠物 (CN)

### Translation Behavior

**Correct language in channel:**
- Message in English channel with English text → Translates to paired Chinese channel ✓
- Message in Chinese channel with Chinese text → Translates to paired English channel ✓

**Wrong language in channel:**
- Message in English channel with Chinese text → Bot adds 🔄 reaction
- Message in Chinese channel with English text → Bot adds 🔄 reaction
- Anyone can click 🔄 to get translation as a reply in the same channel

**Edited messages:**
- When you edit a message, the translation is automatically updated
- Edited translations show a ✏️ indicator in the footer
- Note: Edit tracking is stored in memory and resets when the bot restarts

**Direct messages and @mentions:**
- DM the bot or @mention it in any channel to chat with the LLM
- No translation, just pure LLM conversation
- Ask questions, get help, or chat about anything
- Example: "@llmbot What is the capital of France?"

**RAG Knowledge Base (Optional):**
- Bot automatically learns facts from chat conversations
- Provides contextual answers using stored knowledge
- Per-server isolation - each Discord server has its own knowledge base
- Example workflow:
  1. User: "@llmbot Hey, John's birthday is May 15, 1990!"
  2. Bot: [Responds and stores fact in background]
  3. Later, user: "@llmbot When is John's birthday?"
  4. Bot: "John's birthday is May 15, 1990" [using stored context]

**Designated RAG Channel:**

You can designate a RAG channel in two ways:

1. **Channel Name Pattern** (automatic detection):
   - Create a channel named #knowledge-base, #facts, #rag, or #info
   - Bot automatically detects these channels

2. **Channel Topic Tag** (explicit designation):
   - Add `rag: true` to any channel's topic/description
   - Example: "Team information | rag: true"

**How it works:**
- Post facts directly without @mentioning the bot
- Bot reacts with ✅ to confirm fact was recorded
- Facts from RAG channel are marked as "verified" and prioritized 1.5x
- Example: Post "Office address is 123 Main St, Seattle, WA" in #knowledge-base

### Channel Pairing Methods (in priority order)

1. **Channel Topic - Explicit Pairing** (highest priority) - Add to channel description:
   - `pair: 一般的` or `pair: #general`
   - `translate: 1234567890` (channel ID)
   - Works with or without spaces, hashtags, or emoji

2. **Manual Override** - Set `CHANNEL_PAIRS` env var:
   - Format: `channel_id1:channel_id2,channel_id3:channel_id4`
   - Example: `1234567890:9876543210`

3. **Auto-Detection** (fallback) - Automatic pairing by:
   - Same emoji prefix (e.g., 🏠)
   - One channel has Chinese characters, one doesn't

### Language Tags

Use `lang:` tags in channel topics to specify the expected language:
- `lang: en` - English channel
- `lang: zh` - Chinese channel (also supports: `zh-cn`, `zh-tw`, `cn`)

**Purpose:**
- Controls language mismatch detection (when bot adds 🔄 reaction)
- Useful when channel names don't contain Chinese characters
- Works with any pairing method (explicit, manual, or auto-detection)

**Example:** `"General discussion | pair: 一般的 | lang: en"`

## Setup

### 1. Create Discord Bot

1. Go to https://discord.com/developers/applications
2. Click "New Application" and give it a name
3. Go to "Bot" section
4. Enable **"Message Content Intent"** under Privileged Gateway Intents
5. Click "Reset Token" and copy the token

### 2. Invite Bot to Server

1. Go to "OAuth2" → "URL Generator"
2. Select scopes: `bot`
3. Select permissions:
   - `Send Messages`
   - `Read Message History`
   - `Embed Links`
   - `Add Reactions` (for 🔄 reaction feature)
4. Copy the generated URL and open it to invite the bot

### 3. Configure Channel Pairs (Optional)

**Option A: Use channel topics** (recommended)
1. Edit channel settings → Channel Topic
2. Add: `pair: chinese-channel-name`

**Option B: Auto-detection**
- Just name channels with matching emoji:
  - `🏠-general` and `🏠-一般的`
- Bot will auto-detect on startup

**Option C: Manual override**
1. Enable Developer Mode in Discord (Settings → App Settings → Advanced)
2. Right-click channels → "Copy Channel ID"
3. Set `CHANNEL_PAIRS` env var

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

Enable `DEBUG_MODE=true` to see detected channel pairs on startup.

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `DISCORD_TOKEN` | Bot token (required) | - |
| `LLM_URL` | OpenAI-compatible API endpoint | `http://llm.home.cameron.in:8080/v1/chat/completions` |
| `LLM_MODEL` | Model name | `mlx-community/Qwen3-30B-A3B-4bit` |
| `CHANNEL_PAIRS` | Manual channel pairs (optional) | Empty (use auto-detection) |
| `DEBUG_MODE` | Enable verbose logging | `false` |
| **RAG Configuration** | | |
| `RAG_ENABLED` | Enable RAG knowledge base | `false` |
| `RAG_DATA_DIR` | Directory for guild JSON files | `/data` |
| `RAG_EXTRACTION_ENABLED` | Auto-extract facts from messages | `true` |
| `RAG_CONFIDENCE_THRESHOLD` | Minimum confidence to store facts (0-1) | `0.7` |
| `RAG_MAX_CONTEXT_FACTS` | Max facts to inject into context | `5` |
| `RAG_KEYWORD_MATCH_THRESHOLD` | Min keyword overlap for retrieval (0-1) | `0.3` |
| `RAG_CHANNEL_ENABLED` | Enable designated RAG channel | `true` |
| `RAG_CHANNEL_PATTERN` | Channel name pattern for RAG channels | `knowledge\|facts\|rag\|info` |
| `RAG_VERIFIED_BOOST` | Score multiplier for verified facts | `1.5` |

## Examples

### Setting Up Channel Topics

**Explicit pairing:**
```
🏠-general:
  Topic: "General discussion | pair: 一般的"

🐶-pets:
  Topic: "Pet photos and stories | translate: 宠物"
```

**Language tags (for channels with English names):**
```
translate-test:
  Topic: "pair: translate-pair | lang: en"

translate-pair:
  Topic: "lang: zh"

# The lang: tag tells the bot which language to expect in each channel
# Useful when channel names don't contain Chinese characters
```

### Manual Channel Pairs

```env
CHANNEL_PAIRS=1462598082326827114:1462598082326827118,1462598082326827115:1462598082326827119
```

## License

MIT
