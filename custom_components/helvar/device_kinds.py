"""Decide which Home Assistant platform a Helvar load device belongs to."""
from __future__ import annotations

# Level commands for a 490 Blinds Controller channel (direct level, 0-100).
# Assumption, to be confirmed on site: like other DALI blind modules,
# max = up/open, min = down/close, off = stop.
BLIND_OPEN_LEVEL = 100
BLIND_CLOSE_LEVEL = 1
BLIND_STOP_LEVEL = 0


def is_blind(device) -> bool:
    """490 Blinds Controller channel."""
    part = getattr(getattr(device, "type", None), "part_number", None)
    return device.protocol == "DIGIDIM" and part == "490"


def is_virtual_switch(device) -> bool:
    """DALI device of unknown type 0xFF: in this installation a virtual on/off status
    (e.g. "V: Status Weerstation"), not a lamp."""
    from aiohelvar.static import UNKNOWN_DALI_TYPE

    return device.protocol == "DALI" and device.type == UNKNOWN_DALI_TYPE


def is_light(device) -> bool:
    return device.is_load and not is_blind(device) and not is_virtual_switch(device)
