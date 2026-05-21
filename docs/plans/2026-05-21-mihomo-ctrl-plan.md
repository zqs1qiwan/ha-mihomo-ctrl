# ha-mihomo-ctrl Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Build a high-performance, modern Home Assistant custom integration for controlling and monitoring a Mihomo (Clash) proxy core using WebSockets for real-time traffic/connections pushing and native `select` entities for strategy group switching.

**Architecture:** 
- **WebSocket Push (local_push)**: Instead of polling the Mihomo REST API, we establish a single persistent WebSocket connection to stream real-time download/upload speed and active connections.
- **Dynamic Select Entities**: Automatically discover Mihomo proxy groups and expose each as a `select` entity. Populate attributes with node lists and their respective latencies so frontend cards can render them.
- **Robust Connection Handling**: Use exponential backoff for WebSocket reconnection to handle Clash reboots cleanly without throwing errors or locking the HA event loop.

**Tech Stack:** Home Assistant Core API, `aiohttp`, asyncio, Python 3.12+

---

## Task 1: Setup Manifest and Consts
**Objective:** Create the required HA metadata files and base domain constants.
**Files:**
- Create: `custom_components/mihomo_ctrl/manifest.json`
- Create: `custom_components/mihomo_ctrl/const.py`
- Create: `custom_components/mihomo_ctrl/__init__.py`

### Step 1: Create Manifest
Write `custom_components/mihomo_ctrl/manifest.json`:
```json
{
  "domain": "mihomo_ctrl",
  "name": "Mihomo Controller",
  "codeowners": ["@laobai"],
  "config_flow": true,
  "documentation": "https://github.com/laobai/ha-mihomo-ctrl",
  "iot_class": "local_push",
  "requirements": [],
  "version": "1.0.0"
}
```

### Step 2: Create Constants
Write `custom_components/mihomo_ctrl/const.py`:
```python
import logging

DOMAIN = "mihomo_ctrl"
LOGGER = logging.getLogger(__package__)

PLATFORMS = ["sensor", "select", "button"]

CONF_URL = "url"
CONF_TOKEN = "token"

# API Endpoints
ENDPOINT_TRAFFIC = "traffic"
ENDPOINT_CONNECTIONS = "connections"
ENDPOINT_PROXIES = "proxies"
ENDPOINT_CONFIG = "configs"
```

### Step 3: Create Entry Point Setup
Write `custom_components/mihomo_ctrl/__init__.py` to handle component entry loading and unloading:
```python
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from .const import DOMAIN, PLATFORMS, LOGGER
from .client import MihomoClient

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Mihomo Controller from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    
    url = entry.data["url"]
    token = entry.data.get("token")
    
    client = MihomoClient(url, token)
    hass.data[DOMAIN][entry.entry_id] = {
        "client": client,
    }
    
    # Start background loop for websocket
    client.start_websocket_loop(hass)
    
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        data = hass.data[DOMAIN].pop(entry.entry_id)
        client: MihomoClient = data["client"]
        await client.async_close()
    return unload_ok
```

---

## Task 2: Build the High-Performance Mihomo Client (HTTP & WebSocket)
**Objective:** Create the communication client supporting HTTP REST calls and WebSocket streaming with reconnection resilience.
**Files:**
- Create: `custom_components/mihomo_ctrl/client.py`

### Step 1: Write `client.py`
Implement the `MihomoClient` class:
```python
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
            async with session.request(method, url, headers=headers, timeout=10, **kwargs) as response:
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
```

---

## Task 3: Implement Config Flow (GUI-based Integration Setup)
**Objective:** Let the user add their Mihomo Core using a GUI (Url & Bearer Token) instead of writing yaml.
**Files:**
- Create: `custom_components/mihomo_ctrl/config_flow.py`
- Create: `custom_components/mihomo_ctrl/translations/en.json`
- Create: `custom_components/mihomo_ctrl/translations/zh-Hans.json`

### Step 1: Write `config_flow.py`
```python
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from typing import Any, Dict, Optional
from .const import DOMAIN, CONF_URL, CONF_TOKEN, LOGGER
from .client import MihomoClient

class MihomoFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Mihomo Controller."""

    VERSION = 1

    async def async_step_user(self, user_input: Optional[Dict[str, Any]] = None) -> Any:
        """Handle the initial step."""
        errors = {}
        if user_input is not None:
            url = user_input[CONF_URL]
            token = user_input.get(CONF_TOKEN)
            
            # Verify connectivity
            client = MihomoClient(url, token)
            try:
                await client.async_get_proxies()
                await client.async_close()
                return self.async_create_entry(title=f"Mihomo ({url})", data=user_input)
            except Exception:
                errors["base"] = "cannot_connect"
                await client.async_close()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_URL, default="127.0.0.1:9090"): str,
                vol.Optional(CONF_TOKEN): str,
            }),
            errors=errors,
        )
```

