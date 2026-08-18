import asyncio
import json
from collections import defaultdict
from typing import AsyncIterator

import redis.asyncio as aioredis


class EventBus:
    """Interface: fan-out of per-user 'something changed' events."""

    async def connect(self) -> None: ...

    async def close(self) -> None: ...

    async def publish(self, user_id: int, payload: dict) -> None:
        raise NotImplementedError

    def subscribe(self, user_id: int) -> AsyncIterator[dict]:
        raise NotImplementedError


class RedisEventBus(EventBus):
    """Redis pub/sub backed bus — works across multiple uvicorn workers."""

    def __init__(self, url: str):
        self._url = url
        self._redis: aioredis.Redis | None = None

    @staticmethod
    def _channel(user_id: int) -> str:
        return f"todoapi:user:{user_id}"

    async def connect(self) -> None:
        self._redis = aioredis.from_url(self._url, decode_responses=True)
        await self._redis.ping()

    async def close(self) -> None:
        if self._redis is not None:
            await self._redis.aclose()

    async def publish(self, user_id: int, payload: dict) -> None:
        assert self._redis is not None
        await self._redis.publish(self._channel(user_id), json.dumps(payload))

    async def subscribe(self, user_id: int) -> AsyncIterator[dict]:
        assert self._redis is not None
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(self._channel(user_id))
        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    yield json.loads(message["data"])
        finally:
            await pubsub.unsubscribe(self._channel(user_id))
            await pubsub.aclose()


class InMemoryEventBus(EventBus):
    """Single-process bus for tests."""

    def __init__(self):
        self._queues: dict[int, set[asyncio.Queue]] = defaultdict(set)

    async def publish(self, user_id: int, payload: dict) -> None:
        for queue in self._queues[user_id]:
            queue.put_nowait(payload)

    async def subscribe(self, user_id: int) -> AsyncIterator[dict]:
        queue: asyncio.Queue = asyncio.Queue()
        self._queues[user_id].add(queue)
        try:
            while True:
                yield await queue.get()
        finally:
            self._queues[user_id].discard(queue)
