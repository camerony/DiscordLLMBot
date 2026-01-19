import os
import re
import discord
import aiohttp
import asyncio
from typing import Dict, Optional
import time

DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
LLM_URL = os.environ.get("LLM_URL", "http://localhost:8080/v1/chat/completions")
LLM_MODEL = os.environ.get("LLM_MODEL", "qwen")
DEBUG_MODE = os.environ.get("DEBUG_MODE", "false").lower() == "true"

# RAG Configuration
RAG_ENABLED = os.environ.get("RAG_ENABLED", "false").lower() == "true"
RAG_DATA_DIR = os.environ.get("RAG_DATA_DIR", "/data")
RAG_EXTRACTION_ENABLED = os.environ.get("RAG_EXTRACTION_ENABLED", "true").lower() == "true"
RAG_CONFIDENCE_THRESHOLD = float(os.environ.get("RAG_CONFIDENCE_THRESHOLD", "0.7"))
RAG_MAX_CONTEXT_FACTS = int(os.environ.get("RAG_MAX_CONTEXT_FACTS", "5"))
RAG_KEYWORD_MATCH_THRESHOLD = float(os.environ.get("RAG_KEYWORD_MATCH_THRESHOLD", "0.3"))
RAG_CHANNEL_ENABLED = os.environ.get("RAG_CHANNEL_ENABLED", "true").lower() == "true"
RAG_CHANNEL_PATTERN = os.environ.get("RAG_CHANNEL_PATTERN", "knowledge|facts|rag|info")
RAG_VERIFIED_BOOST = float(os.environ.get("RAG_VERIFIED_BOOST", "1.5"))

# Parse manual channel pairs: "id1:id2,id3:id4,..."
MANUAL_PAIRS = {}
pairs_str = os.environ.get("CHANNEL_PAIRS", "")
if pairs_str:
    for pair in pairs_str.split(","):
        if ":" in pair:
            ch1, ch2 = pair.strip().split(":")
            ch1_id, ch2_id = int(ch1), int(ch2)
            # Bidirectional mapping
            MANUAL_PAIRS[ch1_id] = ch2_id
            MANUAL_PAIRS[ch2_id] = ch1_id

# Will be populated on bot ready
channel_pairs: Dict[int, int] = {}

# Track messages that have been translated via reaction to prevent re-translation
translated_messages: set = set()

# Track message ID mappings: original_message_id -> translation_message_id
# Used for updating translations when original message is edited
message_mappings: Dict[int, int] = {}

# RAG Manager (initialized on bot ready if enabled)
rag_manager = None
if RAG_ENABLED:
    from rag import RAGManager

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.reactions = True
client = discord.Client(intents=intents)


def debug_log(message: str):
    """Log message if debug mode is enabled."""
    if DEBUG_MODE:
        print(f"[DEBUG] {message}")


def has_chinese(text: str) -> bool:
    """Check if text contains Chinese characters."""
    return bool(re.search(r'[\u4e00-\u9fff]', text))


def strip_emoji(channel_name: str) -> str:
    """Remove emoji from start of channel name."""
    # Remove emoji and common separators from start
    return re.sub(r'^[\U0001F000-\U0001F9FF\s\-_]+', '', channel_name).strip()


def find_channel_by_name(guild: discord.Guild, name: str) -> Optional[discord.TextChannel]:
    """Find channel by name, trying exact match first, then without emoji."""
    # Remove # prefix if present
    name = name.lstrip('#').strip()

    # Try exact match first
    for channel in guild.text_channels:
        if channel.name == name:
            return channel

    # Try without emoji
    name_stripped = strip_emoji(name)
    for channel in guild.text_channels:
        if strip_emoji(channel.name) == name_stripped:
            return channel

    return None


def parse_pair_from_topic(topic: str) -> Optional[str]:
    """Extract pair declaration from channel topic."""
    if not topic:
        return None

    # Match "pair: channel" or "translate: channel"
    # Supports: pair:channel, pair: channel, pair:#channel, pair:<#123>
    match = re.search(r'(?:pair|translate):\s*<?#?(\S+?)>?(?:\s|$|,|\|)', topic, re.IGNORECASE)
    if match:
        return match.group(1)
    return None