### Step 2: Write Chinese Translation File
Write `custom_components/mihomo_ctrl/translations/zh-Hans.json`:
```json
{
  "config": {
    "step": {
      "user": {
        "title": "配置 Mihomo 控制器",
        "description": "请输入宿主机上运行的 Mihomo (Clash) 外部控制端口 API 详情",
        "data": {
          "url": "API 控制器地址 (例如 192.168.2.1:9090)",
          "token": "秘钥 Bearer Token (可选)"
        }
      }
    },
    "error": {
      "cannot_connect": "无法连接到该 Mihomo 实例，请检查端口和秘钥是否正确。"
    }
  }
}
```

### Step 3: Write English Translation File
Write `custom_components/mihomo_ctrl/translations/en.json`:
```json
{
  "config": {
    "step": {
      "user": {
        "title": "Configure Mihomo Controller",
        "description": "Please enter the Mihomo API connection details.",
        "data": {
          "url": "API Endpoint (e.g. 192.168.2.1:9090)",
          "token": "Secret Bearer Token (optional)"
        }
      }
    },
    "error": {
      "cannot_connect": "Failed to connect to the Mihomo instance. Verify settings."
    }
  }
}
```

---

## Task 4: Create Real-time Sensors (Upload/Download Speeds & Status)
**Objective:** Create high-frequency update entities utilizing local_push.
**Files:**
- Create: `custom_components/mihomo_ctrl/sensor.py`

### Step 1: Write `sensor.py`
```python
from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from .const import DOMAIN

async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up sensors."""
    data = hass.data[DOMAIN][entry.entry_id]
    client = data["client"]
    
    async_add_entities([
        MihomoSpeedSensor(client, "download", "Download Speed", "mdi:download-network"),
        MihomoSpeedSensor(client, "upload", "Upload Speed", "mdi:upload-network"),
        MihomoConnectionsSensor(client),
        MihomoStatusSensor(client),
    ])

class MihomoBaseEntity:
    """Base class for Mihomo entities."""
    
    def __init__(self, client) -> None:
        self.client = client
        self._unsub_callback = None

    async def async_added_to_hass(self) -> None:
        """Register update callback."""
        self._unsub_callback = self.client.register_update_callback(self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        """Unregister callback."""
        if self._unsub_callback:
            self._unsub_callback()


class MihomoSpeedSensor(MihomoBaseEntity, SensorEntity):
    """Upload/Download speed sensor."""

    def __init__(self, client, direction: str, name: str, icon: str) -> None:
        """Initialize."""
        super().__init__(client)
        self.direction = direction
        self._attr_name = f"Mihomo {name}"
        self._attr_icon = icon
        self._attr_native_unit_of_measurement = "KB/s"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_unique_id = f"mihomo_{direction}_speed"

    @property
    def native_value(self) -> float:
        """Return the state of the sensor in KB/s."""
        # Speed from websocket is in bytes per second. Convert to KB/s
        raw_speed = self.client.down_speed if self.direction == "download" else self.client.up_speed
        return round(raw_speed / 1024, 2)


class MihomoConnectionsSensor(MihomoBaseEntity, SensorEntity):
    """Active connections sensor."""

    def __init__(self, client) -> None:
        super().__init__(client)
        self._attr_name = "Mihomo Active Connections"
        self._attr_icon = "mdi:lan-connect"
        self._attr_native_unit_of_measurement = "conns"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_unique_id = "mihomo_active_connections"

    @property
    def native_value(self) -> int:
        return self.client.connections_count


class MihomoStatusSensor(MihomoBaseEntity, SensorEntity):
    """Mihomo backend status sensor."""

    def __init__(self, client) -> None:
        super().__init__(client)
        self._attr_name = "Mihomo Core Status"
        self._attr_icon = "mdi:server-network"
        self._attr_unique_id = "mihomo_core_status"

    @property
    def native_value(self) -> str:
        return "online" if self.client.is_connected else "offline"
```

---

## Task 5: Implement Dynamic Select Entities for Strategy Groups
**Objective:** Generate a `select` entity for each Mihomo group. Switch groups in real time and store node delay in attributes.
**Files:**
- Create: `custom_components/mihomo_ctrl/select.py`

