# CHISAGE ESS Inteless for Home Assistant

Home Assistant cloud monitoring for CHISAGE ESS inverters connected to the
Inteless / E-Linter platform. The integration uses read-only API requests and
does not expose inverter controls.

## Installation

### HACS custom repository

1. In HACS, open **Integrations** and choose **Custom repositories**.
2. Add `https://github.com/chukaonline/ha-alpsolar-inteless` as an Integration.
3. Download **CHISAGE ESS Inteless** and restart Home Assistant.
4. Add the integration from **Settings → Devices & services**.

### Manual installation

Copy `custom_components/alpsolar_inteless` into your Home Assistant
`config/custom_components/` directory, restart Home Assistant, then add the
integration from **Settings → Devices & services**.

## Configuration

The UI asks for the Inteless username, password, region, and Plant ID. The
selected plant is checked during setup and its inverters are discovered
automatically. Use the integration's **Reconfigure** action to update these
settings. Europe is the default region.

Find the Plant ID in the PV Pro / Inteless portal's plant details URL or in the
plant detail request. For example, `/api/v1/plant/2234?...` corresponds to Plant
ID `2234`.

## Verified sensors

The first sensor set uses values verified from the CHISAGE Mars-14G2-LE portal
responses. Each inverter is a separate Home Assistant device, identified by
serial number.

| Sensor | Source field | Unit |
| --- | --- | --- |
| Solar PV Power | flow `pvPower` | W |
| MPPT 1 / MPPT 2 Power | flow `pv[].power` | W |
| Grid Power | flow `gridOrMeterPower` | W |
| Load Power | flow `loadOrEpsPower` | W |
| Battery Power | flow `battPower` | W |
| Battery Charging / Discharging Power | signed flow `battPower` split by direction | W |
| Battery State of Charge | battery realtime `soc` | % |
| Battery Voltage / Current / Temperature | battery realtime `voltage`, `current`, `temp` | V / A / °C |
| Battery Energy Charged / Discharged Total | battery realtime `etotalChg`, `etotalDischg` | kWh |

Sensors use `unavailable` when an API field is absent; a reported numeric zero
remains zero. Battery charge/discharge split treats positive `battPower` as
discharge, consistent with the portal's observed `batTo` flow flag. Battery
charge direction is inferred as negative power.

## Energy Dashboard

The battery charge/discharge entities use `total_increasing` energy state
classes. Solar total energy is withheld because the inverter-list and inverter
detail `etotal` values differed in a live response, and the list value was null
on another poll. Grid import/export and home consumption energy counters are
also not included until stable cumulative fields are verified. Power sensors
are not integrated internally, avoiding duplicate or fabricated energy totals.

## API diagnostic

The repository includes a standalone, read-only diagnostic. Fill in the ignored
project-root `.env` file, then run:

```bash
python3 scripts/inteless_api_diagnostic.py
```

It authenticates against the selected region, discovers plant inverters, and
checks the observed plant detail, inverter detail, flow, battery realtime,
parameter catalog, and one daily history request. It redacts password/token,
contact, and location fields. Review output for private identifiers before
sharing it. The script only performs GET requests after login.

If Python reports `CERTIFICATE_VERIFY_FAILED`, it uses the installed `certifi`
CA bundle automatically when available. TLS verification is never disabled.

## Troubleshooting

- **Invalid authentication:** confirm the portal username/password and region.
- **Cannot connect / HTTP errors:** verify Home Assistant can reach the region's
  Inteless API host. The diagnostic reports status codes without printing
  credentials or bearer tokens.
- **No entities:** confirm the selected Plant ID returns inverters and that the
  first coordinator refresh succeeded. Inverters appear as separate devices.
- **Some measurements unavailable:** the API may omit fields for an offline or
  unsupported device; missing values are intentionally not replaced with zero.

Enable debug logs temporarily with:

```yaml
logger:
  logs:
    custom_components.alpsolar_inteless: debug
```

Credentials are stored in the Home Assistant config entry. Never share
passwords, bearer tokens, cookies, or unredacted portal responses. The
integration makes no settings or control requests.

## Known limitations

- The `GET /api/v1/plants` route returned HTTP 500 for the tested Europe
  account; a configured Plant ID is used with the working plant inverter route.
- Grid phase voltage/current, frequency, import/export energy, and detailed
  load energy are not yet mapped to live value responses.
- Other Inteless regions and inverter models have not been verified.
- Cloud availability and update latency depend on Inteless.