def parse_lang_from_topic(topic: str) -> Optional[str]:
    """Extract language tag from channel topic (e.g., 'lang: zh', 'lang: en')."""
    if not topic:
        return None

    # Match "lang: xx" where xx is a language code
    match = re.search(r'lang:\s*(\w+)', topic, re.IGNORECASE)
    if match:
        return match.group(1).lower()
    return None


def get_channel_language(channel: discord.TextChannel) -> str:
    """
    Determine the language of a channel.
    Returns 'zh' for Chinese, 'en' for English.
    Checks lang: tag in topic first, then falls back to channel name.
    """
    # Check for explicit lang tag in channel topic
    if channel.topic:
        lang = parse_lang_from_topic(channel.topic)
        if lang:
            # Normalize to 'zh' or 'en'
            if lang in ['zh', 'zh-cn', 'zh-tw', 'cn']:
                return 'zh'
            elif lang == 'en':
                return 'en'

    # Fallback: detect from channel name
    if has_chinese(channel.name):
        return 'zh'
    else:
        return 'en'


def auto_detect_pairs(guild: discord.Guild) -> Dict[int, int]:
    """Auto-detect channel pairs by emoji prefix and language."""
    pairs = {}
    channels = list(guild.text_channels)

    # Group channels by emoji prefix
    emoji_groups: Dict[str, list] = {}
    for channel in channels:
        # Extract emoji from channel name
        emoji_match = re.match(r'^([\U0001F000-\U0001F9FF]+)', channel.name)
        if emoji_match:
            emoji = emoji_match.group(1)
            if emoji not in emoji_groups:
                emoji_groups[emoji] = []
            emoji_groups[emoji].append(channel)

    # Within each emoji group, pair Chinese and non-Chinese channels
    for emoji, group in emoji_groups.items():
        chinese_channels = [ch for ch in group if has_chinese(ch.name)]
        english_channels = [ch for ch in group if not has_chinese(ch.name)]

        # Simple pairing: first Chinese with first English
        if chinese_channels and english_channels:
            for cn_ch, en_ch in zip(chinese_channels, english_channels):
                pairs[cn_ch.id] = en_ch.id
                pairs[en_ch.id] = cn_ch.id
                debug_log(f"Auto-paired: {en_ch.name} ({en_ch.id}) ↔ {cn_ch.name} ({cn_ch.id})")

    return pairs


def build_channel_pairs(guild: discord.Guild) -> Dict[int, int]:
    """Build complete channel pair mapping with priority: explicit pair > manual > auto."""
    pairs = {}

    # Step 1: Auto-detect as base layer
    pairs.update(auto_detect_pairs(guild))

    # Step 2: Apply manual pairs (override auto-detect)
    pairs.update(MANUAL_PAIRS)
    if MANUAL_PAIRS:
        debug_log(f"Applied {len(MANUAL_PAIRS) // 2} manual pair overrides")

    # Step 3: Parse channel topics for explicit pair declarations (highest priority)
    for channel in guild.text_channels:
        if channel.topic:
            pair_ref = parse_pair_from_topic(channel.topic)
            if pair_ref:
                # Try to parse as channel ID
                try:
                    pair_id = int(pair_ref)
                    pair_channel = guild.get_channel(pair_id)
                except ValueError:
                    # Not an ID, search by name
                    pair_channel = find_channel_by_name(guild, pair_ref)

                if pair_channel:
                    # Bidirectional mapping
                    pairs[channel.id] = pair_channel.id
                    pairs[pair_channel.id] = channel.id
                    debug_log(f"Topic-paired: {channel.name} ({channel.id}) ↔ {pair_channel.name} ({pair_channel.id})")
                else:
                    debug_log(f"Warning: Channel '{channel.name}' references pair '{pair_ref}' but not found")

    return pairs


