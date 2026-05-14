import asyncio
import logging
import os
from bot.platforms.jiosaavn import jiosaavn_extractor
from bot.platforms.youtube import youtube_extractor

logging.basicConfig(level=logging.INFO)

async def test_jiosaavn_decryption():
    print("\n--- Testing JioSaavn Decryption ---")
    # Example encrypted URL from JioSaavn
    # This is a sample, real ones are longer
    sample_encrypted = "Lms76Scy6X6M/f8fP1Z8uV+U8y8q8u8v8x8z81838587898=" 
    # Actually, let's just test the search and extract flow
    print("Searching for 'Arijit Singh' on JioSaavn...")
    results = await jiosaavn_extractor.search("Arijit Singh", limit=1)
    if results:
        track = results[0]
        print(f"Found: {track['title']} - {track['artist']} (ID: {track['id']})")
        print("Extracting details...")
        details = await jiosaavn_extractor.extract(track['id'])
        if details:
            print(f"Success! Stream URL: {details['stream_url'][:60]}...")
        else:
            print("Extraction failed.")
    else:
        print("Search failed.")

async def test_youtube_extraction():
    print("\n--- Testing YouTube Extraction ---")
    print("Searching for 'Never Gonna Give You Up' on YouTube...")
    results = await youtube_extractor.search("Never Gonna Give You Up", limit=1)
    if results:
        track = results[0]
        print(f"Found: {track['title']} - {track['artist']} (ID: {track['id']})")
        print("Extracting stream...")
        details = await youtube_extractor.extract(track['id'])
        if details:
            print(f"Success! Stream URL: {details['stream_url'][:60]}...")
        else:
            print("Extraction failed.")
    else:
        print("Search failed.")

if __name__ == "__main__":
    asyncio.run(test_jiosaavn_decryption())
    asyncio.run(test_youtube_extraction())
