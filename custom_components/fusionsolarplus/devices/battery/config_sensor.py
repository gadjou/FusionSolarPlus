"""Read-only sensors from the battery configuration (forced charge/discharge)."""

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    ENTITY_ID_FORMAT,
)
from homeassistant.const import UnitOfEnergy, UnitOfTime
from homeassistant.helpers.entity import generate_entity_id
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ...api.devices.battery_api import (
    SIGNAL_FORCED_DISCHARGE_ENERGY,
    SIGNAL_FORCED_REMAINING_TIME,
)
from .control import BatteryControl

# (signal id, key, label, unit, device class, icon)
CONFIG_SENSORS = [
    (
        SIGNAL_FORCED_REMAINING_TIME,
        "forced_charge_discharge_remaining_time",
        "Forced Charge/Discharge Remaining Time",
        UnitOfTime.MINUTES,
        SensorDeviceClass.DURATION,
        "mdi:timer-sand",
    ),
    (
        SIGNAL_FORCED_DISCHARGE_ENERGY,
        "forced_discharge_energy",
        "Forced Discharge Energy",
        UnitOfEnergy.KILO_WATT_HOUR,
        SensorDeviceClass.ENERGY,
        "mdi:battery-minus",
    ),
]


def create_config_sensors(control: BatteryControl, device_info) -> list:
    return [
        FusionSolarBatteryConfigSensor(control, device_info, *spec)
        for spec in CONFIG_SENSORS
    ]


class FusionSolarBatteryConfigSensor(CoordinatorEntity, SensorEntity):
    """Value of a battery configuration signal.

    The API only returns these signals in some states; the sensor is
    unavailable while its signal is not returned.
    """

    def __init__(self, control, device_info, signal_id, key, label, unit, device_class, icon):
        super().__init__(control.coordinator)
        self._control = control
        self._signal_id = signal_id
        self._attr_device_info = device_info
        self._attr_name = label
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        self._attr_icon = icon

        device_id = list(device_info["identifiers"])[0][1]
        self._attr_unique_id = f"{device_id}_{key}"
        self.entity_id = generate_entity_id(
            ENTITY_ID_FORMAT, f"fsp_{device_id}_{key}", hass=control.hass
        )

    @property
    def native_value(self) -> float | None:
        try:
            return float(self._control.value(self._signal_id))
        except (TypeError, ValueError):
            return None

    @property
    def available(self) -> bool:
        return (
            self.coordinator.last_update_success
            and self._control.signal(self._signal_id) is not None
        )
