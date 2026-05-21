import asyncio
import json
import aiohttp
from typing import Any, Callable, Dict, List, Optional
from .const import LOGGER

class MihomoClient:
    """Async client to communicate with Mihomo/Clash external controller."""

    def __init__(self, url: str, token: Optional[str] = None) -> None:
        """Initialize the client."""
        # Ensure url starts with http:// or https:// and strip trailing slash
        if not url.startswith(("http://", "https://")):
            url = f"http://{url}"
        self.base_url = url.rstrip("/")
        
        # Determine ws_url
        if self.base_url.startswith("https://"):
            self.ws_base_url = self.base_url.replace("https://", "wss://")
        else:
            self.ws_base_url = self.base_url.replace("http://", "ws://")
            
        self.token = token
        self.session: Optional[aiohttp.ClientSession] = None
        self._ws_task: Optional[asyncio.Task] = None
        self._running = False
        
        # Real-time data storage
        self.down_speed = 0.0
        self.up_speed = 0.0
        self.connections_count = 0
        self.is_connected = False
        
        # Callbacks
        self._update_callbacks: List[Callable[[], None]] = []

    def _get_headers(self) -> Dict[str, str]:
        """Get headers for authentication."""
        headers = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    async def get_session(self) -> aiohttp.ClientSession:
        """Get or create an aiohttp ClientSession."""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    async def request(self, method: str, path: str, **kwargs: Any) -> Any:
        """Make a REST request."""
        session = await self.get_session()
        url = f"{self.base_url}/{path}"
        headers = self._get_headers()
        
        try:
            async with session.request(method, url, headers=headers, timeout=aiohttp.ClientTimeout(total=10), **kwargs) as response:
                if response.status == 204:
                    return True
                response.raise_for_status()
                return await response.json()
        except Exception as err:
            LOGGER.error("Error calling Mihomo API %s: %s", path, err)
            raise err

    async def async_get_proxies(self) -> Dict[str, Any]:
        """Fetch all proxy groups and nodes."""
        return await self.request("GET", "proxies")

    async def async_select_proxy(self, group: str, name: str) -> bool:
        """Select a proxy node for a specific strategy group."""
        import urllib.parse
        encoded_group = urllib.parse.quote(group, safe="")
        payload = {"name": name}
        # Mihomo API uses PUT to select node
        await self.request("PUT", f"proxies/{encoded_group}", json=payload)
        return True

    async def async_test_delay(self, group: str, url: str = "http://www.gstatic.com/generate_204", timeout: int = 5000) -> Dict[str, Any]:
        """Trigger latency test for a group."""
        import urllib.parse
        encoded_group = urllib.parse.quote(group, safe="")
        params = {"url": url, "timeout": str(timeout)}
        return await self.request("GET", f"proxies/{encoded_group}/delay", params=params)

    def register_update_callback(self, callback: Callable[[], None]) -> Callable[[], None]:
        """Register callback for WebSocket updates."""
        self._update_callbacks.append(callback)
        def remove_callback():
            self._update_callbacks.remove(callback)
        return remove_callback

    def _fire_callbacks(self) -> None:
        """Trigger all registered entity update callbacks."""
        for callback in self._update_callbacks:
            try:
                callback()
            except Exception as err:
                LOGGER.error("Error in websocket callback: %s", err)

    def start_websocket_loop(self, hass: Any) -> None:
        """Start the background task to stream traffic and connections."""
        self._running = True
        self._ws_task = hass.async_create_background_task(
            self._websocket_loop(), "mihomo_websocket_loop"
        )

    async def _websocket_loop(self) -> None:
        """Maintain persistent WebSockets connections with exponential backoff."""
        backoff = 2
        while self._running:
            try:
                session = await self.get_session()
                headers = self._get_headers()
                
                # We connect to /traffic endpoint
                traffic_url = f"{self.ws_base_url}/traffic"
                conn_url = f"{self.ws_base_url}/connections"
                
                LOGGER.debug("Connecting to Mihomo WebSocket: %s", traffic_url)
                
                async with session.ws_connect(traffic_url, headers=headers) as traffic_ws:
                    self.is_connected = True
                    self._fire_callbacks()
                    backoff = 2  # Reset backoff on success
                    
                    # We will poll connection count from another task or just handle speed here
                    # Actually we can do both by wrapping them or multiplexing.
                    # Since we want to be hyper-efficient, we run a sub-listener for connections in parallel.
                    conn_task = asyncio.create_task(self._listen_connections(session, conn_url, headers))
                    
                    async for msg in traffic_ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            data = json.loads(msg.data)
                            self.up_speed = float(data.get("up", 0))
                            self.down_speed = float(data.get("down", 0))
                            self._fire_callbacks()
                        elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                            break
                            
                    conn_task.cancel()
                    
            except Exception as err:
                LOGGER.debug("Mihomo WebSocket connection error: %s. Retrying in %ss", err, backoff)
                
            self.is_connected = False
            self.up_speed = 0.0
            self.down_speed = 0.0
            self.connections_count = 0
            self._fire_callbacks()
            
            if not self._running:
                break
                
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)

    async def _listen_connections(self, session: aiohttp.ClientSession, url: str, headers: dict) -> None:
        """Listens to active connection counts via WebSocket."""
        try:
            async with session.ws_connect(url, headers=headers) as ws:
                async for msg in ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        data = json.loads(msg.data)
                        # data.get("connections") is a list of active sockets
                        connections = data.get("connections", [])
                        self.connections_count = len(connections)
                        self._fire_callbacks()
        except Exception as err:
            LOGGER.debug("Connections WebSocket error: %s", err)

    async def async_close(self) -> None:
        """Shutdown client and close tasks."""
        self._running = False
        if self._ws_task:
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass
        if self.session and not self.session.closed:
            await self.session.close()
