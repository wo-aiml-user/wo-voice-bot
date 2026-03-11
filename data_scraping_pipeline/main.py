"""
Data Scraping Pipeline Main Entry Point

This module provides the main entry point for the data scraping pipeline,
including scheduler configuration for automated daily runs.
"""
import asyncio
from loguru import logger
from app.data_scraping_pipeline.config import settings
from contextlib import asynccontextmanager
from apscheduler.triggers.cron import CronTrigger
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.data_scraping_pipeline.logger import setup_logger
from app.data_scraping_pipeline.scraping.pipeline import run_pipeline

# Initialize scheduler
scheduler = AsyncIOScheduler()


def start_scheduler():
    """Start the APScheduler with the data scraping pipeline job."""
    try:
        # Schedule data scraping pipeline to run daily at midnight
        scheduler.add_job(
            run_pipeline,
            trigger=CronTrigger(hour=0, minute=0),
            id="pipeline_cron_job",
            max_instances=1,
            misfire_grace_time=900,
        )
        
        scheduler.start()
        logger.info("Data scraping pipeline scheduler started - runs daily at 00:00")
        
    except Exception as e:
        logger.error(f"Failed to start scheduler: {str(e)}")
        raise


def stop_scheduler():
    """Stop the APScheduler."""
    try:
        if scheduler.running:
            scheduler.shutdown()
            logger.info("Data scraping pipeline scheduler stopped")
    except Exception as e:
        logger.error(f"Error stopping scheduler: {str(e)}")


async def main():
    """Main entry point for standalone execution."""
    setup_logger(settings.LOG_LEVEL)
    logger.info("Starting data scraping pipeline in standalone mode...")
    
    try:
        # Run pipeline once
        await run_pipeline()
        logger.info("Pipeline execution completed.")
        
    except Exception as e:
        logger.error(f"Pipeline execution failed: {str(e)}", exc_info=True)
        raise


if __name__ == "__main__":
    asyncio.run(main())
