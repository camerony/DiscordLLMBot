import os
import re
import discord
import aiohttp

DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
LLM_URL = os.environ.get("LLM_URL", "http://localhost:8080/v1/chat/completions")
LLM_MODEL = os.environ.get("LLM_MODEL", "qwen")
MONITORED_CHANNELS = [int(c) for c in os.environ.get("MONITORED_CHANNELS", "").split(",") if c.strip()]

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)


def has_chinese(text):
    """Check if text contains Chinese characters."""
    return bool(re.search(r'[\u4e00-\u9fff]', text))


async def translate(text):
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
    print(f"Bot ready: {client.user}")
    if MONITORED_CHANNELS:
        print(f"Monitoring channels: {MONITORED_CHANNELS}")
    else:
        print("Monitoring ALL channels (no filter set)")


@client.event
async def on_message(message):
    # Ignore bot messages
    if message.author.bot:
        return

    # Check if channel is monitored (empty list = monitor all)
    if MONITORED_CHANNELS and message.channel.id not in MONITORED_CHANNELS:
        return

    # Skip very short messages
    if len(message.content.strip()) < 2:
        return

    translation = await translate(message.content)
    if translation:
        await message.reply(f"**Translation:**\n{translation}", mention_author=False)


if __name__ == "__main__":
    client.run(DISCORD_TOKEN)
