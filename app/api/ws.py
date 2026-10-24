"""Live WebSocket endpoint for dashboard clients."""
import asyncio
import jwt
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from app.core.security import decode_token
from app.services.websocket import broadcaster

router = APIRouter(tags=["WebSocket"])


@router.websocket("/ws/live")
async def websocket_live_endpoint(websocket: WebSocket):
    """
    Real-time event stream: detection.created, detection.updated, health.updated.
    Authenticates via ?token=JWT query parameter.
    Pings every 20 seconds. Bounded queue per client prevents blocking.
    """
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Missing token")
        return

    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid token type")
            return
    except (jwt.PyJWTError, Exception):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid or expired token")
        return

    queue = await broadcaster.connect(websocket)
    writer_task = asyncio.create_task(broadcaster.client_writer(websocket, queue))

    try:
        while True:
            # Keep reading from client to detect disconnects and handle pongs
            data = await websocket.receive_text()
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        writer_task.cancel()
        await broadcaster.disconnect(websocket)
