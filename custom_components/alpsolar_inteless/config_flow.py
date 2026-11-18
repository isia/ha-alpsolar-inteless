"""Config flow for Inteless cloud accounts."""

from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import IntelessApi, IntelessApiError, IntelessAuthError
from .const import CONF_PLANT_ID, CONF_REGION, DOMAIN, REGIONS


class AlpsolarConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure one Inteless plant."""

    VERSION = 2

    async def async_step_user(self, user_input: dict | None = None):
        """Collect credentials, region, and the plant ID to monitor."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                await self._async_validate(user_input)
            except IntelessAuthError:
                errors["base"] = "invalid_auth"
            except IntelessApiError:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(f"{user_input[CONF_REGION]}_{user_input[CONF_PLANT_ID]}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Inteless plant {user_input[CONF_PLANT_ID]}",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=self._schema(),
            errors=errors,
        )

    async def async_step_reconfigure(self, user_input: dict | None = None):
        """Allow credentials, region, and plant to be corrected in the UI."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input = {**user_input, CONF_PASSWORD: user_input.get(CONF_PASSWORD) or entry.data[CONF_PASSWORD]}
            try:
                await self._async_validate(user_input)
            except IntelessAuthError:
                errors["base"] = "invalid_auth"
            except IntelessApiError:
                errors["base"] = "cannot_connect"
            else:
                self.hass.config_entries.async_update_entry(
                    entry,
                    data=user_input,
                    title=f"Inteless plant {user_input[CONF_PLANT_ID]}",
                )
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reconfigure_successful")

        defaults = {**entry.data}
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self._schema(defaults),
            errors=errors,
        )

    async def _async_validate(self, data: dict) -> None:
        """Authenticate and ensure the selected plant endpoint is accessible."""
        api = IntelessApi(
            async_get_clientsession(self.hass),
            data[CONF_REGION],
            data[CONF_USERNAME],
            data[CONF_PASSWORD],
        )
        await api.async_get_inverters(data[CONF_PLANT_ID])

    @staticmethod
    def _schema(defaults: dict | None = None) -> vol.Schema:
        defaults = defaults or {}
        return vol.Schema(
            {
                vol.Required(CONF_REGION, default=defaults.get(CONF_REGION, "Europe")): vol.In(list(REGIONS)),
                vol.Required(CONF_USERNAME, default=defaults.get(CONF_USERNAME, "")): str,
                vol.Optional(CONF_PASSWORD, default=""): str,
                vol.Required(CONF_PLANT_ID, default=defaults.get(CONF_PLANT_ID, "")): str,
            }
        )