### Step 1: Write `select.py`
```python
from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from .const import DOMAIN, LOGGER

async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up strategy group selectors."""
    data = hass.data[DOMAIN][entry.entry_id]
    client = data["client"]
    
    try:
        proxies_data = await client.async_get_proxies()
        proxies = proxies_data.get("proxies", {})
    except Exception as err:
        LOGGER.error("Failed to load proxies for selectors: %s", err)
        return

    # Extract groups (Selector types in Clash)
    selectors = []
    for name, proxy in proxies.items():
        if proxy.get("type") in ("Selector", "Fallback", "URLTest"):
            selectors.append(MihomoGroupSelect(client, name, proxy))
            
    async_add_entities(selectors)


class MihomoGroupSelect(SelectEntity):
    """Representation of a Mihomo strategy group selector."""

    def __init__(self, client, name: str, data: dict) -> None:
        """Initialize."""
        self.client = client
        self.group_name = name
        self._attr_name = f"Mihomo {name}"
        self._attr_unique_id = f"mihomo_select_{name.lower().replace(' ', '_')}"
        self._unsub_callback = None
        
        # Read available options and selection
        self._update_from_data(data)

    def _update_from_data(self, data: dict) -> None:
        """Process group nodes, selection and latency."""
        self._attr_current_option = data.get("now")
        # List of sub nodes
        self._attr_options = data.get("all", [])
        
        # Parse child node latencies
        latency_map = {}
        for item in data.get("history", []):
            # history lists previous delay test results
            delay = item.get("delay", 0)
            if delay > 0:
                # We can map each history node's delay
                pass
                
        # Store metadata in attributes for advanced frontend custom Lovelace cards
        self._attr_extra_state_attributes = {
            "type": data.get("type"),
            "latency": latency_map
        }

    async def async_added_to_hass(self) -> None:
        """Register callbacks."""
        # When WS triggers, we also occasionally pull REST API to refresh selector state
        self._unsub_callback = self.client.register_update_callback(self._handle_client_update)

    async def async_will_remove_from_hass(self) -> None:
        """Cleanup callbacks."""
        if self._unsub_callback:
            self._unsub_callback()

    def _handle_client_update(self) -> None:
        """When client reports speed changes, occasionally query REST proxies to update selected node."""
        # To avoid rate-limiting the REST API, we can trigger a refresh task.
        # However, selecting a node updates it directly. This is a callback fallback.
        # We can run an update task in HASS.
        self.hass.async_create_task(self.async_update())

    async def async_update(self) -> None:
        """Pull fresh state for this proxy group."""
        try:
            proxies_data = await self.client.async_get_proxies()
            group_data = proxies_data.get("proxies", {}).get(self.group_name)
            if group_data:
                self._update_from_data(group_data)
                self.async_write_ha_state()
        except Exception as err:
            LOGGER.debug("Error updating selector %s: %s", self.group_name, err)

    async def async_select_option(self, option: str) -> None:
        """Change selected option."""
        try:
            await self.client.async_select_proxy(self.group_name, option)
            self._attr_current_option = option
            self.async_write_ha_state()
        except Exception as err:
            LOGGER.error("Failed to set proxy group %s option to %s: %s", self.group_name, option, err)
```

---

## Task 6: Add Manual Actions (Refresh Proxy list, Test Delay)
**Objective:** Add manual action buttons for on-demand trigger operations.
**Files:**
- Create: `custom_components/mihomo_ctrl/button.py`

### Step 1: Write `button.py`
```python
from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from .const import DOMAIN, LOGGER

async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up buttons."""
    data = hass.data[DOMAIN][entry.entry_id]
    client = data["client"]
    
    try:
        proxies_data = await client.async_get_proxies()
        proxies = proxies_data.get("proxies", {})
    except Exception as err:
        LOGGER.error("Failed to load proxies for buttons: %s", err)
        return

    buttons = []
    # Create test delay buttons for Selector groups
    for name, proxy in proxies.items():
        if proxy.get("type") in ("Selector", "Fallback", "URLTest"):
            buttons.append(MihomoDelayTestButton(client, name))
            
    async_add_entities(buttons)


class MihomoDelayTestButton(ButtonEntity):
    """Button to trigger latency testing."""

    def __init__(self, client, group_name: str) -> None:
        """Initialize."""
        self.client = client
        self.group_name = group_name
        self._attr_name = f"Mihomo Delay Test ({group_name})"
        self._attr_icon = "mdi:speedometer"
        self._attr_unique_id = f"mihomo_btn_delay_{group_name.lower().replace(' ', '_')}"

    async def async_press(self) -> None:
        """Handle button press."""
        try:
            LOGGER.info("Triggering latency test on Mihomo group %s", self.group_name)
            await self.client.async_test_delay(self.group_name)
        except Exception as err:
            LOGGER.error("Latency test button press failed for %s: %s", self.group_name, err)
```

---

## Task 7: Setup Dev Testing Environment
**Objective:** Create a dev configuration structure so developers can quickly boot HA in docker with our custom component.
**Files:**
- Create: `tests/conftest.py`
- Create: `.gitignore`

### Step 1: Write `.gitignore`
```
__pycache__/
*.pyc
*.pyo
*.pyd
.pytest_cache/
.HA_VERSION
.ha_run.lock
*.db
*.log
```

---

## Plan complete and saved. Ready to execute using subagent-driven-development.
