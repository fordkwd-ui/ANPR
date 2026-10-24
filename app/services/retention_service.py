"""Media retention service: purges media objects older than MEDIA_RETENTION_DAYS."""
from datetime import datetime, timedelta, timezone
import logging
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import get_settings
from app.models.detection import Media
from app.services.storage.base import StorageDriver

logger = logging.getLogger(__name__)


class RetentionService:
    @staticmethod
    async def purge_old_media(
        db: AsyncSession,
        storage: StorageDriver,
        retention_days: Optional[int] = None,
    ) -> int:
        """
        Finds media objects older than retention_days (default 90 days),
        deletes the underlying binary file from storage, and sets object_key to NULL.
        The media database records and detection records are kept intact.
        Returns count of purged media files.
        """
        settings = get_settings()
        days = retention_days if retention_days is not None else settings.MEDIA_RETENTION_DAYS
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        stmt = (
            select(Media)
            .where(
                Media.created_at < cutoff,
                Media.object_key.isnot(None),
            )
        )
        result = await db.execute(stmt)
        old_media_list = result.scalars().all()

        purged_count = 0
        for media_item in old_media_list:
            if media_item.object_key:
                try:
                    await storage.delete_file(media_item.object_key)
                except Exception as e:
                    logger.warning(f"Failed to delete {media_item.object_key} from storage: {e}")
                media_item.object_key = None
                purged_count += 1

        await db.commit()
        logger.info(f"Purged {purged_count} media objects older than {days} days")
        return purged_count
