"""Select platform for Battery devices (forced charge/discharge)."""

import logging

from homeassistant.components.select import SelectEntity, ENTITY_ID_FORMAT
from homeassistant.helpers.entity import generate_entity_id
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ...api.devices.battery_api import (
    SIGNAL_FORCED_CHARGE_DISCHARGE,
    SIGNAL_FORCED_SETTING_MODE,
)
from .control import (
    ACTION_OPTIONS,
    MODE_OPTIONS,
    BatteryControl,
    async_get_battery_control,
)

_LOGGER = logging.getLogger(__name__)


# ── Handler ───────────────────────────────────────────────────────────────────

class BatterySelectHandler:
    """Creates the forced charge/discharge Select entities of a battery."""

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
            FusionSolarBatteryForcedActionSelect(self.control, self.device_info),
            FusionSolarBatteryForcedModeSelect(self.control, self.device_info),
        ]


# ── Entities ──────────────────────────────────────────────────────────────────

class _BatteryControlSelect(CoordinatorEntity, SelectEntity):
    _signal_id: int
    _options_map: dict[str, str]
    _key: str
    _label: str

    def __init__(self, control: BatteryControl, device_info):
        super().__init__(control.coordinator)
        self._control = control
        self._attr_device_info = device_info
        self._reverse = {v: k for k, v in self._options_map.items()}

        device_id = list(device_info["identifiers"])[0][1]
        self._attr_unique_id = f"{device_id}_{self._key}"
        self._attr_name = self._label
        self._attr_options = list(self._options_map.values())
        self.entity_id = generate_entity_id(
            ENTITY_ID_FORMAT, f"fsp_{device_id}_{self._key}", hass=control.hass
        )

    @property
    def current_option(self) -> str | None:
        return self._options_map.get(self._control.value(self._signal_id))

    @property
    def available(self) -> bool:
        return (
            self.coordinator.last_update_success
            and self._control.signal(self._signal_id) is not None
        )

    async def async_select_option(self, option: str) -> None:
        key = self._reverse.get(option)
        if key is None:
            _LOGGER.error("Unknown option for %s: %s", self._label, option)
            return
        await self._async_write(key)
        self.async_write_ha_state()

    async def _async_write(self, key: str) -> None:
        raise NotImplementedError


class FusionSolarBatteryForcedActionSelect(_BatteryControlSelect):
    """Forced charge/discharge: Stop / Charge / Discharge (230320245)."""

    _signal_id = SIGNAL_FORCED_CHARGE_DISCHARGE
    _options_map = ACTION_OPTIONS
    _key = "forced_charge_discharge"
    _label = "Forced Charge/Discharge"
    _attr_icon = "mdi:battery-sync"

    async def _async_write(self, key: str) -> None:
        await self._control.async_set_action(key)


class FusionSolarBatteryForcedModeSelect(_BatteryControlSelect):
    """Forced charge/discharge setting mode: Duration / Energy (230320257)."""

    _signal_id = SIGNAL_FORCED_SETTING_MODE
    _options_map = MODE_OPTIONS
    _key = "forced_charge_discharge_mode"
    _label = "Forced Charge/Discharge Mode"
    _attr_icon = "mdi:tune-variant"

    async def _async_write(self, key: str) -> None:
        await self._control.async_set_mode(key)
