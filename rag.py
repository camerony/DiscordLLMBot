import os
import re
import json
import asyncio
import aiohttp
from typing import Dict, List, Optional, Set
from datetime import datetime
from collections import OrderedDict
import uuid

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
RAG_EXTRACTION_MAX_TOKENS = int(os.environ.get("RAG_EXTRACTION_MAX_TOKENS", "1500"))
RAG_CHUNKING_ENABLED = os.environ.get("RAG_CHUNKING_ENABLED", "true").lower() == "true"
RAG_CHUNK_THRESHOLD = int(os.environ.get("RAG_CHUNK_THRESHOLD", "2000"))
RAG_CHUNK_MAX_SIZE = int(os.environ.get("RAG_CHUNK_MAX_SIZE", "500"))

# LLM Configuration (reuse from main bot)
LLM_URL = os.environ.get("LLM_URL", "http://localhost:8080/v1/chat/completions")
LLM_MODEL = os.environ.get("LLM_MODEL", "qwen")

# Stopwords for keyword extraction
STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "as", "is", "was", "are", "were", "be",
    "been", "being", "have", "has", "had", "do", "does", "did", "will",
    "would", "should", "could", "may", "might", "can", "what", "when",
    "where", "who", "how", "why", "which", "this", "that", "these", "those",
    "i", "you", "he", "she", "it", "we", "they", "my", "your", "his", "her",
    "its", "our", "their"
}


