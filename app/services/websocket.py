"""Non-blocking WebSocket broadcaster with bounded queues and 20s ping loop."""
import asyncio
from datetime import datetime, timezone
import json
import logging
from typing import Any, Dict, Optional, Set
from fastapi import WebSocket, WebSocketDisconnect
from app.core.latency import latency_tracker

logger = logging.getLogger(__name__)


class WebSocketBroadcaster:
    """
    Manages active WebSocket connections.
    Uses bounded per-client queues to prevent slow clients from blocking ingestion.
    """

    def __init__(self, queue_maxsize: int = 100, ping_interval_seconds: int = 20):
        self.queue_maxsize = queue_maxsize
        self.ping_interval = ping_interval_seconds
        self._clients: Dict[WebSocket, asyncio.Queue] = {}
        self._lock = asyncio.Lock()
        self._ping_task: Optional[asyncio.Task] = None

    async def connect(self, websocket: WebSocket) -> asyncio.Queue:
        await websocket.accept()
        client_queue: asyncio.Queue = asyncio.Queue(maxsize=self.queue_maxsize)
        async with self._lock:
            self._clients[websocket] = client_queue
        return client_queue

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._clients.pop(websocket, None)

    async def broadcast(self, event_type: str, data: Dict[str, Any]) -> None:
        """
        Dispatches message non-blockingly to all connected clients.
        Attaches ws_sent_at for latency measurement.
        """
        now = datetime.now(timezone.utc)
        message = {
            "type": event_type,
            "data": data,
            "ws_sent_at": now.isoformat(),
        }

        # Record WS latency if captured_at is in data
        captured_at_str = data.get("captured_at")
        if captured_at_str:
            try:
                cap_dt = datetime.fromisoformat(captured_at_str)
                latency_tracker.record_event(cap_dt, now, ws_sent_at=now)
            except Exception:
                pass

        stale_sockets: Set[WebSocket] = set()
        async with self._lock:
            for ws, q in list(self._clients.items()):
                try:
                    q.put_nowait(message)
                except asyncio.QueueFull:
                    logger.warning("Dropping message for slow client and disconnecting")
                    stale_sockets.add(ws)

        for ws in stale_sockets:
            await self.disconnect(ws)
            try:
                await ws.close(code=1008, reason="Client too slow")
            except Exception:
                pass

    async def client_writer(self, websocket: WebSocket, queue: asyncio.Queue) -> None:
        """Loops pulling messages from per-client queue and writing to the socket."""
        try:
            while True:
                msg = await queue.get()
                await websocket.send_json(msg)
                queue.task_done()
        except (WebSocketDisconnect, asyncio.CancelledError):
            pass
        finally:
            await self.disconnect(websocket)

    async def _ping_loop(self) -> None:
        """Pings all connected clients every 20 seconds."""
        try:
            while True:
                await asyncio.sleep(self.ping_interval)
                await self.broadcast("ping", {"timestamp": datetime.now(timezone.utc).isoformat()})
        except asyncio.CancelledError:
            pass

    def start_background_tasks(self) -> None:
        if self._ping_task is None or self._ping_task.done():
            self._ping_task = asyncio.create_task(self._ping_loop())

    def stop_background_tasks(self) -> None:
        if self._ping_task and not self._ping_task.done():
            self._ping_task.cancel()


broadcaster = WebSocketBroadcaster()
