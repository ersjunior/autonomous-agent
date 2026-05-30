"""Real-time monitoring WebSocket endpoint."""

import asyncio

import redis.asyncio as redis
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from agents.events import AGENT_EVENTS_CHANNEL
from app.core.config import settings

router = APIRouter(prefix="/monitoring", tags=["monitoring"])


class ConnectionManager:
    """Manages active WebSocket connections and Redis pub/sub listener."""

    def __init__(self) -> None:
        self.active_connections: list[WebSocket] = []
        self._listener_task: asyncio.Task | None = None

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.append(websocket)
        if self._listener_task is None or self._listener_task.done():
            self._listener_task = asyncio.create_task(self._redis_listener())

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: str) -> None:
        dead: list[WebSocket] = []
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception:
                dead.append(connection)
        for conn in dead:
            self.disconnect(conn)

    async def _redis_listener(self) -> None:
        client = redis.from_url(settings.redis_url, decode_responses=True)
        pubsub = client.pubsub()
        await pubsub.subscribe(AGENT_EVENTS_CHANNEL)
        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    await self.broadcast(message["data"])
        finally:
            await pubsub.unsubscribe(AGENT_EVENTS_CHANNEL)
            await pubsub.aclose()
            await client.aclose()


manager = ConnectionManager()


@router.websocket("/ws")
async def monitoring_ws(websocket: WebSocket) -> None:
    """WebSocket feed of agent events from Redis pub/sub."""
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