async def translate(text: str) -> Optional[str]:
    """Translate text using the LLM API."""
    # Detect direction based on Chinese character presence
    if has_chinese(text):
        prompt = f"Translate the following Chinese text to English. Output ONLY the translation:\n\n{text}"
    else:
        prompt = f"Translate the following English text to Chinese. Output ONLY the translation:\n\n{text}"

    payload = {
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 1000
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(LLM_URL, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data["choices"][0]["message"]["content"].strip()
                else:
                    print(f"LLM API error: {resp.status}")
    except Exception as e:
        print(f"Translation error: {e}")
    return None


@client.event
async def on_ready():
    global channel_pairs, rag_manager

    print(f"✓ Bot ready: {client.user}")

    # Initialize RAG manager
    if RAG_ENABLED:
        rag_manager = RAGManager(data_dir=RAG_DATA_DIR)
        print(f"✓ RAG enabled with data dir: {RAG_DATA_DIR}")

    # Build channel pairs for each guild
    for guild in client.guilds:
        print(f"✓ Connected to server: {guild.name}")
        guild_pairs = build_channel_pairs(guild)
        channel_pairs.update(guild_pairs)

    if DEBUG_MODE:
        print(f"\n{'='*50}")
        print(f"Channel Pairs Summary:")
        print(f"{'='*50}")
        # Show unique pairs (avoid showing A↔B and B↔A)
        shown = set()
        for ch1_id, ch2_id in channel_pairs.items():
            if ch1_id not in shown:
                ch1 = client.get_channel(ch1_id)
                ch2 = client.get_channel(ch2_id)
                if ch1 and ch2:
                    print(f"  • {ch1.name} ({ch1_id}) ↔ {ch2.name} ({ch2_id})")
                    shown.add(ch1_id)
                    shown.add(ch2_id)
        print(f"{'='*50}")
        print(f"Total active pairs: {len(shown) // 2}\n")
    else:
        print(f"✓ Monitoring {len(channel_pairs) // 2} channel pairs")


@client.event
async def on_message(message):
    # Ignore bot messages
    if message.author.bot:
        return

    # Handle bot mentions as LLM chat requests (both DMs and channel mentions)
    is_dm = isinstance(message.channel, discord.DMChannel)
    is_mentioned = client.user in message.mentions

    if is_dm or is_mentioned:
        # Extract content, removing bot mention if present
        content = message.content
        if is_mentioned:
            # Remove the bot mention from the message
            content = content.replace(f'<@{client.user.id}>', '').replace(f'<@!{client.user.id}>', '').strip()
        else:
            content = content.strip()

        if not content:
            return

        debug_log(f"Chat request from {message.author.name} in {message.channel}: {content}")

        # Send typing indicator
        async with message.channel.typing():
            # Retrieve context from RAG if enabled
            context_str = None
            if RAG_ENABLED and not is_dm and rag_manager:
                guild_id = message.guild.id
                context_str = await rag_manager.retrieve_context(guild_id, content)
                if context_str:
                    debug_log(f"Retrieved RAG context for query")

            # Build messages array with context
            messages = []
            if context_str:
                messages.append({"role": "system", "content": context_str})
            messages.append({"role": "user", "content": content})

            # Make LLM request without translation prompt
            payload = {
                "model": LLM_MODEL,
                "messages": messages,
                "temperature": 0.7,
                "max_tokens": 2000
            }

            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(LLM_URL, json=payload) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            response = data["choices"][0]["message"]["content"].strip()

                            # Split long responses into multiple messages (Discord limit: 2000 chars)
                            if len(response) <= 2000:
                                await message.reply(response)
                            else:
                                # Split at newlines to avoid cutting mid-sentence
                                chunks = []
                                current_chunk = ""
                                for line in response.split("\n"):
                                    if len(current_chunk) + len(line) + 1 <= 2000:
                                        current_chunk += line + "\n"
                                    else:
                                        if current_chunk:
                                            chunks.append(current_chunk)
                                        current_chunk = line + "\n"
                                if current_chunk:
                                    chunks.append(current_chunk)

                                # Reply to first chunk, send rest as follow-ups
                                await message.reply(chunks[0])
                                for chunk in chunks[1:]:
                                    await message.channel.send(chunk)
                        else:
                            await message.reply(f"Sorry, I encountered an error: HTTP {resp.status}")
                            print(f"LLM API error: {resp.status}")
            except Exception as e:
                await message.reply("Sorry, I encountered an error processing your request.")
                print(f"Chat error: {e}")

        # Extract facts in background (non-blocking)
        if RAG_ENABLED and not is_dm and RAG_EXTRACTION_ENABLED and rag_manager:
            guild_id = message.guild.id
            # Check if this is a designated RAG channel
            is_rag = rag_manager.is_rag_channel(message.channel.name, message.channel.topic)
            asyncio.create_task(
                rag_manager.extract_facts_from_message(message, content, is_rag_channel=is_rag)
            )
        return

    # Handle RAG channel messages (extract facts even without @mention)
    if RAG_ENABLED and RAG_CHANNEL_ENABLED and rag_manager:
        if rag_manager.is_rag_channel(message.channel.name, message.channel.topic):
            # Extract facts from RAG channel messages
            content = message.content.strip()
            if content and len(content) >= 2:
                guild_id = message.guild.id

                # Chunk large messages with context preservation
                chunks = await rag_manager.chunk_message_with_context(content)

                print(f"[RAG] Processing {len(chunks)} chunk(s) sequentially to avoid server overload...")

                # Process chunks sequentially to avoid overwhelming LLM server
                for i, chunk in enumerate(chunks, 1):
                    try:
                        print(f"[RAG] Processing chunk {i}/{len(chunks)}...")
                        await rag_manager.extract_facts_from_message(message, chunk, is_rag_channel=True)
                    except Exception as e:
                        print(f"[RAG] Error processing chunk {i}/{len(chunks)}: {e}")

                # React with ✅ to confirm fact was recorded
                try:
                    await message.add_reaction("✅")
                except discord.errors.Forbidden:
                    print("Warning: Bot lacks permission to add reactions")
            return  # Don't process as translation

    # Check if this channel has a pair
    if message.channel.id not in channel_pairs:
        debug_log(f"Skipping message in unpaired channel: {message.channel.name}")
        return

    # Get paired channel
    target_channel_id = channel_pairs[message.channel.id]
    target_channel = client.get_channel(target_channel_id)

    if not target_channel:
        debug_log(f"Error: Paired channel {target_channel_id} not found")
        return

    # Get message content
    content = message.content.strip()

    # Handle media-only messages (no text, just attachments)
    if not content and message.attachments:
        debug_log(f"Media-only message in {message.channel.name}, forwarding attachments")
        # Send attachments directly without translation
        for att in message.attachments:
            await target_channel.send(att.url)
        return

    # Skip if no content at all
    if not content or len(content) < 2:
        debug_log(f"Skipping short/empty message")
        return

    # Detect language mismatch
    channel_lang = get_channel_language(message.channel)
    message_lang = 'zh' if has_chinese(content) else 'en'

    # If language doesn't match channel, add 🔄 reaction and skip
    if channel_lang != message_lang:
        debug_log(f"Language mismatch in {message.channel.name}: adding 🔄 reaction")
        try:
            await message.add_reaction("🔄")
        except discord.errors.Forbidden:
            print("Warning: Bot lacks permission to add reactions")
        return

    # Translate the content
    start_time = time.time()
    translation = await translate(content)
    elapsed = time.time() - start_time

    if not translation:
        debug_log(f"Translation failed for message in {message.channel.name}")
        return

    debug_log(f"Translated message from {message.channel.name} → {target_channel.name} ({elapsed:.2f}s)")

    # Create embed with author info
    embed = discord.Embed(
        description=translation,
        color=0x5865F2 if not has_chinese(content) else 0xED4245  # Blue for EN→CN, Red for CN→EN
    )

    # Add author info with clickable link to original
    embed.set_author(
        name=f"{message.author.display_name} • #{message.channel.name}",
        icon_url=message.author.display_avatar.url,
        url=message.jump_url
    )

    # Send translation embed
    translation_msg = await target_channel.send(embed=embed)

    # Store message mapping for edit tracking
    message_mappings[message.id] = translation_msg.id

    # Send attachments as separate messages (for messages with both text and images)
    if message.attachments:
        for att in message.attachments:
            await target_channel.send(att.url)


@client.event
async def on_message_edit(before, after):
    """Handle message edits and update translations."""
    # Ignore bot messages
    if after.author.bot:
        return

    # Check if this message was translated
    if before.id not in message_mappings:
        debug_log(f"Edited message {before.id} has no translation, skipping")
        return

    # Check if content actually changed
    if before.content == after.content:
        debug_log(f"Message {before.id} edited but content unchanged, skipping")
        return

    # Check if message is in a paired channel
    if after.channel.id not in channel_pairs:
        return

    # Get the translation message
    translation_msg_id = message_mappings[before.id]
    target_channel_id = channel_pairs[after.channel.id]
    target_channel = client.get_channel(target_channel_id)

    if not target_channel:
        debug_log(f"Error: Paired channel {target_channel_id} not found for edit")
        return

    try:
        translation_msg = await target_channel.fetch_message(translation_msg_id)
    except discord.NotFound:
        debug_log(f"Translation message {translation_msg_id} not found, removing mapping")
        del message_mappings[before.id]
        return
    except discord.Forbidden:
        print(f"Warning: Bot lacks permission to fetch message {translation_msg_id}")
        return

    # Get new content
    content = after.content.strip()

    # Skip if no content
    if not content or len(content) < 2:
        debug_log(f"Edited message has no content, skipping")
        return

    # Check language mismatch
    channel_lang = get_channel_language(after.channel)
    message_lang = 'zh' if has_chinese(content) else 'en'

    if channel_lang != message_lang:
        debug_log(f"Edited message has language mismatch, not updating translation")
        return

    # Translate the new content
    start_time = time.time()
    translation = await translate(content)
    elapsed = time.time() - start_time

    if not translation:
        debug_log(f"Translation failed for edited message in {after.channel.name}")
        return

    debug_log(f"Updated translation for edited message in {after.channel.name} ({elapsed:.2f}s)")

    # Update the embed
    embed = discord.Embed(
        description=translation,
        color=0x5865F2 if not has_chinese(content) else 0xED4245
    )

    # Add author info with clickable link to original
    embed.set_author(
        name=f"{after.author.display_name} • #{after.channel.name}",
        icon_url=after.author.display_avatar.url,
        url=after.jump_url
    )

    # Add edited indicator
    embed.set_footer(text="✏️ Edited")

    # Update the translation message
    try:
        await translation_msg.edit(embed=embed)
    except discord.Forbidden:
        print(f"Warning: Bot lacks permission to edit message {translation_msg_id}")
    except discord.HTTPException as e:
        print(f"Error editing translation message: {e}")


@client.event
async def on_reaction_add(reaction, user):
    # Ignore bot's own reactions
    if user.bot:
        return

    # Only handle 🔄 emoji
    if str(reaction.emoji) != "🔄":
        return

    message = reaction.message

    # Skip if already translated
    if message.id in translated_messages:
        debug_log(f"Message {message.id} already translated, skipping")
        return

    # Skip if message has no content
    content = message.content.strip()
    if not content or len(content) < 2:
        return

    debug_log(f"🔄 reaction on message in {message.channel.name} by {user.name}")

    # Translate and reply in same channel
    start_time = time.time()
    translation = await translate(content)
    elapsed = time.time() - start_time

    if not translation:
        debug_log(f"Translation failed for reaction in {message.channel.name}")
        return

    # Mark as translated
    translated_messages.add(message.id)

    # Reply with simple translation (not full embed for in-channel)
    await message.reply(translation, mention_author=False)
    debug_log(f"Translated via reaction: {message.channel.name} ({elapsed:.2f}s)")


if __name__ == "__main__":
    client.run(DISCORD_TOKEN)
