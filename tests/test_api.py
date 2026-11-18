"""Mocked API tests requiring only Python's unittest and aiohttp."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
import unittest
from collections import deque
from pathlib import Path
from typing import Any

# Load the API module without importing the Home Assistant integration package;
# that keeps these HTTP-client unit tests runnable on a plain Python install.
INTEGRATION_PATH = Path(__file__).parents[1] / "custom_components" / "alpsolar_inteless"
PACKAGE_NAME = "_inteless_api_test_package"
package = types.ModuleType(PACKAGE_NAME)
package.__path__ = [str(INTEGRATION_PATH)]
sys.modules[PACKAGE_NAME] = package
for module_name in ("const", "api"):
    spec = importlib.util.spec_from_file_location(
        f"{PACKAGE_NAME}.{module_name}", INTEGRATION_PATH / f"{module_name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

helper_spec = importlib.util.spec_from_file_location(
    f"{PACKAGE_NAME}.sensor_helpers", INTEGRATION_PATH / "sensor_helpers.py"
)
helper_module = importlib.util.module_from_spec(helper_spec)
sys.modules[helper_spec.name] = helper_module
helper_spec.loader.exec_module(helper_module)

IntelessApi = sys.modules[f"{PACKAGE_NAME}.api"].IntelessApi
IntelessApiError = sys.modules[f"{PACKAGE_NAME}.api"].IntelessApiError
IntelessAuthError = sys.modules[f"{PACKAGE_NAME}.api"].IntelessAuthError
numeric_value = helper_module.numeric_value
battery_directional_power = helper_module.battery_directional_power


class FakeResponse:
    def __init__(self, status: int, body: Any) -> None:
        self.status = status
        self.body = body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return None

    async def json(self, **_kwargs):
        if isinstance(self.body, Exception):
            raise self.body
        return self.body


class FakeSession:
    def __init__(self, *, posts=(), gets=()) -> None:
        self.posts = deque(posts)
        self.gets = deque(gets)
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        item = self.posts.popleft()
        if isinstance(item, Exception):
            raise item
        return item

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        item = self.gets.popleft()
        if isinstance(item, Exception):
            raise item
        return item


def auth_response(token="test-token"):
    return FakeResponse(200, {"success": True, "data": {"access_token": token, "expires_in": 3600}})


class IntelessApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_authentication_and_inverter_discovery(self):
        session = FakeSession(
            posts=[auth_response()],
            gets=[FakeResponse(200, {"success": True, "data": {"infos": [{"sn": "SN1", "type": 93}]}})],
        )
        api = IntelessApi(session, "Europe", "user", "password")
        result = await api.async_get_inverters("2234")
        self.assertEqual(result[0]["sn"], "SN1")
        self.assertIn("stationId=2234", session.calls[1][1])
        self.assertEqual(session.calls[1][2]["headers"]["Authorization"], "Bearer test-token")

    async def test_empty_plant_and_multiple_plant_ids(self):
        session = FakeSession(
            posts=[auth_response()],
            gets=[
                FakeResponse(200, {"success": True, "data": {"infos": []}}),
                FakeResponse(200, {"success": True, "data": {"infos": [{"sn": "OTHER"}]}}),
            ],
        )
        api = IntelessApi(session, "Europe", "user", "password")
        self.assertEqual(await api.async_get_inverters("empty-plant"), [])
        self.assertEqual((await api.async_get_inverters("other-plant"))[0]["sn"], "OTHER")
        self.assertIn("stationId=empty-plant", session.calls[1][1])
        self.assertIn("stationId=other-plant", session.calls[2][1])

    async def test_invalid_credentials(self):
        session = FakeSession(posts=[FakeResponse(401, {"error": "invalid_grant"})])
        api = IntelessApi(session, "Europe", "user", "wrong")
        with self.assertRaises(IntelessAuthError):
            await api.async_get_inverters("2234")

    async def test_expired_token_is_reauthenticated_after_401(self):
        session = FakeSession(
            posts=[auth_response("old"), auth_response("new")],
            gets=[
                FakeResponse(401, {"error": "expired"}),
                FakeResponse(200, {"success": True, "data": {"infos": []}}),
            ],
        )
        api = IntelessApi(session, "Europe", "user", "password")
        self.assertEqual(await api.async_get_inverters("2234"), [])
        self.assertEqual(session.calls[1][2]["headers"]["Authorization"], "Bearer old")
        self.assertEqual(session.calls[3][2]["headers"]["Authorization"], "Bearer new")

    async def test_http_errors_are_reported_without_response_secrets(self):
        for status in (403, 404, 429, 500):
            with self.subTest(status=status):
                session = FakeSession(
                    posts=[auth_response()],
                    gets=[FakeResponse(status, {"message": "private server body"})],
                )
                api = IntelessApi(session, "Europe", "user", "password")
                with self.assertRaises(IntelessApiError) as caught:
                    await api.async_get_inverters("2234")
                self.assertNotIn("private server body", str(caught.exception))
                if status == 403:
                    self.assertIsInstance(caught.exception, IntelessAuthError)

    async def test_timeout_is_converted_to_safe_api_error(self):
        session = FakeSession(posts=[asyncio.TimeoutError()])
        api = IntelessApi(session, "Europe", "user", "password")
        with self.assertRaisesRegex(IntelessApiError, "TimeoutError"):
            await api.async_get_inverters("2234")

    async def test_unexpected_inverter_response_is_rejected(self):
        session = FakeSession(posts=[auth_response()], gets=[FakeResponse(200, {"data": {"list": []}})])
        api = IntelessApi(session, "Europe", "user", "password")
        with self.assertRaisesRegex(IntelessApiError, "unexpected structure"):
            await api.async_get_inverters("2234")

    async def test_live_flow_and_battery_values_are_preserved(self):
        flow = {"pvPower": 54, "gridOrMeterPower": 3112, "loadOrEpsPower": 3095, "battPower": 59}
        battery = {"soc": "99.0", "voltage": "53.6", "etotalChg": "10390.4"}
        session = FakeSession(
            posts=[auth_response()],
            gets=[FakeResponse(200, {"success": True, "data": flow}),
                  FakeResponse(200, {"success": True, "data": battery})],
        )
        api = IntelessApi(session, "Europe", "user", "password")
        self.assertEqual(await api.async_get_flow("SN1"), flow)
        self.assertEqual(await api.async_get_battery("SN1"), battery)

    def test_battery_power_direction_and_invalid_energy_values(self):
        self.assertEqual(battery_directional_power(59), (0.0, 59.0))
        self.assertEqual(battery_directional_power(-14), (14.0, 0.0))
        self.assertEqual(battery_directional_power(None), (None, None))
        self.assertIsNone(numeric_value("NaN", non_negative=True))
        self.assertIsNone(numeric_value(-0.1, non_negative=True))
        self.assertEqual(numeric_value("10390.4", non_negative=True), 10390.4)


if __name__ == "__main__":
    unittest.main()
