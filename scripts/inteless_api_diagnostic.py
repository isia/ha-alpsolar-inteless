#!/usr/bin/env python3
"""Read-only diagnostic for the Inteless cloud API.

Run locally with INTELESS_API_BASE, INTELESS_USERNAME, INTELESS_PASSWORD and
INTELESS_PLANT_ID set. The script prints response shapes and useful identifiers,
but redacts credentials and tokens. It only issues the documented login and GET
requests; it never calls inverter control endpoints.
"""

from __future__ import annotations

import json
import os
import ssl
import sys
from datetime import date
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

SCRIPT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_FILE = os.path.join(SCRIPT_ROOT, ".env")
REGION_BASES = {
    "Europe": "https://euapi.inteless.com",
    "America": "https://usapi.inteless.com",
    "Asia": "https://pv.inteless.com",
    "Global": "https://api.inteless.com",
}
SENSITIVE_KEYS = {
    "password", "access_token", "refresh_token", "token", "authorization",
    "client_secret", "secret", "credential", "email", "phone", "address",
    "principal", "nickname", "lat", "lon", "latitude", "longitude",
}
TIMEOUT = 20
SECRET_VALUES: list[str] = []


def verified_ssl_context() -> ssl.SSLContext:
    """Use certifi's maintained roots when available, otherwise Python defaults."""
    try:
        import certifi  # Optional; avoids broken/missing CA configuration in some Python installs.

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def load_env_file() -> None:
    """Load simple KEY=VALUE entries from the project .env without dependencies."""
    try:
        with open(ENV_FILE, encoding="utf-8") as env_file:
            for raw_line in env_file:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                name, value = line.split("=", 1)
                name = name.strip()
                value = value.strip().strip("\"'")
                if name and name not in os.environ:
                    os.environ[name] = value
    except FileNotFoundError:
        pass


def redact(value: Any, key: str = "") -> Any:
    """Recursively remove secrets while retaining response structure."""
    if key.lower() in SENSITIVE_KEYS or any(part in key.lower() for part in ("token", "password", "secret")):
        return "<redacted>"
    if isinstance(value, dict):
        return {str(k): redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value[:50]] + (["<{} more items>".format(len(value) - 50)] if len(value) > 50 else [])
    if isinstance(value, str) and len(value) > 500:
        value = value[:500] + "… <truncated>"
    if isinstance(value, str):
        for secret in SECRET_VALUES:
            if secret:
                value = value.replace(secret, "<redacted>")
    return value


def request(method: str, url: str, *, payload: dict[str, Any] | None = None,
            token: str | None = None) -> tuple[int, Any]:
    headers = {"Accept": "application/json", "User-Agent": "inteless-ha-diagnostic/1.0"}
    body = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload).encode()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=verified_ssl_context()) as response:
            status = response.status
            raw = response.read(1_000_001)
    except urllib.error.HTTPError as err:
        status = err.code
        raw = err.read(1_000_001)
    except Exception as err:  # Network and timeout details are useful, no secrets included.
        return 0, {"transport_error": f"{type(err).__name__}: {err}"}
    if len(raw) > 1_000_000:
        raw = raw[:1_000_000]
    try:
        return status, json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return status, {"non_json_body": raw.decode("utf-8", errors="replace")[:1000]}


def show(label: str, method: str, url: str, status: int, body: Any) -> None:
    print(f"\n[{label}] {method} {url}\nHTTP status: {status}")
    print(json.dumps(redact(body), indent=2, ensure_ascii=False))


