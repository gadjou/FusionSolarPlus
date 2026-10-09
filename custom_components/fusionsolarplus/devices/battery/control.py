"""Forced charge/discharge control shared by the battery select and number entities.

The FusionSolar web UI exposes, in the "Forced charge/discharge" group of the
battery configuration:
- Charge/Discharge (230320245): 0 = Stop, 1 = Charge, 2 = Discharge
- Setting mode (230320257): 0 = Duration, 1 = Energy
- Forced charge/discharge period (min) — used with the Duration mode
- Target SOC (%) — used with the Energy mode

The period and target SOC signals are only returned by the API in some states,
so their ids are discovered at runtime (see ``find_forced_signal_id``) and the
values chosen in Home Assistant are kept locally and sent together with the
Charge/Discharge command, like the web UI does.
"""

import asyncio
import logging
import time
from datetime import timedelta
from typing import Any, Dict

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from ...api.devices.battery_api import (
    SIGNAL_FORCED_CHARGE_DISCHARGE,
    SIGNAL_FORCED_SETTING_MODE,
    find_forced_signal_id,
)
from ...const import DOMAIN
from ...device_handler import BaseDeviceHandler

_LOGGER = logging.getLogger(__name__)

ACTION_OPTIONS = {"0": "Stop", "1": "Charge", "2": "Discharge"}
MODE_OPTIONS = {"0": "Duration", "1": "Energy"}

MODE_DURATION = "0"
MODE_ENERGY = "1"
ACTION_STOP = "0"

UNIT_PERIOD = "min"
UNIT_TARGET_SOC = "%"

# A value written but not yet reported back by the API is shown for this long.
PENDING_TIMEOUT = 120


class BatteryControlHandler(BaseDeviceHandler):
    """Fetches the battery configuration signals."""

    async def _async_get_data(self) -> Dict[str, Any]:
        async def fetch(client):
            return await self.hass.async_add_executor_job(
                client.get_battery_config, self.device_id
            )

        return await self._get_client_and_retry(fetch)

    async def create_coordinator(self) -> DataUpdateCoordinator:
        coordinator = DataUpdateCoordinator(
            self.hass,
            _LOGGER,
            name=f"{self.device_name} FusionSolar Battery Config",
            update_method=self._async_get_data,
            update_interval=timedelta(seconds=60),
        )
        await coordinator.async_config_entry_first_refresh()
        return coordinator


