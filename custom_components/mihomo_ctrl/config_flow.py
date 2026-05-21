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
                vol.Optional("enable_physical_switch", default=False): bool,
                vol.Optional("ssh_host", default="192.168.2.1"): str,
                vol.Optional("ssh_user", default="root"): str,
                vol.Optional("ssh_key", default="/config/sshkeys/id_rsa_ha"): str,
            }),
            errors=errors,
        )