def main() -> int:
    load_env_file()
    region = os.getenv("INTELESS_REGION", "Europe")
    base = os.getenv("INTELESS_API_BASE", REGION_BASES.get(region, "")).rstrip("/")
    client_id = os.getenv("INTELESS_CLIENT_ID", "csp-web")
    username = os.getenv("INTELESS_USERNAME")
    password = os.getenv("INTELESS_PASSWORD")
    plant_id = os.getenv("INTELESS_PLANT_ID")
    missing = [name for name, val in (
        ("INTELESS_API_BASE", base), ("INTELESS_USERNAME", username),
        ("INTELESS_PASSWORD", password), ("INTELESS_PLANT_ID", plant_id),
    ) if not val]
    if missing:
        print("Missing required environment variables: " + ", ".join(missing), file=sys.stderr)
        print("Set INTELESS_API_BASE to the regional API host confirmed for your account.", file=sys.stderr)
        return 2
    if not base.startswith("https://"):
        print("INTELESS_API_BASE must use https://; refusing to send credentials.", file=sys.stderr)
        return 2
    SECRET_VALUES.extend([str(username), str(password)])

    login_url = base + "/oauth/token"
    status, auth = request("POST", login_url, payload={
        "username": username, "password": password, "grant_type": "password",
        "client_id": client_id,
    })
    token = auth.get("data", {}).get("access_token") if isinstance(auth, dict) else None
    if token:
        SECRET_VALUES.append(str(token))
    # Do not print auth response contents: even a server error may echo submitted data.
    print(f"\n[authentication] POST {login_url}\nHTTP status: {status}")
    print(json.dumps({
        "top_level_keys": list(auth) if isinstance(auth, dict) else type(auth).__name__,
        "data_keys": list(auth.get("data", {})) if isinstance(auth, dict) and isinstance(auth.get("data"), dict) else None,
        "authenticated": bool(token),
        "api_error": redact({k: v for k, v in auth.items() if k not in ("data", "access_token", "refresh_token")}) if isinstance(auth, dict) else None,
    }, indent=2, ensure_ascii=False))
    if not token:
        return 1

    headers_token = str(token)
    plants_url = base + "/api/v1/plants"
    status, plants = request("GET", plants_url, token=headers_token)
    show("plants", "GET", plants_url, status, plants)

    inverter_query = urllib.parse.urlencode({
        "page": 1,
        "limit": 10,
        "status": -1,
        "sn": "",
        "stationId": plant_id,
        "type": -2,
    })
    plant_url = (
        base + "/api/v1/plant/" + urllib.parse.quote(str(plant_id), safe="")
        + "/inverters?" + inverter_query
    )
    status, inverters = request("GET", plant_url, token=headers_token)
    show("selected plant inverters", "GET", plant_url, status, inverters)

    inverter_infos = (
        inverters.get("data", {}).get("infos", [])
        if isinstance(inverters, dict) and isinstance(inverters.get("data"), dict)
        else []
    )
    if isinstance(inverter_infos, list):
        for inverter in inverter_infos:
            if not isinstance(inverter, dict) or not inverter.get("sn"):
                continue
            serial = str(inverter["sn"])
            detail_query = urllib.parse.urlencode({"sn": serial, "lan": "en"})
            detail_url = (
                base + "/api/v1/inverter/" + urllib.parse.quote(serial, safe="")
                + "?" + detail_query
            )
            status, detail = request("GET", detail_url, token=headers_token)
            show(f"inverter detail {serial}", "GET", detail_url, status, detail)

            battery_query = urllib.parse.urlencode({"sn": serial, "lan": "en"})
            battery_url = (
                base + "/api/v1/inverter/battery/"
                + urllib.parse.quote(serial, safe="") + "/realtime?" + battery_query
            )
            status, battery = request("GET", battery_url, token=headers_token)
            show(f"battery realtime {serial}", "GET", battery_url, status, battery)

            flow_url = (
                base + "/api/v1/inverter/" + urllib.parse.quote(serial, safe="")
                + "/flow"
            )
            status, flow = request("GET", flow_url, token=headers_token)
            show(f"inverter flow {serial}", "GET", flow_url, status, flow)

            today = date.today().isoformat()
            day_query = urllib.parse.urlencode({
                "sn": serial,
                "date": today,
                "edate": today,
                "lan": "en",
                "params": "316194",
            })
            day_url = (
                base + "/api/v1/inverter/" + urllib.parse.quote(serial, safe="")
                + "/new/day?" + day_query
            )
            status, day_data = request("GET", day_url, token=headers_token)
            show(f"inverter parameter history {serial}", "GET", day_url, status, day_data)

    # The web portal's observed plant-detail request includes both a path ID
    # and an id query parameter; keep both until account results validate it.
    detail_query = urllib.parse.urlencode({"lan": "en", "id": str(plant_id)})
    detail_url = (
        base + "/api/v1/plant/" + urllib.parse.quote(str(plant_id), safe="")
        + "?" + detail_query
    )
    status, plant_detail = request("GET", detail_url, token=headers_token)
    show("selected plant detail", "GET", detail_url, status, plant_detail)

    # These query parameters were observed in the user's portal request.
    for inverter in inverter_infos if isinstance(inverter_infos, list) else []:
        if not isinstance(inverter, dict) or not inverter.get("sn"):
            continue
        serial = str(inverter["sn"])
        params_query = urllib.parse.urlencode({
            "lan": "en", "devType": inverter.get("type", ""), "sn": serial,
        })
        params_url = base + "/api/v1/inverter/params?" + params_query
        status, params = request("GET", params_url, token=headers_token)
        show(f"inverter telemetry params {serial}", "GET", params_url, status, params)
    print("\nDiagnostic complete. Share output after reviewing it for account identifiers or other private data.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