class BatteryControl:
    """State and write logic for forced charge/discharge of one battery."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, coordinator):
        self.hass = hass
        self.entry = entry
        self.coordinator = coordinator
        self.battery_dn = entry.data.get("device_id")
        # Values chosen in Home Assistant, sent when charge/discharge starts.
        self.mode = MODE_DURATION
        self.period: float | None = None
        self.target_soc: float | None = None
        # Discovered signal ids (kept once seen, the API hides them when stopped).
        self.period_id: int | None = None
        self.target_soc_id: int | None = None
        self._pending: dict[int, tuple[str, float]] = {}
        self.handle_update()
        self.unsubscribe = coordinator.async_add_listener(self.handle_update)

    # ── Reading ───────────────────────────────────────────────────────────────

    def signal(self, signal_id: int | None) -> dict[str, Any] | None:
        if signal_id is None or not self.coordinator.data:
            return None
        return self.coordinator.data.get(signal_id)

    def value(self, signal_id: int | None) -> str | None:
        """Pending value if a write is in flight, else the API value."""
        pending = self._pending.get(signal_id)
        sig = self.signal(signal_id)
        api_value = None if sig is None else sig.get("value")
        if pending is not None:
            pending_value, written_at = pending
            if (
                _same_value(api_value, pending_value)
                or time.monotonic() - written_at > PENDING_TIMEOUT
            ):
                del self._pending[signal_id]
            else:
                return pending_value
        return api_value

    def _discover(self) -> None:
        data = self.coordinator.data or {}
        self.period_id = find_forced_signal_id(data, UNIT_PERIOD) or self.period_id
        self.target_soc_id = (
            find_forced_signal_id(data, UNIT_TARGET_SOC) or self.target_soc_id
        )

    def handle_update(self) -> None:
        """Sync local values from the API after each coordinator refresh."""
        self._discover()
        mode = self.value(SIGNAL_FORCED_SETTING_MODE)
        if mode in MODE_OPTIONS:
            self.mode = mode
        self.period = _as_float(self.value(self.period_id), self.period)
        self.target_soc = _as_float(self.value(self.target_soc_id), self.target_soc)

    # ── Writing ───────────────────────────────────────────────────────────────

    async def _write(self, changes: dict[int, str]) -> None:
        client = self.hass.data[DOMAIN][self.entry.entry_id]
        _LOGGER.debug("Writing battery %s config: %s", self.battery_dn, changes)
        await self.hass.async_add_executor_job(
            client.set_battery_config, self.battery_dn, changes
        )
        now = time.monotonic()
        for signal_id, value in changes.items():
            self._pending[signal_id] = (value, now)

    def _setpoint_change(self) -> dict[int, str]:
        """The period or target SOC matching the current setting mode."""
        if self.mode == MODE_DURATION and self.period_id and self.period is not None:
            return {self.period_id: _format(self.period, self.signal(self.period_id))}
        if (
            self.mode == MODE_ENERGY
            and self.target_soc_id
            and self.target_soc is not None
        ):
            return {
                self.target_soc_id: _format(
                    self.target_soc, self.signal(self.target_soc_id)
                )
            }
        return {}

    async def async_set_action(self, action: str) -> None:
        if action == ACTION_STOP:
            await self._write({SIGNAL_FORCED_CHARGE_DISCHARGE: ACTION_STOP})
            await self.coordinator.async_request_refresh()
            return

        setpoint = self._setpoint_change()
        await self._write(
            {
                SIGNAL_FORCED_SETTING_MODE: self.mode,
                **setpoint,
                SIGNAL_FORCED_CHARGE_DISCHARGE: action,
            }
        )
        await self.coordinator.async_refresh()

        if not setpoint:
            # The period / target SOC signal was unknown until now: the API only
            # exposes it once forced charge/discharge is active.
            self._discover()
            setpoint = self._setpoint_change()
            if setpoint:
                await self._write(setpoint)
                await self.coordinator.async_request_refresh()
            else:
                _LOGGER.warning(
                    "Battery %s: no %s signal found in the forced charge/discharge "
                    "group, it was not sent",
                    self.battery_dn,
                    "period" if self.mode == MODE_DURATION else "target SOC",
                )

    async def async_set_mode(self, mode: str) -> None:
        self.mode = mode
        await self._write({SIGNAL_FORCED_SETTING_MODE: mode})
        await self.coordinator.async_request_refresh()

    async def async_set_period(self, period: float) -> None:
        self.period = period
        await self._write_setpoint_if_visible(self.period_id, period)

    async def async_set_target_soc(self, target_soc: float) -> None:
        self.target_soc = target_soc
        await self._write_setpoint_if_visible(self.target_soc_id, target_soc)

    async def _write_setpoint_if_visible(self, signal_id, value: float) -> None:
        """Write now if the API currently exposes the signal, else on next start."""
        sig = self.signal(signal_id)
        if sig is None:
            return
        await self._write({signal_id: _format(value, sig)})
        await self.coordinator.async_request_refresh()


async def async_get_battery_control(
    hass: HomeAssistant, entry: ConfigEntry, device_info: Dict[str, Any]
) -> BatteryControl:
    """Return the BatteryControl of the entry, shared by select and number."""
    domain_data = hass.data[DOMAIN]
    lock = domain_data.setdefault(f"{entry.entry_id}_battery_control_lock", asyncio.Lock())
    async with lock:
        key = f"{entry.entry_id}_battery_control"
        if key not in domain_data:
            handler = BatteryControlHandler(hass, entry, device_info)
            coordinator = await handler.create_coordinator()
            domain_data[key] = BatteryControl(hass, entry, coordinator)
        return domain_data[key]


def _same_value(api_value: Any, written: str) -> bool:
    if api_value is None:
        return False
    try:
        return abs(float(api_value) - float(written)) < 1e-6
    except (TypeError, ValueError):
        return str(api_value) == written


def _as_float(value: Any, default: float | None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _format(value: float, signal: dict[str, Any] | None) -> str:
    precision = int((signal or {}).get("precision") or 0)
    return f"{value:.{precision}f}"
