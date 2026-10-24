"""
24/7 CCTV Continuous Recording Archive API endpoints.
Enables browsing, streaming, and downloading segmented MP4 recordings stored on disk.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

router = APIRouter(prefix="/recordings", tags=["recordings"])

RECORDINGS_DIR = Path("./recordings").resolve()


@router.get("", response_model=Dict[str, Any])
def list_recordings() -> Dict[str, Any]:
    """
    Lists all 24/7 continuous video recording segments on disk.
    Sorted by newest first.
    """
    if not RECORDINGS_DIR.exists():
        return {"total_count": 0, "total_size_mb": 0.0, "recordings": []}

    recordings = []
    total_bytes = 0

    # Directory layout: ./recordings/<YYYY-MM-DD>/<HH-MM-SS>.mp4 or subfolders
    for root, _, files in os.walk(RECORDINGS_DIR):
        for f in files:
            if f.endswith(".mp4") and not f.startswith("."):
                full_path = Path(root) / f
                try:
                    stat = full_path.stat()
                    size_b = stat.st_size
                    total_bytes += size_b
                    rel_path = full_path.relative_to(RECORDINGS_DIR)
                    parts = rel_path.parts
                    date_folder = parts[0] if len(parts) > 1 else "root"
                    sub_cam = parts[1] if len(parts) > 2 else None

                    recordings.append({
                        "filename": f,
                        "date": date_folder,
                        "camera": sub_cam or "Camera A (ANPR)",
                        "size_bytes": size_b,
                        "size_mb": round(size_b / (1024 * 1024), 2),
                        "modified_at": stat.st_mtime,
                        "rel_path": str(rel_path),
                        "stream_url": f"/api/v1/recordings/stream/{rel_path}",
                    })
                except Exception:
                    continue

    # Newest first
    recordings.sort(key=lambda r: r["modified_at"], reverse=True)

    return {
        "total_count": len(recordings),
        "total_size_mb": round(total_bytes / (1024 * 1024), 2),
        "recordings": recordings,
    }


@router.get("/stream/{full_rel_path:path}")
def stream_recording(full_rel_path: str, download: bool = Query(False)) -> FileResponse:
    """Streams or downloads an MP4 recording file."""
    target = (RECORDINGS_DIR / full_rel_path).resolve()

    # Path traversal protection
    if not str(target).startswith(str(RECORDINGS_DIR)) or not target.exists():
        raise HTTPException(status_code=404, detail="Recording segment not found")

    filename = target.name
    headers = {}
    if download:
        headers["Content-Disposition"] = f'attachment; filename="{filename}"'

    return FileResponse(
        str(target),
        media_type="video/mp4",
        filename=filename if download else None,
        headers=headers,
    )
