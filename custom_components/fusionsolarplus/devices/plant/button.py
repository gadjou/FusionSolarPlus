"""Button platform for Plant devices."""

import asyncio
import logging
from typing import Dict, Any

from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.components.button import ButtonEntity, ENTITY_ID_FORMAT
from homeassistant.helpers.entity import generate_entity_id

from ...device_handler import BaseDeviceHandler
from ...const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class PlantButtonHandler(BaseDeviceHandler):
    """Handler that creates Button entities for Plant devices."""

    async def _async_get_data(self) -> Dict[str, Any]:
        """Plant button handler reuses the main coordinator — no separate poll."""
        return {}

    def create_entities(self, coordinator) -> list:
        return [
            FusionSolarRefreshButton(
                coordinator=coordinator,
                device_info=self.device_info,
            )
        ]


class FusionSolarRefreshButton(CoordinatorEntity, ButtonEntity):
    """Button that forces a live data refresh on the FusionSolar plant.

    Without an active livedata subscription, FusionSolar caches energy-flow
    data server-side. This button:
      1. Subscribes to livedata -> backend updates every refreshPeriod seconds
      2. Waits refreshPeriod + 1s for fresh data to be ready
      3. Polls the coordinator -> HA gets the fresh data immediately
    """

    def __init__(self, coordinator, device_info):
        super().__init__(coordinator)
        self._attr_device_info = device_info

        device_id = list(device_info["identifiers"])[0][1]
        self._attr_unique_id = f"{device_id}_live_data"
        self._attr_name = "Live Data"
        self._attr_icon = "mdi:refresh"

        self.entity_id = generate_entity_id(
            ENTITY_ID_FORMAT,
            f"fsp_{device_id}_live_data",
            hass=coordinator.hass,
        )

    async def async_press(self) -> None:
        """Subscribe to livedata, wait for fresh data, then poll coordinator."""
        device_dn = list(self._attr_device_info["identifiers"])[0][1]
        client = self.hass.data[DOMAIN][self.coordinator.config_entry.entry_id]

        # Step 1 - subscribe: forces FusionSolar backend to prepare fresh data
        try:
            result = await self.hass.async_add_executor_job(
                client.refresh_livedata, device_dn
            )
            refresh_period = result.get("subscribeInfo", {}).get("refreshPeriod", 2)
            _LOGGER.debug("Livedata subscribed - refreshPeriod=%ss", refresh_period)
        except Exception as err:
            _LOGGER.warning("Livedata subscribe failed: %s", err)
            refresh_period = 2

        # Step 2 - wait for backend to serve fresh data
        await asyncio.sleep(refresh_period + 1)

        # Step 3 - poll: HA fetches the now-fresh data
        await self.coordinator.async_request_refresh()

    @property
    def available(self) -> bool:
        return True
