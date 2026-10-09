"""Battery API helpers."""

from __future__ import annotations

import html
import json
import logging
import time
from typing import Any

from custom_components.fusionsolarplus.api.constants import MODULE_SIGNALS
from custom_components.fusionsolarplus.api.exceptions import FusionSolarException


def get_battery_ids(client: Any, plant_id) -> list:
    plant_flow = client.get_plant_flow(plant_id)
    nodes = plant_flow["data"]["flow"]["nodes"]
    battery_ids = []

    for node in nodes:
        name = node.get("name", "")
        dev_ids = node.get("devIds")
        logging.debug("Processing node: name=%r devIds=%r", name, dev_ids)
        if "energy_store" in name:
            if isinstance(dev_ids, list) and dev_ids:
                battery_ids.extend(dev_ids)
            else:
                logging.warning(
                    "Node with 'energy_store' in name but devIds is not a non-empty list: %r",
                    node,
                )
    return battery_ids


def get_battery_day_stats(
    client: Any, battery_id: str, query_time: int | None = None
) -> dict:
    current_time = round(time.time() * 1000)
    if query_time is not None:
        current_time = query_time
    r = client._session.get(
        url=f"https://{client._huawei_subdomain}.fusionsolar.huawei.com/rest/pvms/web/device/v1/device-history-data",
        params={
            "signalIds": ["30005", "30007"],
            "deviceDn": battery_id,
            "date": current_time,
            "_": current_time,
        },
    )
    r.raise_for_status()
    battery_data = r.json()
    if not battery_data["success"] or "data" not in battery_data:
        raise FusionSolarException(
            f"Failed to retrieve battery day stats for {battery_id}"
        )
    battery_data["data"]["30005"]["name"] = "Charge/Discharge power"
    battery_data["data"]["30007"]["name"] = "SOC"
    return battery_data["data"]


def get_battery_module_stats(
    client: Any, battery_id: str, module_id: str = "1", signal_ids: list | None = None
) -> dict:
    if signal_ids is None:
        signal_ids = MODULE_SIGNALS[module_id]
    elif not all(signal_id in MODULE_SIGNALS[module_id] for signal_id in signal_ids):
        raise ValueError(f"One or more unknown signal ids for module {module_id}")

    signal_ids_str = ",".join(signal_ids)
    r = client._session.get(
        url=f"https://{client._huawei_subdomain}.fusionsolar.huawei.com/rest/pvms/web/device/v1/query-battery-dc",
        params={
            "sigids": signal_ids_str,
            "dn": battery_id,
            "moduleId": module_id,
            "_": round(time.time() * 1000),
        },
    )
    r.raise_for_status()
    battery_data = r.json()
    if not battery_data["success"] or "data" not in battery_data:
        raise FusionSolarException(
            f"Failed to retrieve battery status for {battery_id}"
        )
    return battery_data["data"]


def get_battery_status(client: Any, battery_id: str) -> dict:
    r = client._session.get(
        url=f"https://{client._huawei_subdomain}.fusionsolar.huawei.com/rest/pvms/web/device/v1/device-realtime-data",
        params={"deviceDn": battery_id, "_": round(time.time() * 1000)},
    )
    r.raise_for_status()
    battery_data = r.json()
    if not battery_data["success"] or "data" not in battery_data:
        raise FusionSolarException(
            f"Failed to retrieve battery status for {battery_id}"
        )
    return battery_data["data"][1]["signals"]


def get_battery_data(client: Any, battery_id: str) -> dict:
    """Fetch and normalize battery status plus module-level values."""
    battery_signals = get_battery_status(client, battery_id)
    modules: dict[str, list[dict]] = {}
    module_values: dict[str, dict[int, Any]] = {}
    for module_id in ["1", "2", "3", "4"]:
        module_signals = get_battery_module_stats(client, battery_id, module_id)
        modules[module_id] = module_signals
        module_values[module_id] = _signals_to_value_map(module_signals)

    return {
        "battery": battery_signals,
        "modules": modules,
        "battery_values": _signals_to_value_map(battery_signals, "value"),
        "module_values": {
            module_id: _signals_to_value_map(modules[module_id], "realValue")
            for module_id in modules
        },
    }


def _signals_to_value_map(
    signals: list[dict], value_key: str = "value"
) -> dict[int, Any]:
    values: dict[int, Any] = {}
    for signal in signals:
        signal_id = signal.get("id")
        if signal_id is None:
            continue

        raw_value = signal.get(value_key)

        if raw_value in (None, "-", "N/A", "n/a"):
            values[int(signal_id)] = None
            continue

        try:
            values[int(signal_id)] = float(raw_value)
        except (TypeError, ValueError):
            values[int(signal_id)] = raw_value

    return values


