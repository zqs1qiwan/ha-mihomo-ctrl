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
