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
            selectors.append(MihomoGroupSelect(client, name, proxy, proxies))
            
    async_add_entities(selectors)


class MihomoGroupSelect(SelectEntity):
    """Representation of a Mihomo strategy group selector."""

    def __init__(self, client, name: str, data: dict, all_proxies: dict) -> None:
        """Initialize."""
        self.client = client
        self.group_name = name
        self._attr_name = f"Mihomo {name}"
        self._attr_unique_id = f"mihomo_select_{name.lower().replace(' ', '_')}"
        self._unsub_callback = None
        
        # Read available options and selection
        self._update_from_data(data, all_proxies)

    def _update_from_data(self, data: dict, all_proxies: dict) -> None:
        """Process group nodes, selection and latency."""
        self._attr_current_option = data.get("now")
        # List of sub nodes
        self._attr_options = data.get("all", [])
        
        # Parse child node latencies
        latency_map = {}
        for node_name in self._attr_options:
            node_info = all_proxies.get(node_name, {})
            history = node_info.get("history", [])
            if history:
                # history is a list of dicts with delay test results
                latest_delay = history[-1].get("delay", 0)
                if latest_delay > 0:
                    latency_map[node_name] = latest_delay
                
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
            all_proxies = proxies_data.get("proxies", {})
            group_data = all_proxies.get(self.group_name)
            if group_data:
                self._update_from_data(group_data, all_proxies)
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
