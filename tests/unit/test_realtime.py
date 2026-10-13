"""Realtime fan-out: payloads must be JSON-encoded, and a bad payload must not drop the connection."""
import asyncio
from datetime import datetime
from decimal import Decimal

from starlette.websockets import WebSocketState

from src.core.realtime import ConnectionManager


class FakeWebSocket:
    def __init__(self):
        self.client_state = WebSocketState.CONNECTED
        self.sent = []

    async def accept(self):
        pass

    async def send_json(self, data):
        import json

        json.dumps(data)  # raises like Starlette would for non-JSON types
        self.sent.append(data)


def test_send_encodes_datetimes_and_decimals():
    manager, ws = ConnectionManager(), FakeWebSocket()

    async def scenario():
        await manager.connect(7, ws)
        await manager.send(7, {"event": "message", "message": {"created_at": datetime(2026, 1, 2, 3, 4), "total": Decimal("12.50")}})

    asyncio.run(scenario())
    assert ws.sent == [{"event": "message", "message": {"created_at": "2026-01-02T03:04:00", "total": 12.5}}]
    assert manager.is_online(7)


def test_closed_sockets_are_dropped():
    manager, ws = ConnectionManager(), FakeWebSocket()

    async def scenario():
        await manager.connect(3, ws)
        ws.client_state = WebSocketState.DISCONNECTED
        await manager.send(3, {"event": "notification"})

    asyncio.run(scenario())
    assert not manager.is_online(3) and ws.sent == []
