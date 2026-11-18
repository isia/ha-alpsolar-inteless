"""Sensors for verified Inteless inverter telemetry."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import IntelessCoordinator
from .const import DOMAIN
from .sensor_helpers import battery_directional_power, numeric_value


@dataclass(frozen=True, kw_only=True)
class IntelessSensorDescription(SensorEntityDescription):
    """Describe the source and path of a supported telemetry value."""

    source: str
    path: tuple[str | int, ...]
    transform: str | None = None


SENSORS: tuple[IntelessSensorDescription, ...] = (
    IntelessSensorDescription(
        key="pv_power", name="Solar PV Power", source="flow", path=("pvPower",),
        device_class=SensorDeviceClass.POWER, native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    IntelessSensorDescription(
        key="mppt_1_power", name="Solar MPPT 1 Power", source="flow", path=("pv", 0, "power"),
        device_class=SensorDeviceClass.POWER, native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    IntelessSensorDescription(
        key="mppt_2_power", name="Solar MPPT 2 Power", source="flow", path=("pv", 1, "power"),
        device_class=SensorDeviceClass.POWER, native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    IntelessSensorDescription(
        key="grid_power", name="Grid Power", source="flow", path=("gridOrMeterPower",),
        device_class=SensorDeviceClass.POWER, native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    IntelessSensorDescription(
        key="load_power", name="Load Power", source="flow", path=("loadOrEpsPower",),
        device_class=SensorDeviceClass.POWER, native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    IntelessSensorDescription(
        key="battery_power", name="Battery Power", source="flow", path=("battPower",),
        device_class=SensorDeviceClass.POWER, native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    IntelessSensorDescription(
        key="battery_charge_power", name="Battery Charging Power", source="flow", path=("battPower",),
        device_class=SensorDeviceClass.POWER, native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT, transform="charge_power",
    ),
    IntelessSensorDescription(
        key="battery_discharge_power", name="Battery Discharging Power", source="flow", path=("battPower",),
        device_class=SensorDeviceClass.POWER, native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT, transform="discharge_power",
    ),
    IntelessSensorDescription(
        key="battery_soc", name="Battery State of Charge", source="battery", path=("soc",),
        device_class=SensorDeviceClass.BATTERY, native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    IntelessSensorDescription(
        key="battery_voltage", name="Battery Voltage", source="battery", path=("voltage",),
        device_class=SensorDeviceClass.VOLTAGE, native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    IntelessSensorDescription(
        key="battery_current", name="Battery Current", source="battery", path=("current",),
        device_class=SensorDeviceClass.CURRENT, native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    IntelessSensorDescription(
        key="battery_temperature", name="Battery Temperature", source="battery", path=("temp",),
        device_class=SensorDeviceClass.TEMPERATURE, native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    IntelessSensorDescription(
        key="battery_energy_charged", name="Battery Energy Charged Total", source="battery", path=("etotalChg",),
        device_class=SensorDeviceClass.ENERGY, native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    IntelessSensorDescription(
        key="battery_energy_discharged", name="Battery Energy Discharged Total", source="battery", path=("etotalDischg",),
        device_class=SensorDeviceClass.ENERGY, native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Any,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create one set of sensor entities for every discovered inverter."""
    coordinator: IntelessCoordinator = entry.runtime_data
    added_serials: set[str] = set()

    def add_new_inverters() -> None:
        new_serials = set(coordinator.data) - added_serials
        if not new_serials:
            return
        added_serials.update(new_serials)
        async_add_entities(
            IntelessSensor(coordinator, serial, description)
            for serial in new_serials
            for description in SENSORS
        )

    add_new_inverters()
    entry.async_on_unload(coordinator.async_add_listener(add_new_inverters))


class IntelessSensor(CoordinatorEntity[IntelessCoordinator], SensorEntity):
    """A single sensor tied to an inverter device."""

    entity_description: IntelessSensorDescription

    def __init__(
        self,
        coordinator: IntelessCoordinator,
        serial: str,
        description: IntelessSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._serial = serial
        self._attr_unique_id = f"{serial}_{description.key}"
        inverter = coordinator.data[serial]["inverter"]
        model = inverter.get("model") or inverter.get("modelSource") or "Inteless inverter"
        version = inverter.get("version") or {}
        firmware = ".".join(
            str(value) for value in (version.get("masterVer"), version.get("softVer")) if value
        ) or None
        self._attr_device_info = {
            "identifiers": {(DOMAIN, serial)},
            "manufacturer": "CHISAGE ESS",
            "model": model,
            "name": f"{model} ({serial})",
            "serial_number": serial,
            "sw_version": firmware,
        }

    @property
    def native_value(self) -> float | None:
        """Return a numeric measurement, or None when the API omitted it."""
        item = self.coordinator.data.get(self._serial)
        if not item:
            return None
        source = item.get(self.entity_description.source)
        value: Any = source
        for key in self.entity_description.path:
            if isinstance(value, dict):
                value = value.get(key)
            elif isinstance(value, list) and isinstance(key, int) and key < len(value):
                value = value[key]
            else:
                return None
        numeric = numeric_value(
            value,
            non_negative=self.entity_description.device_class == SensorDeviceClass.ENERGY,
        )
        if numeric is None:
            return None
        if self.entity_description.transform == "charge_power":
            return battery_directional_power(numeric)[0]
        if self.entity_description.transform == "discharge_power":
            return battery_directional_power(numeric)[1]
        return numeric

    @property
    def available(self) -> bool:
        """Mark data unavailable when the cloud's inverter sample is stale."""
        if not super().available:
            return False
        if self.native_value is None:
            return False
        inverter = self.coordinator.data.get(self._serial, {}).get("inverter", {})
        updated = inverter.get("updateAt")
        if not updated:
            return True
        try:
            timestamp = datetime.fromisoformat(str(updated).replace("Z", "+00:00"))
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
        except ValueError:
            return True
        return datetime.now(timezone.utc) - timestamp <= timedelta(minutes=10)
