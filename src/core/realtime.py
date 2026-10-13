"""
WebSocket fan-out for live chat and notifications.

Events are queued on the DB session and pushed only after the transaction commits,
so clients never see data that was rolled back. Connections are tracked per process.
"""
import asyncio
import json
import os
from collections import defaultdict

from fastapi import WebSocket
from fastapi.encoders import jsonable_encoder
from sqlalchemy import event
from sqlalchemy.orm import Session
from starlette.websockets import WebSocketDisconnect, WebSocketState

from src.helpers.logging_config import get_logger

logger = get_logger(__name__)

# Strong references to in-flight send tasks (the event loop only keeps weak ones).
_pending: set[asyncio.Task] = set()


class ConnectionManager:
    def __init__(self):
        self._connections: dict[int, set[WebSocket]] = defaultdict(set)

    async def connect(self, user_id: int, websocket: WebSocket):
        await websocket.accept()
        self._connections[user_id].add(websocket)

    def disconnect(self, user_id: int, websocket: WebSocket):
        self._connections[user_id].discard(websocket)
        if not self._connections[user_id]:
            self._connections.pop(user_id, None)

    def is_online(self, user_id: int) -> bool:
        return user_id in self._connections

    async def send(self, user_id: int, payload: dict):
        data = jsonable_encoder(payload)  # datetimes, Decimals, ... -> JSON-safe
        for websocket in list(self._connections.get(user_id, ())):
            if websocket.client_state != WebSocketState.CONNECTED:
                self.disconnect(user_id, websocket)
                continue
            try:
                await websocket.send_json(data)
            except (WebSocketDisconnect, RuntimeError, ConnectionError):
                self.disconnect(user_id, websocket)
            except Exception:
                logger.exception("Failed to push a realtime event")


manager = ConnectionManager()


def queue_event(db_session, user_id: int, payload: dict):
    """Queue a realtime event on an AsyncSession (or Session); sent after commit."""
    sync_session = getattr(db_session, "sync_session", db_session)
    sync_session.info.setdefault("realtime_events", []).append((user_id, payload))


def _schedule(coro):
    task = asyncio.get_running_loop().create_task(coro)
    _pending.add(task)
    task.add_done_callback(_pending.discard)


# ---- cross-process fan-out (PostgreSQL LISTEN/NOTIFY) -----------------------------------------
# With several worker processes a receiver's socket may live in another process. Each process
# LISTENs on one channel; events are NOTIFYed after commit and every process delivers to the
# sockets it holds. Without a running listener (scripts, tests without lifespan) delivery is local.

CHANNEL = "smart_agri_realtime"
MAX_NOTIFY_BYTES = 7900  # PostgreSQL's NOTIFY payload limit is 8000 bytes


class _PubSub:
    def __init__(self):
        self.conn = None
        self.watchdog: asyncio.Task | None = None
        self.dsn: str | None = None

    @property
    def active(self) -> bool:
        return self.conn is not None and not self.conn.is_closed()

    def _on_notify(self, _conn, _pid, _channel, raw: str):
        try:
            message = json.loads(raw)
            _schedule(manager.send(int(message["u"]), message["p"]))
        except Exception:
            logger.exception("Bad realtime notification payload")

    async def _connect(self):
        import asyncpg

        self.conn = await asyncpg.connect(self.dsn)
        await self.conn.add_listener(CHANNEL, self._on_notify)

    async def _watch(self):
        while True:
            await asyncio.sleep(15)
            if not self.active:
                try:
                    await self._connect()
                    logger.info("Realtime listener reconnected.")
                except Exception as e:
                    logger.warning(f"Realtime listener reconnect failed: {e}")

    async def start(self, dsn: str):
        self.dsn = dsn
        try:
            await self._connect()
        except Exception as e:  # keep serving; local delivery still works
            logger.warning(f"Realtime listener unavailable, delivering in-process only: {e}")
        self.watchdog = asyncio.get_running_loop().create_task(self._watch())

    async def stop(self):
        if self.watchdog:
            self.watchdog.cancel()
        if self.active:
            await self.conn.close()
        self.conn = None

    async def publish(self, user_id: int, payload: dict):
        raw = json.dumps({"u": user_id, "p": jsonable_encoder(payload)}, default=str)
        if not self.active or len(raw.encode()) > MAX_NOTIFY_BYTES:
            await manager.send(user_id, payload)
            return
        try:
            # Publish via the pool: the listener connection is dedicated to LISTEN and can't run
            # concurrent queries.
            from sqlalchemy import text
            from src.db_connections.database import async_engine

            async with async_engine.connect() as conn:
                await conn.execute(text("SELECT pg_notify(:channel, :payload)"), {"channel": CHANNEL, "payload": raw})
                await conn.commit()
        except Exception:
            logger.exception("pg_notify failed; delivering in-process")
            await manager.send(user_id, payload)


pubsub = _PubSub()


async def start_pubsub():
    if os.getenv("REALTIME_PUBSUB", "true").lower() == "false":
        return
    from src.db_connections.database import SQLALCHEMY_DATABASE_URL_ASYNC

    await pubsub.start(SQLALCHEMY_DATABASE_URL_ASYNC.replace("postgresql+asyncpg://", "postgresql://", 1))


async def stop_pubsub():
    await pubsub.stop()


@event.listens_for(Session, "after_commit")
def _flush_realtime_events(session: Session):
    events = session.info.pop("realtime_events", None)
    if not events:
        return
    try:
        asyncio.get_running_loop()
    except RuntimeError:  # committed outside an event loop (scripts, migrations): nobody to notify
        return
    for user_id, payload in events:
        _schedule(pubsub.publish(user_id, payload))


@event.listens_for(Session, "after_rollback")
def _drop_realtime_events(session: Session):
    session.info.pop("realtime_events", None)
