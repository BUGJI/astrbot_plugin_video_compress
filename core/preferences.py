"""个人默认参数存储。

键值按“平台实例 + 会话 + 用户”隔离。QQ 官方机器人在不同群里的用户 openid
不同，因此个人默认只在当前群/会话内生效。
"""

from __future__ import annotations

from typing import Any


class PreferenceStore:
    """基于 AstrBot 插件 KV 的轻量缓存。"""

    def __init__(self, plugin: Any) -> None:
        self._plugin = plugin
        self._cache: dict[str, dict[str, Any]] = {}

    async def get(self, key: str) -> dict[str, Any]:
        if key in self._cache:
            return dict(self._cache[key])

        value = await self._plugin.get_kv_data(key, {})
        data = dict(value) if isinstance(value, dict) else {}
        self._cache[key] = data
        return dict(data)

    async def set(self, key: str, data: dict[str, Any]) -> None:
        stored = dict(data)
        await self._plugin.put_kv_data(key, stored)
        self._cache[key] = stored

    async def clear(self, key: str) -> None:
        await self._plugin.delete_kv_data(key)
        self._cache.pop(key, None)

    async def update(self, key: str, changes: dict[str, Any]) -> dict[str, Any]:
        data = await self.get(key)
        data.update(changes)
        await self.set(key, data)
        return data
