"""Number platform for Battery devices (forced charge/discharge setpoints)."""

import logging

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberMode,
    RestoreNumber,
    ENTITY_ID_FORMAT,
)
from homeassistant.const import PERCENTAGE, UnitOfPower, UnitOfTime
from homeassistant.helpers.entity import generate_entity_id
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ...api.devices.battery_api import (
    SIGNAL_FORCED_CHARGE_DISCHARGE,
    SIGNAL_FORCED_DISCHARGE_POWER,
)
from .control import BatteryControl, async_get_battery_control

_LOGGER = logging.getLogger(__name__)


# ── Handler ───────────────────────────────────────────────────────────────────

class BatteryNumberHandler:
    """Creates the forced charge/discharge Number entities of a battery."""

    def __init__(self, hass, entry, device_info):
        self.hass = hass
        self.entry = entry
        self.device_info = device_info
        self.control: BatteryControl | None = None

    async def create_coordinator(self):
        self.control = await async_get_battery_control(
            self.hass, self.entry, self.device_info
        )
        return self.control.coordinator

    def create_entities(self, coordinator) -> list:
        if not coordinator.data or SIGNAL_FORCED_CHARGE_DISCHARGE not in coordinator.data:
            return []
        return [
            FusionSolarBatteryForcedPeriodNumber(self.control, self.device_info),
            FusionSolarBatteryTargetSocNumber(self.control, self.device_info),
            FusionSolarBatteryForcedDischargePowerNumber(
                self.control, self.device_info
            ),
        ]


# ── Entities ──────────────────────────────────────────────────────────────────

class _BatteryControlNumber(CoordinatorEntity, RestoreNumber):
    """Setpoint kept locally and sent with the next forced charge/discharge.

    When the API currently exposes the signal (forced charge/discharge active),
    a change is also written immediately.
    """

    _key: str
    _label: str
    _default_min: float
    _default_max: float
    _attr_mode = NumberMode.BOX
    _attr_native_step = 1

    def __init__(self, control: BatteryControl, device_info):
        super().__init__(control.coordinator)
        self._control = control
        self._attr_device_info = device_info

        device_id = list(device_info["identifiers"])[0][1]
        self._attr_unique_id = f"{device_id}_{self._key}"
        self._attr_name = self._label
        self.entity_id = generate_entity_id(
            ENTITY_ID_FORMAT, f"fsp_{device_id}_{self._key}", hass=control.hass
        )

    def _signal(self):
        raise NotImplementedError

    @property
    def native_min_value(self) -> float:
        sig = self._signal()
        return sig["min"] if sig and sig.get("min") is not None else self._default_min

    @property
    def native_max_value(self) -> float:
        sig = self._signal()
        return sig["max"] if sig and sig.get("max") is not None else self._default_max

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success and self.coordinator.data is not None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_number_data()
        if last is not None and last.native_value is not None:
            self._restore(last.native_value)

    def _restore(self, value: float) -> None:
        raise NotImplementedError


class FusionSolarBatteryForcedPeriodNumber(_BatteryControlNumber):
    """Forced charge/discharge period in minutes (Duration mode)."""

    _key = "forced_charge_discharge_period"
    _label = "Forced Charge/Discharge Period"
    _default_min = 0
    _default_max = 1440
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_device_class = NumberDeviceClass.DURATION
    _attr_icon = "mdi:timer-outline"

    def _signal(self):
        return self._control.signal(self._control.period_id)

    @property
    def native_value(self) -> float | None:
        return self._control.period

    def _restore(self, value: float) -> None:
        if self._control.period is None:
            self._control.period = value

    async def async_set_native_value(self, value: float) -> None:
        await self._control.async_set_period(value)
        self.async_write_ha_state()


class FusionSolarBatteryTargetSocNumber(_BatteryControlNumber):
    """Target SOC in % (Energy mode)."""

    _key = "forced_charge_discharge_target_soc"
    _label = "Forced Charge/Discharge Target SOC"
    _default_min = 0
    _default_max = 100
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_device_class = NumberDeviceClass.BATTERY
    _attr_icon = "mdi:battery-arrow-up"

    def _signal(self):
        return self._control.signal(self._control.target_soc_id)

    @property
    def native_value(self) -> float | None:
        return self._control.target_soc

    def _restore(self, value: float) -> None:
        if self._control.target_soc is None:
            self._control.target_soc = value

    async def async_set_native_value(self, value: float) -> None:
        await self._control.async_set_target_soc(value)
        self.async_write_ha_state()


class FusionSolarBatteryForcedDischargePowerNumber(_BatteryControlNumber):
    """Forced discharge power in kW (sent with Discharge)."""

    _key = "forced_discharge_power"
    _label = "Forced Discharge Power"
    _default_min = 0
    _default_max = 3.5
    _attr_native_step = 0.1
    _attr_native_unit_of_measurement = UnitOfPower.KILO_WATT
    _attr_device_class = NumberDeviceClass.POWER
    _attr_icon = "mdi:battery-arrow-down"

    def _signal(self):
        return self._control.signal(SIGNAL_FORCED_DISCHARGE_POWER)

    @property
    def native_value(self) -> float | None:
        return self._control.discharge_power

    def _restore(self, value: float) -> None:
        if self._control.discharge_power is None:
            self._control.discharge_power = value

    async def async_set_native_value(self, value: float) -> None:
        await self._control.async_set_discharge_power(value)
        self.async_write_ha_state()