# ── Battery configuration (forced charge/discharge) ───────────────────────────

# "Charge/décharge" — 0 = Stop, 1 = Charge, 2 = Discharge
SIGNAL_FORCED_CHARGE_DISCHARGE = 230320245
# "Mode de paramétrage" — 0 = Duration, 1 = Energy (target SOC)
SIGNAL_FORCED_SETTING_MODE = 230320257
# "Période de charge/décharge forcée (min)" — used with the Duration mode
SIGNAL_FORCED_PERIOD = 230320281
# "SOC cible (%)" — used with the Energy mode
SIGNAL_FORCED_TARGET_SOC = 230320246


def get_battery_config(client: Any, battery_id: str) -> dict[int, dict[str, Any]]:
    """Fetch the battery configuration signals, keyed by signal id.

    Each value contains ``value``, ``unit``, ``group``, ``edit``, ``precision``,
    ``min``/``max`` (when the API exposes a range) and ``enum`` (key → label).
    """
    r = client._session.get(
        url=f"https://{client._huawei_subdomain}.fusionsolar.huawei.com/rest/pvms/web/device/v1/deviceExt/get-config-signals",
        params={"dn": battery_id, "_": round(time.time() * 1000)},
    )
    r.raise_for_status()
    payload = r.json()
    if payload.get("code") != 0 or not isinstance(payload.get("data"), list):
        raise FusionSolarException(
            f"get-config-signals failed for {battery_id}: {payload.get('description')}"
        )

    signals: dict[int, dict[str, Any]] = {}
    for group in payload["data"]:
        for signal in group.get("configSignalDisplayList") or []:
            if signal.get("id") is None:
                continue
            ranges = (signal.get("valueRange") or {}).get("ranges") or []
            enum: dict[str, str] = {}
            for entry in signal.get("enumListEntry") or []:
                if isinstance(entry, dict):
                    enum.update({str(k): html.unescape(str(v)) for k, v in entry.items()})
            signals[int(signal["id"])] = {
                "name": html.unescape(signal.get("name") or ""),
                "value": signal.get("value"),
                "unit": signal.get("unit") or "",
                "group": html.unescape(
                    signal.get("displayGroup") or group.get("groupName") or ""
                ),
                "edit": bool(signal.get("edit")),
                "precision": signal.get("precision") or 0,
                "min": ranges[0].get("minValue") if ranges else None,
                "max": ranges[0].get("maxValue") if ranges else None,
                "enum": enum,
            }
    return signals


def find_forced_signal_id(signals: dict[int, dict[str, Any]], unit: str) -> int | None:
    """Find an editable signal of the forced charge/discharge group by its unit.

    The period ("min") and target SOC ("%") signals are only exposed by the API
    for some states, and their names are localized, so they are located in the
    group that holds the Charge/Discharge signal.
    """
    anchor = signals.get(SIGNAL_FORCED_CHARGE_DISCHARGE)
    if anchor is None:
        return None
    for signal_id, signal in signals.items():
        if (
            signal["group"] == anchor["group"]
            and signal["edit"]
            and signal["unit"] == unit
        ):
            return signal_id
    return None


def set_battery_config(client: Any, battery_id: str, changes: dict[int, str]) -> dict:
    """Write one or more battery configuration signals in a single request.

    Mirrors the FusionSolar web UI: set-config-signals, then signal-refresh so
    the backend re-reads the configuration from the device.
    """
    base = f"https://{client._huawei_subdomain}.fusionsolar.huawei.com"
    r = client._session.post(
        url=f"{base}/rest/pvms/web/device/v1/deviceExt/set-config-signals",
        data={
            "dn": battery_id,
            "changeValues": json.dumps(
                [{"id": str(sid), "value": str(value)} for sid, value in changes.items()],
                separators=(",", ":"),
            ),
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    r.raise_for_status()
    response = r.json()
    logging.debug("set_battery_config %s %s → %s", battery_id, changes, response)
    if response.get("code") != 0 or any(
        item.get("code") != 0 for item in response.get("data") or []
    ):
        raise FusionSolarException(
            f"set-config-signals failed for {battery_id}: {response}"
        )

    try:
        client._session.post(
            url=f"{base}/rest/pvms/web/monitor/v1/refresh/signal/signal-refresh",
            json={
                "dn": battery_id,
                "scenes": "config",
                "operateSerial": str(round(time.time() * 1000)),
            },
        ).raise_for_status()
    except Exception:
        logging.debug("signal-refresh failed for %s", battery_id, exc_info=True)
    return response
