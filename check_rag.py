#!/usr/bin/env python3
"""Check RAG database contents including vector database."""

import json
import os
import glob

# Vector database support
try:
    import chromadb
    from chromadb.config import Settings
    CHROMA_AVAILABLE = True
except ImportError:
    CHROMA_AVAILABLE = False

# Use environment variable or default to /data
data_dir = os.environ.get("RAG_DATA_DIR", "/data")
RAG_VECTOR_ENABLED = os.environ.get("RAG_VECTOR_ENABLED", "true").lower() == "true"

print("=" * 60)
print("RAG Database Contents")
print("=" * 60)

# Find all guild JSON files
guild_files = glob.glob(os.path.join(data_dir, "guild_*.json"))

if not guild_files:
    print("\nNo guild data files found!")
    exit(0)

for file_path in guild_files:
    print(f"\nFile: {file_path}")
    print("-" * 60)

    try:
        with open(file_path, 'r') as f:
            data = json.load(f)

        guild_id = data.get("guild_id", "unknown")
        fact_count = len(data.get("facts", []))

        print(f"Guild ID: {guild_id}")
        print(f"Total Facts: {fact_count}")
        print(f"Last Updated: {data.get('last_updated', 'unknown')}")
        print()

        # Count verified vs unverified
        verified_count = sum(1 for f in data.get("facts", []) if f.get("verified", False))
        unverified_count = fact_count - verified_count
        print(f"Verified facts: {verified_count}")
        print(f"Unverified facts: {unverified_count}")
        print()

        # Print each fact
        for i, fact in enumerate(data.get("facts", []), 1):
            verified_icon = "✅" if fact.get("verified", False) else "❌"
            print(f"Fact #{i} {verified_icon}:")
            print(f"  Content: {fact.get('content', 'N/A')}")
            print(f"  Category: {fact.get('category', 'N/A')}")
            print(f"  Keywords: {', '.join(fact.get('keywords', []))}")
            print(f"  Confidence: {fact.get('confidence', 0.0):.2f}")
            print(f"  Verified: {fact.get('verified', False)}")
            print(f"  Source: #{fact.get('extracted_from', {}).get('channel_name', 'unknown')}")
            print()

    except Exception as e:
        print(f"Error reading {file_path}: {e}")

# Vector Database Stats
print()
print("=" * 60)
print("Vector Database Stats")
print("=" * 60)

if not CHROMA_AVAILABLE:
    print("\nChromaDB not installed - vector search unavailable")
elif not RAG_VECTOR_ENABLED:
    print("\nVector search disabled (RAG_VECTOR_ENABLED=false)")
else:
    try:
        chroma_path = os.path.join(data_dir, "chroma")
        if os.path.exists(chroma_path):
            chroma_client = chromadb.PersistentClient(
                path=chroma_path,
                settings=Settings(anonymized_telemetry=False)
            )

            collections = chroma_client.list_collections()
            print(f"\nChroma DB path: {chroma_path}")
            print(f"Total collections: {len(collections)}")

            for collection in collections:
                count = collection.count()
                print(f"\n  Collection: {collection.name}")
                print(f"    Vector count: {count}")

                # Show sample if not empty
                if count > 0:
                    sample = collection.peek(limit=3)
                    if sample["documents"]:
                        print(f"    Sample documents:")
                        for doc in sample["documents"][:3]:
                            preview = doc[:60] + "..." if len(doc) > 60 else doc
                            print(f"      - {preview}")
        else:
            print(f"\nNo ChromaDB data found at {chroma_path}")
    except Exception as e:
        print(f"\nError accessing ChromaDB: {e}")

print()
print("=" * 60)