class RAGManager:
    """Manages RAG knowledge base with per-guild JSON storage."""

    def __init__(self, data_dir: str = RAG_DATA_DIR):
        self.data_dir = data_dir
        self.cache: OrderedDict[str, Dict] = OrderedDict()
        self.cache_size = 10

        # Ensure data directory exists
        os.makedirs(data_dir, exist_ok=True)

    def _get_guild_file(self, guild_id: int) -> str:
        """Get the file path for a guild's data."""
        return os.path.join(self.data_dir, f"guild_{guild_id}.json")

    def load_guild_data(self, guild_id: int) -> Dict:
        """Load guild data from JSON file with LRU caching."""
        guild_key = str(guild_id)

        # Check cache first
        if guild_key in self.cache:
            # Move to end (most recently used)
            self.cache.move_to_end(guild_key)
            return self.cache[guild_key]

        # Load from file
        file_path = self._get_guild_file(guild_id)

        if not os.path.exists(file_path):
            # Create new guild data
            data = {
                "guild_id": str(guild_id),
                "last_updated": datetime.utcnow().isoformat() + "Z",
                "facts": [],
                "metadata": {
                    "total_facts": 0,
                    "total_messages_processed": 0,
                    "categories": {}
                }
            }
        else:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                print(f"Error loading guild {guild_id} data: {e}")
                # Backup corrupted file
                backup_path = f"{file_path}.backup"
                if os.path.exists(file_path):
                    os.rename(file_path, backup_path)
                    print(f"Backed up corrupted file to {backup_path}")
                # Create new data
                data = {
                    "guild_id": str(guild_id),
                    "last_updated": datetime.utcnow().isoformat() + "Z",
                    "facts": [],
                    "metadata": {
                        "total_facts": 0,
                        "total_messages_processed": 0,
                        "categories": {}
                    }
                }

        # Add to cache
        self.cache[guild_key] = data
        self.cache.move_to_end(guild_key)

        # Evict oldest if cache is full
        if len(self.cache) > self.cache_size:
            self.cache.popitem(last=False)

        return data

    def save_guild_data(self, guild_id: int, data: Dict):
        """Save guild data to JSON file with atomic write."""
        file_path = self._get_guild_file(guild_id)
        temp_path = f"{file_path}.tmp"

        # Update timestamp
        data["last_updated"] = datetime.utcnow().isoformat() + "Z"

        try:
            # Write to temp file
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            # Atomic rename
            os.replace(temp_path, file_path)

            # Update cache
            guild_key = str(guild_id)
            self.cache[guild_key] = data
            self.cache.move_to_end(guild_key)
        except IOError as e:
            print(f"Error saving guild {guild_id} data: {e}")
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def is_rag_channel(self, channel_name: str, channel_topic: Optional[str]) -> bool:
        """Check if channel is a designated RAG channel."""
        if not RAG_CHANNEL_ENABLED:
            return False

        # Check channel topic for explicit tag
        if channel_topic:
            # Look for "rag: true" in topic
            if re.search(r'rag:\s*true', channel_topic, re.IGNORECASE):
                return True

        # Check channel name against pattern
        if re.search(RAG_CHANNEL_PATTERN, channel_name, re.IGNORECASE):
            return True

        return False

    def extract_keywords(self, text: str) -> List[str]:
        """Extract keywords from text (lowercase, no stopwords)."""
        # Tokenize: split on non-alphanumeric
        tokens = re.findall(r'\w+', text.lower())

        # Filter stopwords and short tokens
        keywords = [t for t in tokens if t not in STOPWORDS and len(t) > 2]

        # Remove duplicates while preserving order
        seen: Set[str] = set()
        unique_keywords = []
        for kw in keywords:
            if kw not in seen:
                seen.add(kw)
                unique_keywords.append(kw)

        return unique_keywords

    def calculate_keyword_overlap(self, keywords1: List[str], keywords2: List[str]) -> float:
        """Calculate keyword overlap ratio."""
        set1 = set(keywords1)
        set2 = set(keywords2)

        if not set1:
            return 0.0

        overlap = len(set1 & set2)
        return overlap / len(set1)

    def search_facts(self, facts: List[Dict], query_keywords: List[str]) -> List[Dict]:
        """Search facts by keyword matching with verified boost."""
        if not query_keywords:
            return []

        scored_facts = []
        query_set = set(query_keywords)

        for fact in facts:
            fact_keywords = set(fact.get("keywords", []))

            # Calculate base score
            if not query_keywords:
                score = 0.0
            else:
                overlap = len(query_set & fact_keywords)
                score = overlap / len(query_keywords)

            # Boost verified facts
            if fact.get("verified", False):
                score *= RAG_VERIFIED_BOOST

            # Filter by threshold
            if score >= RAG_KEYWORD_MATCH_THRESHOLD:
                scored_facts.append((score, fact))

        # Sort by score descending
        scored_facts.sort(key=lambda x: x[0], reverse=True)

        # Return top facts (without scores)
        return [fact for score, fact in scored_facts[:RAG_MAX_CONTEXT_FACTS]]

    async def retrieve_context(self, guild_id: int, query: str) -> Optional[str]:
        """Retrieve relevant context for a query."""
        try:
            # Load guild data
            data = self.load_guild_data(guild_id)
            facts = data.get("facts", [])

            if not facts:
                return None

            # Extract query keywords
            query_keywords = self.extract_keywords(query)

            if not query_keywords:
                return None

            # Search for relevant facts
            relevant_facts = self.search_facts(facts, query_keywords)

            if not relevant_facts:
                return None

            # Format context string with source attribution
            context_lines = ["Relevant context from this server:"]

            for fact in relevant_facts:
                content = fact.get("content", "")
                extracted_from = fact.get("extracted_from", {})
                channel_name = extracted_from.get("channel_name", "unknown")
                author_name = extracted_from.get("author_name", "unknown")
                verified = fact.get("verified", False)

                # Add source attribution
                if verified:
                    source = f"(from #{channel_name})"
                else:
                    source = f"(mentioned by {author_name})"

                context_lines.append(f"- {content} {source}")

            return "\n".join(context_lines)

        except Exception as e:
            print(f"Error retrieving context for guild {guild_id}: {e}")
            return None

    async def chunk_message_with_context(self, content: str) -> List[str]:
        """Use LLM to split large message into contextually complete chunks."""

        # Only chunk if enabled and message is large
        if not RAG_CHUNKING_ENABLED or len(content) < RAG_CHUNK_THRESHOLD:
            return [content]

        system_prompt = f"""Split the following message into smaller chunks where each chunk is self-contained and preserves context.

Rules:
1. Keep all information about one person/entity together in the same chunk
2. Add context where needed (e.g., "Email: bella@gmail.com" → "Bella Liu's email is bella@gmail.com")
3. Each chunk should be under {RAG_CHUNK_MAX_SIZE} characters
4. Return a JSON array of strings, one per chunk
5. Preserve all original information - don't summarize or omit anything

Example input:
"Bella Liu's birthday is January 17, 2005. Email: bellaliu208@gmail.com. Mobile: (949) 351-9388. Nicholas Liu's birthday is December 6, 2006."

Example output:
[
  "Bella Liu's birthday is January 17, 2005. Bella Liu's email is bellaliu208@gmail.com. Bella Liu's mobile is (949) 351-9388.",
  "Nicholas Liu's birthday is December 6, 2006."
]"""

        payload = {
            "model": LLM_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content}
            ],
            "temperature": 0.1,
            "max_tokens": 2000
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(LLM_URL, json=payload) as resp:
                    if resp.status != 200:
                        print(f"LLM chunking failed: {resp.status}")
                        return [content]  # Fallback to single chunk

                    data = await resp.json()
                    response_text = data["choices"][0]["message"]["content"].strip()

                    # Parse JSON array
                    json_match = re.search(r'\[.*\]', response_text, re.DOTALL)
                    if json_match:
                        chunks = json.loads(json_match.group(0))
                        if isinstance(chunks, list) and all(isinstance(c, str) for c in chunks):
                            print(f"[RAG] Split message into {len(chunks)} contextual chunks")
                            return chunks

                    # Fallback if parsing fails
                    print(f"[RAG] Chunking failed to parse, using original message")
                    return [content]
        except Exception as e:
            print(f"Error chunking message: {e}")
            return [content]  # Fallback

    async def extract_facts_from_message(self, message, content: str, is_rag_channel: bool = False):
        """Extract facts from a message using LLM."""
        if not RAG_EXTRACTION_ENABLED:
            return

        try:
            guild_id = message.guild.id

            # Create extraction prompt
            system_prompt = """Extract factual information from the following message. Return ONLY a JSON array of facts.
Each fact should have:
- content: The fact as a complete sentence
- category: One of [birthday, location, contact, preference, general]
- confidence: A score from 0 to 1 indicating your confidence in the fact
- keywords: Array of searchable keywords (lowercase, no stopwords)
- entities: Object with extracted entities (e.g., {"person": "John", "date": "May 15, 1990"})

Return [] if no facts are found. Do not include conversational or hypothetical statements."""

            user_prompt = f"""Message: "{content}"
Author: {message.author.display_name}"""

            payload = {
                "model": LLM_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "temperature": 0.1,
                "max_tokens": RAG_EXTRACTION_MAX_TOKENS
            }

            # Make LLM request
            async with aiohttp.ClientSession() as session:
                async with session.post(LLM_URL, json=payload) as resp:
                    if resp.status != 200:
                        print(f"LLM API error during fact extraction: {resp.status}")
                        return

                    data = await resp.json()
                    response_text = data["choices"][0]["message"]["content"].strip()

            # Parse JSON response
            try:
                # Try to extract JSON array from response
                json_match = re.search(r'\[.*\]', response_text, re.DOTALL)
                if json_match:
                    extracted_facts = json.loads(json_match.group(0))
                else:
                    extracted_facts = json.loads(response_text)

                if not isinstance(extracted_facts, list):
                    print(f"Invalid extraction response: not a list")
                    return
            except json.JSONDecodeError as e:
                print(f"Failed to parse extraction response as JSON: {e}")
                print(f"Response: {response_text[:200]}")
                return

            if not extracted_facts:
                return

            # Load guild data
            guild_data = self.load_guild_data(guild_id)
            existing_facts = guild_data.get("facts", [])

            # Process each extracted fact
            new_facts_added = 0
            for fact in extracted_facts:
                confidence = fact.get("confidence", 0.0)

                # Apply confidence threshold (unless from RAG channel)
                if not is_rag_channel and confidence < RAG_CONFIDENCE_THRESHOLD:
                    continue

                # Extract keywords if not provided
                if "keywords" not in fact or not fact["keywords"]:
                    fact["keywords"] = self.extract_keywords(fact.get("content", ""))

                # Check for duplicates
                is_duplicate = False
                for existing_fact in existing_facts:
                    existing_keywords = existing_fact.get("keywords", [])
                    overlap = self.calculate_keyword_overlap(fact["keywords"], existing_keywords)
                    if overlap > 0.7:  # 70% overlap threshold
                        is_duplicate = True
                        break

                if is_duplicate:
                    continue

                # Create fact entry
                fact_entry = {
                    "id": f"fact_{uuid.uuid4().hex[:8]}",
                    "content": fact.get("content", ""),
                    "category": fact.get("category", "general"),
                    "keywords": fact["keywords"],
                    "entities": fact.get("entities", {}),
                    "confidence": confidence,
                    "verified": is_rag_channel,
                    "extracted_from": {
                        "message_id": str(message.id),
                        "author_id": str(message.author.id),
                        "author_name": message.author.display_name,
                        "channel_id": str(message.channel.id),
                        "channel_name": message.channel.name,
                        "timestamp": message.created_at.isoformat() + "Z",
                        "original_message": content[:200]  # Truncate
                    },
                    "created_at": datetime.utcnow().isoformat() + "Z"
                }

                # Add to facts
                existing_facts.append(fact_entry)
                new_facts_added += 1

                # Update category count
                category = fact_entry["category"]
                if "categories" not in guild_data["metadata"]:
                    guild_data["metadata"]["categories"] = {}
                guild_data["metadata"]["categories"][category] = guild_data["metadata"]["categories"].get(category, 0) + 1

            if new_facts_added > 0:
                # Update metadata
                guild_data["facts"] = existing_facts
                guild_data["metadata"]["total_facts"] = len(existing_facts)
                guild_data["metadata"]["total_messages_processed"] = guild_data["metadata"].get("total_messages_processed", 0) + 1

                # Save
                self.save_guild_data(guild_id, guild_data)

                print(f"[RAG] Extracted {new_facts_added} fact(s) from message in #{message.channel.name} (verified: {is_rag_channel})")

        except Exception as e:
            print(f"Error extracting facts from message: {e}")
            import traceback
            traceback.print_exc()
