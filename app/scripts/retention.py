"""Standalone script to execute daily media retention purge."""
import asyncio
import logging
from app.db.session import async_session_factory
from app.services.retention_service import RetentionService
from app.services.storage import get_storage

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("retention_job")


async def main() -> None:
    logger.info("Starting daily media retention cleanup...")
    storage = get_storage()
    async with async_session_factory() as db:
        purged = await RetentionService.purge_old_media(db, storage)
        logger.info(f"Retention job completed. Purged {purged} old media objects.")


if __name__ == "__main__":
    asyncio.run(main())
