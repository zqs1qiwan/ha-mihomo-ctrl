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
