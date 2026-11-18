"""Home Assistant setup for the Inteless cloud integration."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .coordinator import IntelessCoordinator, coordinator_from_entry

PLATFORMS = ["sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the API coordinator before forwarding platforms."""
    coordinator: IntelessCoordinator = coordinator_from_entry(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload platforms for a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate existing entries without changing their configured values."""
    if entry.version == 1:
        unique_id = f"{entry.data.get('region', 'Europe')}_{entry.data.get('plant_id', '')}"
        hass.config_entries.async_update_entry(
            entry,
            version=2,
            unique_id=unique_id,
        )
        return True
    return entry.version == 2
