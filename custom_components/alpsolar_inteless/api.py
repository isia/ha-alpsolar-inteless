"""Asynchronous, read-only client for the Inteless cloud API."""

from __future__ import annotations

import asyncio
import time
from typing import Any
from urllib.parse import quote, urlencode

from aiohttp import ClientError, ClientSession

from .const import REGIONS


class IntelessApiError(Exception):
    """Base error for API failures safe to show in Home Assistant logs."""


class IntelessAuthError(IntelessApiError):
    """Authentication was rejected by Inteless."""


class IntelessApi:
    """Minimal client for verified Inteless endpoints."""

    def __init__(self, session: ClientSession, region: str, username: str, password: str) -> None:
        self._session = session
        self._base_url = REGIONS[region].rstrip("/")
        self._username = username
        self._password = password
        self._access_token: str | None = None
        self._token_expiry = 0.0
        self._auth_lock = asyncio.Lock()

    async def _async_authenticate(self) -> None:
        async with self._auth_lock:
            if self._access_token and time.monotonic() < self._token_expiry:
                return
            url = f"{self._base_url}/oauth/token"
            payload = {
                "username": self._username,
                "password": self._password,
                "grant_type": "password",
                "client_id": "csp-web",
            }
            try:
                async with self._session.post(url, json=payload, timeout=20) as response:
                    if response.status in (401, 403):
                        raise IntelessAuthError("Inteless rejected the username or password")
                    if response.status < 200 or response.status >= 300:
                        raise IntelessApiError(f"Inteless authentication failed (HTTP {response.status})")
                    body = await self._read_json(response)
            except (ClientError, asyncio.TimeoutError) as err:
                raise IntelessApiError(f"Inteless authentication request failed: {type(err).__name__}") from err

            data = body.get("data") if isinstance(body, dict) else None
            token = data.get("access_token", data.get("accessToken")) if isinstance(data, dict) else None
            if not token:
                raise IntelessAuthError("Inteless authentication response did not contain an access token")
            expires = data.get("expires_in", data.get("expiresIn", 3600))
            try:
                lifetime = max(60, float(expires))
            except (TypeError, ValueError):
                lifetime = 3600
            self._access_token = str(token)
            # The API returns bearer token expiry; reauthenticate before expiration.
            self._token_expiry = time.monotonic() + max(30, lifetime - 60)

    async def _read_json(self, response: Any) -> Any:
        try:
            return await response.json(content_type=None)
        except (ValueError, TypeError) as err:
            raise IntelessApiError(f"Inteless returned invalid JSON (HTTP {response.status})") from err

    async def _async_get(self, path: str, query: dict[str, Any] | None = None, *, retry_auth: bool = True) -> Any:
        await self._async_authenticate()
        url = f"{self._base_url}{path}"
        if query:
            url += "?" + urlencode(query)
        headers = {"Authorization": f"Bearer {self._access_token}", "Accept": "application/json"}
        try:
            async with self._session.get(url, headers=headers, timeout=20) as response:
                if response.status == 401 and retry_auth:
                    self._access_token = None
                    self._token_expiry = 0
                    await self._async_authenticate()
                    return await self._async_get(path, query, retry_auth=False)
                if response.status in (401, 403):
                    raise IntelessAuthError(f"Inteless authorization failed (HTTP {response.status})")
                if response.status == 429:
                    raise IntelessApiError("Inteless rate limit reached (HTTP 429)")
                if response.status < 200 or response.status >= 300:
                    raise IntelessApiError(f"Inteless request failed (HTTP {response.status})")
                body = await self._read_json(response)
        except (ClientError, asyncio.TimeoutError) as err:
            raise IntelessApiError(f"Inteless request failed: {type(err).__name__}") from err
        if isinstance(body, dict) and body.get("success") is False:
            code = body.get("code", "unknown")
            raise IntelessApiError(f"Inteless API reported an error (code {code})")
        return body

    async def async_get_inverters(self, plant_id: str) -> list[dict[str, Any]]:
        body = await self._async_get(
            f"/api/v1/plant/{quote(str(plant_id), safe='')}/inverters",
            {"page": 1, "limit": 10, "status": -1, "sn": "", "stationId": plant_id, "type": -2},
        )
        data = body.get("data") if isinstance(body, dict) else None
        infos = data.get("infos") if isinstance(data, dict) else None
        if not isinstance(infos, list):
            raise IntelessApiError("Inteless inverter list response had an unexpected structure")
        return [item for item in infos if isinstance(item, dict) and item.get("sn")]

    async def async_get_flow(self, serial: str) -> dict[str, Any]:
        body = await self._async_get(f"/api/v1/inverter/{quote(serial, safe='')}/flow")
        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, dict):
            raise IntelessApiError("Inteless inverter flow response had an unexpected structure")
        return data

    async def async_get_battery(self, serial: str) -> dict[str, Any] | None:
        body = await self._async_get(
            f"/api/v1/inverter/battery/{quote(serial, safe='')}/realtime",
            {"sn": serial, "lan": "en"},
        )
        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, dict):
            raise IntelessApiError("Inteless battery response had an unexpected structure")
        return data
