"""Screens (490 Blinds Controller channels).

Up/down go through scenes, like the weather sequences in the Designer project:
every 490 channel has the standard scene table (1.1 = 100 = up, 1.15/1.16 = 0 = down).
Proportion commands sent by the router (C:17/C:18) did not move a screen on site
(18 Nov), while button panels use them directly on the bus; they are only kept for
stop (opposite direction while running, as on the panels), which is still to be tested.
Note: Helvar blocks scenes for the ground-floor screens while it rains.

Panel behaviour (for tracking):

Observed on site (18 Nov 2026): every panel sends "modify proportion" to the
room's blinds group, C:17 with F:15:

- down: P:0
- up:   P:-1
- stop: the opposite direction while the 490 still counts its run time

The channel level (C:152) does not tell the position, so the state in Home
Assistant is the last direction commanded (by HA or by a panel).
"""
from __future__ import annotations

import logging
import time

_LOGGER = logging.getLogger(__name__)

UP = "up"
DOWN = "down"
STOPPED = "stopped"
PROPORTION = {DOWN: 0, UP: -1}
SCENE = {UP: 1, DOWN: 15}  # block 1
FADE = 15  # 1/100 s, as the panels send it
# The 490's run time lies between 43 s and 98 s (measured on 18 Nov: "up" 43 s after
# "down" acted as stop, 98 s after it moved). Within RUN_TIME the opposite direction
# is a stop; after it, it would start the screen moving, so a stop is not sent then.
RUN_TIME = 40  # s


