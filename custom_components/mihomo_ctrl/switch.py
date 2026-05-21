"""Switch platform for Mihomo (Clash) Controller."""
import asyncio
from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from .const import DOMAIN, LOGGER

async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Mihomo switch platform."""
    data = entry.data
    enable_physical_switch = data.get("enable_physical_switch", False)
    if not enable_physical_switch:
        LOGGER.debug("Physical switch is not enabled for OpenClash")
        return

    ssh_host = data.get("ssh_host", "192.168.2.1")
    ssh_user = data.get("ssh_user", "root")
    ssh_key = data.get("ssh_key", "/config/sshkeys/id_rsa_ha")

    LOGGER.info(
        "Setting up OpenClash physical switch on %s with user %s",
        ssh_host,
        ssh_user,
    )
    async_add_entities([MihomoPhysicalSwitch(ssh_host, ssh_user, ssh_key)])


class MihomoPhysicalSwitch(SwitchEntity):
    """Mihomo SSH-based Physical Switch for OpenClash."""

    def __init__(self, ssh_host: str, ssh_user: str, ssh_key: str) -> None:
        """Initialize the switch."""
        self._ssh_host = ssh_host
        self._ssh_user = ssh_user
        self._ssh_key = ssh_key
        self._attr_name = "OpenClash"
        self._attr_unique_id = f"openclash_switch_{ssh_host.replace('.', '_')}"
        self._attr_icon = "mdi:router-wireless"
        self._attr_is_on = False

    async def _run_ssh_command(self, cmd: str) -> tuple[int, str, str]:
        """Run SSH command asynchronously and return exit code, stdout, stderr."""
        ssh_cmd = (
            f'ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null '
            f'-i "{self._ssh_key}" "{self._ssh_user}@{self._ssh_host}" "{cmd}"'
        )
        LOGGER.debug("Running SSH command: %s", ssh_cmd)
        try:
            proc = await asyncio.create_subprocess_shell(
                ssh_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            return proc.returncode if proc.returncode is not None else -1, stdout.decode().strip(), stderr.decode().strip()
        except Exception as err:
            LOGGER.error("SSH execution failed for command %s: %s", cmd, err)
            return -1, "", str(err)

    async def async_update(self) -> None:
        """Fetch the latest status of the switch."""
        code, stdout, stderr = await self._run_ssh_command("uci -q get openclash.config.enable")
        LOGGER.debug(
            "OpenClash update result - code: %s, stdout: %s, stderr: %s",
            code,
            stdout,
            stderr,
        )
        if code == 0:
            self._attr_is_on = stdout == "1"
        else:
            self._attr_is_on = False

    async def async_turn_on(self, **kwargs) -> None:
        """Turn the physical switch on."""
        cmd = "uci set openclash.config.enable=1; uci commit openclash; /etc/init.d/openclash start"
        code, stdout, stderr = await self._run_ssh_command(cmd)
        if code == 0:
            self._attr_is_on = True
            self.async_write_ha_state()
        else:
            LOGGER.error("Failed to turn on OpenClash: %s", stderr)

    async def async_turn_off(self, **kwargs) -> None:
        """Turn the physical switch off."""
        cmd = "uci set openclash.config.enable=0; uci commit openclash; /etc/init.d/openclash stop"
        code, stdout, stderr = await self._run_ssh_command(cmd)
        if code == 0:
            self._attr_is_on = False
            self.async_write_ha_state()
        else:
            LOGGER.error("Failed to turn off OpenClash: %s", stderr)
