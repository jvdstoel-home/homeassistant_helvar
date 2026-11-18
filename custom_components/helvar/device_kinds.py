"""Decide which Home Assistant platform a Helvar load device belongs to."""
from __future__ import annotations

# Screens are driven like the button panels: see blinds.py.


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
