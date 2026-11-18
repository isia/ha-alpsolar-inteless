"""Coordinator for plant inventory and inverter telemetry."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import IntelessApi, IntelessApiError
from .const import CONF_PLANT_ID, DOMAIN

_LOGGER = logging.getLogger(__name__)


class IntelessCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    """Fetch verified read-only data for every inverter in one plant."""

    def __init__(self, hass: Any, api: IntelessApi, plant_id: str) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=60),
        )
        self.api = api
        self.plant_id = str(plant_id)

    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        try:
            inverters = await self.api.async_get_inverters(self.plant_id)
            async def fetch_one(inverter: dict[str, Any]) -> tuple[str, dict[str, Any]]:
                serial = str(inverter["sn"])
                flow_task = self.api.async_get_flow(serial)
                battery_task = self.api.async_get_battery(serial)
                flow, battery = await asyncio.gather(flow_task, battery_task, return_exceptions=True)
                if isinstance(flow, Exception):
                    _LOGGER.warning("Unable to refresh telemetry for inverter %s (%s)", serial, flow)
                    flow = {}
                if isinstance(battery, Exception):
                    _LOGGER.warning("Unable to refresh battery telemetry for inverter %s (%s)", serial, battery)
                    battery = None
                return serial, {"inverter": inverter, "flow": flow, "battery": battery}

            results = await asyncio.gather(*(fetch_one(item) for item in inverters))
            return dict(results)
        except IntelessApiError as err:
            raise UpdateFailed(str(err)) from err
        except (asyncio.TimeoutError, OSError) as err:
            raise UpdateFailed(f"Inteless cloud request failed: {type(err).__name__}") from err


def coordinator_from_entry(hass: Any, entry: Any) -> IntelessCoordinator:
    """Create the API client and coordinator for a config entry."""
    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    from .const import CONF_PASSWORD, CONF_REGION, CONF_USERNAME

    api = IntelessApi(
        async_get_clientsession(hass),
        entry.data[CONF_REGION],
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
    )
    return IntelessCoordinator(hass, api, entry.data[CONF_PLANT_ID])
