"""Client for the trading engine's read-only status API.

Mirrors `poc/trading_engine/status_api.py`. Everything here is a GET; the
engine exposes no write surface and this client must not grow one — the
engine's control path is its ZMQ intent socket, and a run is started and
stopped through `RunSupervisor`, not over HTTP.

"The engine is not running" is the normal case, not an error: most of the time
there is no run in flight. So the methods raise one specific exception for it
and the routes turn that into a quiet "no run" rather than a 500.
"""
import logging
from typing import Any
from typing import Optional

import httpx

log = logging.getLogger("finhub.engine")


class EngineUnavailable(RuntimeError):
    """No engine answered. Usually means no run is in flight."""


class EngineClient:
    def __init__(self, base_url: str, timeout: float = 5.0):
        self.base_url = base_url.rstrip("/")
        # Short by default. These are all in-memory reads on the engine's side
        # except /roundtrips, which it caches for 2s behind one broker call, so
        # anything slower than this means the engine is wedged and the UI is
        # better off being told than waiting.
        self.timeout = timeout

    async def _get(self, path: str, params: Optional[dict] = None) -> Any:
        url = f"{self.base_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(url, params=params)
        except httpx.RequestError as exc:
            raise EngineUnavailable(f"{url}: {exc}") from exc
        if resp.status_code == 404:
            return None
        if resp.status_code >= 400:
            raise EngineUnavailable(f"{url}: HTTP {resp.status_code}")
        return resp.json()

    async def is_up(self) -> bool:
        try:
            await self._get("/health")
            return True
        except EngineUnavailable:
            return False

    async def health(self) -> dict:
        return await self._get("/health")

    async def status(self) -> dict:
        """Everything about the run in one read: config, progress, equity,
        risk, and each bot's last report."""
        return await self._get("/status")

    async def bots(self) -> dict:
        """bot_id -> its last report, or None for a bot that never spoke."""
        return await self._get("/bots")

    async def bot_history(self, bot_id: str, limit: int = 0) -> Optional[dict]:
        """That bot's recent per-bar reports. None when the id is unknown.

        The engine's buffer is shared across bots and bounded, so this answers
        "what was it doing just before that", not "replay the run".
        """
        return await self._get(f"/bots/{bot_id}/history", {"limit": limit})

    async def equity(self, limit: int = 1000) -> dict:
        """The equity curve, newest `limit` samples. 0 means all of it."""
        return await self._get("/equity", {"limit": limit})

    async def roundtrips(self) -> dict:
        """Closed trades, win rate and realised P&L, computed live.

        The one engine call that leaves its process (it reads the broker's fill
        history), which is why the engine caches it. Do not poll faster than a
        second or two.
        """
        return await self._get("/roundtrips")
