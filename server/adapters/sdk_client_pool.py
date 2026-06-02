"""SDK Client Session Pool.

ClaudeSDKClient 是有状态的——多轮对话靠它维持内存中的 session 上下文。
Pool 按 (conversation_id, agent_id) 缓存 client 实例，TTL 30 分钟自动回收。

Why: SDK client 不能每轮请求 new 一个（会丢失上下文），也不能永久常驻（内存泄漏）。
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient

logger = logging.getLogger("agenthub.adapters.sdk_pool")

DEFAULT_TTL = 1800       # 30 minutes idle → evict
DEFAULT_MAX_SIZE = 50    # max concurrent clients


@dataclass
class _Entry:
    client: ClaudeSDKClient
    last_used: float = field(default_factory=time.monotonic)
    conversation_id: str = ""
    agent_id: str = ""


class SDKClientPool:
    """按 (conversation_id, agent_id) 缓存 ClaudeSDKClient。

    用法::

        pool = SDKClientPool()
        client = await pool.get_or_create("conv_1", "agent_x", options, "sk-xxx")
        await client.query("你好")
        async for msg in client.receive_response():
            ...
    """

    def __init__(self, max_size: int = DEFAULT_MAX_SIZE, ttl: float = DEFAULT_TTL) -> None:
        self._pool: dict[tuple[str, str], _Entry] = {}
        self._max_size = max_size
        self._ttl = ttl
        self._lock = asyncio.Lock()

    async def get_or_create(
        self,
        conversation_id: str,
        agent_id: str,
        options: ClaudeAgentOptions,
        api_key: str,
    ) -> ClaudeSDKClient:
        key = (conversation_id, agent_id)

        # Fast path: check without lock (safe in asyncio single-threaded context)
        entry = self._pool.get(key)
        if entry is not None:
            entry.last_used = time.monotonic()
            return entry.client

        # Slow path: create client and connect OUTSIDE the lock
        client = ClaudeSDKClient(options=options)
        await client.connect()

        async with self._lock:
            # Double-check: another task may have created it while we connected
            entry = self._pool.get(key)
            if entry is not None:
                entry.last_used = time.monotonic()
                try:
                    await client.disconnect()
                except Exception:
                    logger.debug("SDK client disconnect error (ignored)", exc_info=True)
                return entry.client

            await self._evict_lru()

            self._pool[key] = _Entry(
                client=client,
                conversation_id=conversation_id,
                agent_id=agent_id,
            )
            logger.info(
                "SDK client created: conv=%s agent=%s (pool=%d)",
                conversation_id[:8], agent_id[:8], len(self._pool),
            )
            return client

    def get(self, conversation_id: str, agent_id: str) -> ClaudeSDKClient | None:
        entry = self._pool.get((conversation_id, agent_id))
        return entry.client if entry else None

    async def evict(self, conversation_id: str, agent_id: str) -> None:
        key = (conversation_id, agent_id)
        async with self._lock:
            entry = self._pool.pop(key, None)
            if entry:
                try:
                    await entry.client.disconnect()
                except Exception:
                    logger.debug("SDK client disconnect error (ignored)", exc_info=True)
                logger.debug("SDK client evicted: conv=%s agent=%s", conversation_id[:8], agent_id[:8])

    async def evict_all(self) -> None:
        async with self._lock:
            for key, entry in list(self._pool.items()):
                try:
                    await entry.client.disconnect()
                except Exception:
                    pass
            self._pool.clear()
            logger.info("All SDK clients evicted (pool shutdown)")

    async def _evict_lru(self) -> None:
        now = time.monotonic()
        expired = [k for k, v in self._pool.items() if now - v.last_used > self._ttl]
        for k in expired:
            entry = self._pool.pop(k, None)
            if entry:
                try:
                    await entry.client.disconnect()
                except Exception:
                    pass
                logger.debug("SDK client expired: %s", k)

        while len(self._pool) >= self._max_size:
            oldest_key = min(self._pool, key=lambda k: self._pool[k].last_used)
            entry = self._pool.pop(oldest_key, None)
            if entry:
                try:
                    await entry.client.disconnect()
                except Exception:
                    pass


_pools: dict[int, SDKClientPool] = {}
_locks: dict[int, asyncio.Lock] = {}


async def get_sdk_pool() -> SDKClientPool:
    loop_id = id(asyncio.get_running_loop())
    pool = _pools.get(loop_id)
    if pool is not None:
        return pool

    lock = _locks.setdefault(loop_id, asyncio.Lock())
    async with lock:
        pool = _pools.get(loop_id)
        if pool is None:
            pool = SDKClientPool()
            _pools[loop_id] = pool
        return pool
