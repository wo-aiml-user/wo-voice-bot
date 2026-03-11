"""
Standalone script to run the complete data scraping + RAG indexing pipeline.
Run this from the project root: python run_pipeline.py
"""
import sys
import os

# Ensure project root is in sys.path for imports
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import asyncio
from data_scraping_pipeline.config import settings
from data_scraping_pipeline.indexing.vector_store import connect_to_mongodb, disconnect_from_mongodb
from data_scraping_pipeline.scraping.pipeline import run_pipeline

async def main():
    print("🔌 Connecting to MongoDB Atlas...")
    try:
        connect_to_mongodb()
        print("✅ Connected to MongoDB Atlas successfully!")
        
        print("🚀 Starting data scraping pipeline...")
        await run_pipeline()
        print("✅ Data scraping and indexing completed!")
        
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        print("🔌 Disconnecting from MongoDB...")
        disconnect_from_mongodb()
        print("✅ Disconnected!")

if __name__ == "__main__":
    asyncio.run(main())