class BlindState:
    """Last commanded direction per channel and per group, shared by covers and actions."""

    def __init__(self, api) -> None:
        self.api = api
        self.devices: dict[str, tuple[str, float]] = {}
        self.groups: dict[int, tuple[str, float]] = {}
        self.listeners: list = []
        self._sent: list[tuple[str, float]] = []

    def _remember(self, command: str) -> None:
        now = time.monotonic()
        self._sent = [(c, t) for c, t in self._sent if now - t < 1.5] + [(command, now)]

    def _is_own_echo(self, cmd: int, params: dict, address) -> bool:
        now = time.monotonic()
        key = (
            f"C:{cmd},G:{params.get('G')},P:{params.get('P')}"
            if cmd == 17
            else f"C:{cmd},P:{params.get('P')},@{address}"
        )
        for i, (c, t) in enumerate(self._sent):
            if c == key and now - t < 1.5:
                del self._sent[i]
                return True
        return False

    # ------------------------------------------------------------------ state
    def _members(self, group_id: int) -> list[str]:
        group = self.api.groups.groups.get(group_id)
        return [str(a) for a in getattr(group, "devices", [])] if group else []

    def record_group(self, group_id: int, direction: str) -> None:
        now = time.monotonic()
        self.groups[group_id] = (direction, now)
        for address in self._members(group_id):
            self.devices[address] = (direction, now)
        self._notify()

    def record_device(self, address: str, direction: str) -> None:
        self.devices[str(address)] = (direction, time.monotonic())
        self._notify()

    def record_stop_device(self, address: str) -> None:
        self.devices[str(address)] = (STOPPED, time.monotonic())
        self._notify()

    def record_stop_group(self, group_id: int) -> None:
        now = time.monotonic()
        self.groups[group_id] = (STOPPED, now)
        for address in self._members(group_id):
            self.devices[address] = (STOPPED, now)
        self._notify()

    def device_state(self, address: str):
        return self.devices.get(str(address))

    def _notify(self) -> None:
        for listener in list(self.listeners):
            try:
                listener()
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Blind state listener failed")

    # ---------------------------------------------------------------- sending
    async def move_group(self, group_id: int, direction: str) -> None:
        await self.api.send_string(
            f">V:2,C:11,G:{int(group_id)},B:1,S:{SCENE[direction]},F:0#"
        )
        self.record_group(int(group_id), direction)

    async def move_device(self, address: str, direction: str) -> None:
        addr = str(address).lstrip("@")
        # C:12 = recall scene on one device.
        await self.api.send_string(f">V:2,C:12,B:1,S:{SCENE[direction]},F:0,@{addr}#")
        self.record_device(f"@{addr}", direction)

    async def stop_group(self, group_id: int) -> None:
        last = self.groups.get(int(group_id))
        if last is None:
            # Fall back to the members' last direction.
            directions = [
                self.devices[a][0]
                for a in self._members(int(group_id))
                if a in self.devices and self.devices[a][0] != STOPPED
            ]
            times = [
                self.devices[a][1]
                for a in self._members(int(group_id))
                if a in self.devices and self.devices[a][0] != STOPPED
            ]
            last = (
                (max(set(directions), key=directions.count), max(times)) if directions else None
            )
        if last is None or last[0] == STOPPED or time.monotonic() - last[1] > RUN_TIME:
            _LOGGER.info("Stop for group %s not sent: not moving (as far as known)", group_id)
            return
        opposite = UP if last[0] == DOWN else DOWN
        self._remember(f"C:17,G:{int(group_id)},P:{PROPORTION[opposite]}")
        await self.api.send_string(
            f">V:2,C:17,G:{int(group_id)},P:{PROPORTION[opposite]},F:{FADE}#"
        )
        self.record_stop_group(int(group_id))

    async def stop_device(self, address: str) -> None:
        last = self.device_state(address)
        if last is None or last[0] == STOPPED or time.monotonic() - last[1] > RUN_TIME:
            _LOGGER.info("Stop for %s not sent: not moving (as far as known)", address)
            return
        opposite = UP if last[0] == DOWN else DOWN
        addr = str(address).lstrip("@")
        self._remember(f"C:18,P:{PROPORTION[opposite]},@{addr}")
        await self.api.send_string(
            f">V:2,C:18,P:{PROPORTION[opposite]},F:{FADE},@{addr}#"
        )
        self.record_stop_device(f"@{addr}")

    # ------------------------------------------------- commands from panels
    def on_control(self, cmd, _description, params, address) -> None:
        """Track C:17/C:18 that the router reports (panels, sequences)."""
        if cmd not in (17, 18):
            return
        if self._is_own_echo(cmd, params, address):
            return
        p = params.get("P")
        if p == "0":
            direction = DOWN
        elif p == "-1":
            direction = UP
        else:
            return
        if cmd == 17 and params.get("G", "").isdigit():
            group_id = int(params["G"])
            last = self.groups.get(group_id)
            # Opposite direction within the run time acts as stop on the 490.
            if last and last[0] not in (direction, STOPPED) and time.monotonic() - last[1] < RUN_TIME:
                self.record_stop_group(group_id)
            else:
                self.record_group(group_id, direction)
        elif cmd == 18 and address:
            key = f"@{address}"
            last = self.device_state(key)
            if last and last[0] not in (direction, STOPPED) and time.monotonic() - last[1] < RUN_TIME:
                self.record_stop_device(key)
            else:
                self.record_device(key, direction)


    def on_scene(self, scene_address, _fade_time) -> None:
        """A scene recall on a group with screens: level 100 = up, 0 = down."""
        group = self.api.groups.groups.get(scene_address.group)
        if group is None:
            return
        now = time.monotonic()
        changed = False
        for address in getattr(group, "devices", []):
            device = self.api.devices.devices.get(address)
            if device is None or not _is_blind(device):
                continue
            level = device.get_level_for_scene(scene_address) if hasattr(
                device, "get_level_for_scene"
            ) else None
            try:
                level = float(level)
            except (TypeError, ValueError):
                continue  # '*' = this channel ignores the scene
            direction = UP if level >= 100 else DOWN if level <= 0 else STOPPED
            self.devices[str(address)] = (direction, now)
            changed = True
        if changed:
            self._notify()


def _is_blind(device) -> bool:
    from .device_kinds import is_blind

    return is_blind(device)


def get_blind_state(api) -> BlindState:
    state = getattr(api, "_blind_state", None)
    if state is None:
        state = api._blind_state = BlindState(api)
        listeners = getattr(api, "_control_listeners", None)
        if listeners is None:
            listeners = api._control_listeners = []
        listeners.append(state.on_control)
        scene_listeners = getattr(api, "_scene_listeners", None)
        if scene_listeners is None:
            scene_listeners = api._scene_listeners = []
        scene_listeners.append(state.on_scene)
    return state
