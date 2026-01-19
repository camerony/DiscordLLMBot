#!/usr/bin/env python3
"""Check RAG database contents."""

import json
import os
import glob

# Use environment variable or default to /data
data_dir = os.environ.get("RAG_DATA_DIR", "/data")

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

print("=" * 60)
