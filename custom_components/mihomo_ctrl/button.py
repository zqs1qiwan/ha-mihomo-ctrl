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
