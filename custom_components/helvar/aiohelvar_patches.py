"""Runtime fixes for aiohelvar 0.9.8 (applied by the Helvar integration).

1. initialize() now waits for groups, devices and scenes before returning, so
   Home Assistant creates the light entities after the devices are known.
2. Devices are queried on every router in the cluster (found via group
   membership, plus optional extra router ids), not only the connected one.
3. Only named scenes are registered (was 253 blocks x 16 scenes per group).
4. An error reply to "last scene in group" (=27) is no longer read as a scene.
5. Queries are limited to 8 at a time, and failures are logged instead of
   raising "Task exception was never retrieved".
"""
from __future__ import annotations

import asyncio
import logging
import re

import aiohelvar
from aiohelvar import devices as _devices
from aiohelvar import groups as _groups
from aiohelvar import router as _router
from aiohelvar import scenes as _scenes
from aiohelvar.parser.address import HelvarAddress, SceneAddress
from aiohelvar.parser.command import Command
from aiohelvar.parser.command_parameter import CommandParameter, CommandParameterType
from aiohelvar.parser.command_type import (
    COMMAND_TYPES_DONT_LISTEN_FOR_RESPONSE,
    CommandType,
    MessageType,
)

_LOGGER = logging.getLogger(__name__)

_PATCHED = False
MAX_PARALLEL_QUERIES = 8


class _ExpectedRouterErrors(logging.Filter):
    """Hide normal discovery answers: =23 (no such subnet/device), =27 (no scene yet)."""

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        if "triggered an error back from the router" in msg and (
            msg.endswith("=23#.") or msg.endswith("=27#.")
        ):
            return False
        if msg.startswith("Encountered unknown") and "device type" in msg:
            return False
        return True


async def _safe(coro, what):
    try:
        return await coro
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("%s failed: %r", what, err)
        return None


# --------------------------------------------------------------------- groups
async def _query_group_name(router, group_id):
    response = await router._send_command_task(
        Command(
            CommandType.QUERY_GROUP_DESCRIPTION,
            [CommandParameter(CommandParameterType.GROUP, group_id)],
        )
    )
    if response is None or response.command_message_type == MessageType.ERROR:
        return
    router.groups.update_group_name(group_id, response.result)


async def _query_group_devices(router, group_id):
    response = await router._send_command_task(
        Command(
            CommandType.QUERY_GROUP,
            [CommandParameter(CommandParameterType.GROUP, group_id)],
        )
    )
    if response is None or response.command_message_type == MessageType.ERROR:
        return
    if not response.result:
        return
    addresses = []
    for member in str(response.result).split(","):
        member = member.strip().strip("@")
        if not member:
            continue
        try:
            addresses.append(HelvarAddress(*member.split(".")))
        except (TypeError, ValueError) as err:
            _LOGGER.warning("Group %s: ignoring member %r: %s", group_id, member, err)
    router.groups.update_group_device_members(group_id, addresses)


async def _query_group_last_scene(router, group_id):
    response = await router._send_command_task(
        Command(
            CommandType.QUERY_LAST_SCENE_IN_GROUP,
            [CommandParameter(CommandParameterType.GROUP, group_id)],
        )
    )
    if response is None or response.command_message_type != MessageType.REPLY:
        return
    try:
        block, scene = _groups.blockscene_to_block_and_scene(int(response.result))
        scene_address = SceneAddress(group_id, int(block), int(scene))
    except (ValueError, TypeError):
        return
    await router.groups.handle_scene_callback(scene_address, 10)


async def update_all_last_scenes(router):
    await asyncio.gather(
        *[
            _safe(_query_group_last_scene(router, gid), f"Last scene of group {gid}")
            for gid in list(router.groups.groups.keys())
        ]
    )


async def get_groups(router):
    response = await router._send_command_task(Command(CommandType.QUERY_GROUPS))
    if response is None or not response.result:
        _LOGGER.debug("No groups returned by the router")
        return

    groups = []
    for group_id in str(response.result).split(","):
        group_id = group_id.strip()
        if not group_id:
            continue
        try:
            groups.append(_groups.Group(int(group_id)))
        except ValueError:
            _LOGGER.warning("Invalid group ID: %s", group_id)

    for group in groups:
        router.groups.register_group(group)

    await asyncio.gather(
        *[_safe(_query_group_name(router, g.group_id), f"Name of group {g.group_id}") for g in groups],
        *[_safe(_query_group_devices(router, g.group_id), f"Members of group {g.group_id}") for g in groups],
    )


_orig_handle_scene_callback = _groups.Groups.handle_scene_callback


async def _handle_scene_callback(self, scene_address, fade_time):
    if scene_address is not None and not self.router.scenes.has_scene(scene_address):
        self.router.scenes.register_scene(scene_address, _scenes.Scene(scene_address))
    await _orig_handle_scene_callback(self, scene_address, fade_time)
    if scene_address is not None:
        _schedule_group_refresh(self.router, scene_address.group, fade_time)


def _schedule_group_refresh(router, group_id, fade_time):
    """After a scene recall, read the real levels of the group's lamps once the fade is done.

    The levels computed from the scene table are only an estimate ('*' = unchanged,
    'L' = last level), so this keeps Home Assistant in line with the lamps, also
    when the scene was recalled from a wall switch or a schedule.
    """
    tasks = getattr(router, "_refresh_tasks", None)
    if tasks is None:
        tasks = router._refresh_tasks = {}
    previous = tasks.get(group_id)
    if previous is not None and not previous.done():
        previous.cancel()
    try:
        fade_s = float(fade_time or 0) / 100
    except (TypeError, ValueError):
        fade_s = 0
    tasks[group_id] = asyncio.create_task(
        _refresh_group_levels(router, group_id, min(fade_s, 60) + 1.5)
    )


async def _refresh_group_levels(router, group_id, delay):
    await asyncio.sleep(delay)
    group = router.groups.groups.get(group_id)
    if group is None:
        return
    for address in list(group.devices):
        device = router.devices.devices.get(address)
        if device is None or not device.is_load:
            continue
        try:
            response = await router._send_command_task(
                Command(CommandType.QUERY_DEVICE_LOAD_LEVEL, command_address=address)
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Refreshing level of %s failed: %r", address, err)
            continue
        if response is None or response.command_message_type != MessageType.REPLY:
            continue
        try:
            await router.devices.update_device_load_level(address, response.result)
        except (TypeError, ValueError):
            continue


# -------------------------------------------------------------------- devices
async def _update_device(self, address):
    device = self.devices[address]

    async def update_name():
        response = await self.router._send_command_task(
            Command(CommandType.QUERY_DEVICE_DESCRIPTION, command_address=device.address)
        )
        await self.update_device_name(device.address, response.result)

    async def update_state():
        response = await self.router._send_command_task(
            Command(CommandType.QUERY_DEVICE_STATE, command_address=device.address)
        )
        await self.update_device_state(device.address, response.result)

    async def update_load_level():
        response = await self.router._send_command_task(
            Command(CommandType.QUERY_DEVICE_LOAD_LEVEL, command_address=device.address)
        )
        await self.update_device_load_level(device.address, response.result)

    async def update_scene_level():
        response = await self.router._send_command_task(
            Command(CommandType.QUERY_SCENE_INFO, command_address=device.address)
        )
        self.update_device_scene_level(device.address, response.result)

    jobs = [update_name(), update_state()]
    if device.is_load:
        jobs += [update_load_level(), update_scene_level()]
    for result in await asyncio.gather(*jobs, return_exceptions=True):
        if isinstance(result, Exception):
            _LOGGER.warning("Updating device %s failed: %r", device.address, result)


def _get_level_for_scene(self, scene_address):
    """A device only stores levels for blocks 1-8; return None instead of raising."""
    if not self.levels or not self.is_load:
        return None
    # to_device_int() is 1-based (scene 1.1 = 1); the levels list is 0-based.
    index = scene_address.to_device_int() - 1
    if index < 0:
        return None
    try:
        return self.levels[index]
    except IndexError:
        return None


async def _set_device_brightness(self, address, brightness, fade_time=100):
    """HelvarNet expects an integer level 0-100; 0.9.8 sent e.g. 'L:0.0', which the router ignores."""
    level = int(round((brightness or 0) / 255 * 100))
    if brightness and level == 0:
        level = 1
    await self.router._send_command_task(
        Command(
            CommandType.DIRECT_LEVEL_DEVICE,
            [
                CommandParameter(CommandParameterType.LEVEL, str(level)),
                CommandParameter(CommandParameterType.FADE_TIME, str(fade_time)),
            ],
            command_address=address,
        )
    )
    await self.update_device_load_level(address, str(level))


async def _register_subnet(router, router_id, subnet_id):
    command = Command(
        CommandType.QUERY_DEVICE_TYPES_AND_ADDRESSES,
        command_address=HelvarAddress(router.cluster_id, router_id, subnet_id),
    )
    response = await router._send_command_task(command)
    if response is None or response.command_message_type == MessageType.ERROR:
        return
    if not response.result or "@" not in str(response.result):
        return

    registered = []
    for device_result in str(response.result).split(","):
        parts = device_result.split("@")
        if len(parts) != 2:
            continue
        device_type, device_id = parts
        address = HelvarAddress(router.cluster_id, router_id, subnet_id, device_id)
        router.devices.register_device(_devices.Device(address, device_type))
        registered.append(address)

    await asyncio.gather(
        *[router.devices.update_device(a) for a in registered], return_exceptions=True
    )


async def get_devices(router, router_ids=None):
    router_ids = router_ids or [router.router_id]
    await asyncio.gather(
        *[
            _safe(
                _register_subnet(router, r, s),
                f"Querying devices on {router.cluster_id}.{r}.{s}",
            )
            for r in router_ids
            for s in range(1, 5)
        ]
    )


# --------------------------------------------------------------------- scenes
async def get_scenes(router, groups):
    response = await router._send_command_task(Command(CommandType.QUERY_SCENE_NAMES))
    if response is None or not response.result:
        _LOGGER.debug("No scene names returned by the router")
        return
    for part in str(response.result).strip("@").split("@"):
        if ":" not in part:
            continue
        address, name = part.split(":", 1)
        try:
            scene_address = SceneAddress(*[int(a) for a in address.split(".")])
        except (TypeError, ValueError):
            continue
        router.scenes.register_scene(
            scene_address, _scenes.Scene(scene_address, name=name)
        )


_orig_get_scene = _scenes.Scenes.get_scene


def _get_scene(self, scene_address):
    if scene_address is None:
        return None
    return self.scenes.get(scene_address)


# --------------------------------------------------------------------- router
async def _handle_scene_recall(self, command):
    """aiohelvar's scene recall handling, plus notification of listeners (logbook)."""
    await _orig_handle_scene_recall(self, command)
    scene_address = command.get_scene_address()
    fade_time = command.get_param_value(CommandParameterType.FADE_TIME)
    for listener in list(getattr(self, "_scene_listeners", [])):
        try:
            listener(scene_address, fade_time)
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Scene listener failed")


_orig_handle_scene_recall = _router.Router.handle_scene_recall
_orig_router_init = _router.Router.__init__
_orig_connect = _router.Router.connect
_orig_send_command_task = _router.Router._send_command_task


def _router_init(self, host, port, *args, extra_router_ids=None, **kwargs):
    _orig_router_init(self, host, port, *args, **kwargs)
    self.extra_router_ids = [int(r) for r in (extra_router_ids or [])]
    self.router_ids = []
    self._query_semaphore = asyncio.Semaphore(MAX_PARALLEL_QUERIES)
    self._input_waiters = {}


# ------------------------------------------------- inputs over main session
QUERY_INPUTS = 151
_INPUT_REPLY = re.compile(r"^([?!>])V:\d+,C:151,@([\d.]+)(?:=(-?\d+))?#?$")


def _handle_input_reply(router, raw: bytes) -> bool:
    """Consume replies to C:151 (Query Inputs), which aiohelvar cannot parse."""
    text = raw.decode(errors="replace").strip()
    if ",C:151," not in text:
        return False
    match = _INPUT_REPLY.match(text)
    if match:
        kind, address, value = match.groups()
        waiter = router._input_waiters.get(address)
        if kind != ">" and waiter is not None and not waiter.done():
            waiter.set_result(int(value) if kind == "?" and value is not None else None)
    return True


# Control commands other than C:11 that the router reports when a button panel,
# sequence or other client changes lamps. aiohelvar cannot parse most of them.
CONTROL_COMMANDS = {
    12: "scène oproepen (apparaat)",
    13: "knop / direct niveau (groep)",
    14: "direct niveau (apparaat)",
    15: "directe proportie (groep)",
    16: "directe proportie (apparaat)",
    17: "proportie wijzigen (groep)",
    18: "proportie wijzigen (apparaat)",
}
_CONTROL = re.compile(r"^>V:\d+,C:(\d+)((?:,[A-Z]:[^,@#]*)*)(?:,?@([\d.]+))?#?$")


def _handle_other_control(router, raw: bytes) -> bool:
    """Log control commands other than scene recalls and re-read the affected levels."""
    text = raw.decode(errors="replace").strip()
    match = _CONTROL.match(text)
    if not match:
        return False
    cmd = int(match.group(1))
    if cmd not in CONTROL_COMMANDS:
        return False
    params = dict(
        part.split(":", 1) for part in match.group(2).split(",") if ":" in part
    )
    address = match.group(3)
    _LOGGER.info("Router reported %s: %s", CONTROL_COMMANDS[cmd], text)
    fade = params.get("F", 0)
    if "G" in params:
        try:
            _schedule_group_refresh(router, int(params["G"]), fade)
        except ValueError:
            pass
    elif address:
        for group_id, group in router.groups.groups.items():
            if any(str(d) == f"@{address}" or str(d) == address for d in group.devices):
                _schedule_group_refresh(router, group_id, fade)
    for listener in list(getattr(router, "_control_listeners", [])):
        try:
            listener(cmd, CONTROL_COMMANDS[cmd], params, address)
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Control listener failed")
    return True


async def query_input(router, address: str, timeout: float = 5.0):
    """Ask the router for the level (0-255) of an input over the main TCP session."""
    if not router.connected:
        raise ConnectionError("Helvar router not connected")
    async with router._query_semaphore:
        future = asyncio.get_running_loop().create_future()
        router._input_waiters[address] = future
        try:
            await router.send_string(f">V:2,C:{QUERY_INPUTS},@{address}#")
            return await asyncio.wait_for(future, timeout)
        finally:
            if router._input_waiters.get(address) is future:
                del router._input_waiters[address]


async def _stream_writer(self, reader, writer):
    """aiohelvar's writer, but a broken connection triggers a reconnect instead of a silent stop."""
    while True:
        command_string = await self.commands_to_send.get()
        try:
            _LOGGER.debug("Sending %s", command_string)
            writer.write(command_string)
            await asyncio.sleep(0.01)  # small gap; a router can be overloaded
            await writer.drain()
        except (ConnectionError, OSError, RuntimeError) as err:
            _LOGGER.warning("Sending to Helvar router %s failed: %r", self.host, err)
            self.commands_to_send.task_done()
            self.commands_to_send.put_nowait(command_string)  # resend after reconnect
            self.connected = False
            _schedule_reconnect(self)
            return
        self.commands_to_send.task_done()


RECONNECT_DELAYS = (5, 10, 30, 60, 120, 300)


def _schedule_reconnect(router):
    if getattr(router, "_reconnecting", False):
        return
    router._reconnecting = True
    asyncio.create_task(_reconnect_loop(router))


async def _reconnect_loop(router):
    attempt = 0
    try:
        while True:
            delay = RECONNECT_DELAYS[min(attempt, len(RECONNECT_DELAYS) - 1)]
            await asyncio.sleep(delay)
            attempt += 1
            try:
                for task in (
                    router._stream_reader_task,
                    router._stream_writer_task,
                    router._keep_alive_task,
                ):
                    if task is not None and task is not asyncio.current_task():
                        task.cancel()
                try:
                    router._writer.close()
                except Exception:  # noqa: BLE001
                    pass
                router.connected = False
                await asyncio.wait_for(_orig_connect(router), 30)
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning(
                    "Reconnecting to Helvar router %s failed (attempt %s): %r",
                    router.host, attempt, err,
                )
                continue
            _LOGGER.warning("Reconnected to Helvar router %s", router.host)
            try:
                await update_all_last_scenes(router)
            except Exception:  # noqa: BLE001
                pass
            return
    finally:
        router._reconnecting = False


async def _reconnect(self):
    """Used by aiohelvar's keep-alive when the router stops answering."""
    self.connected = False
    _schedule_reconnect(self)


async def _stream_reader(self, reader):
    """aiohelvar's reader, plus C:151 handling, and it no longer dies on one bad line."""
    _LOGGER.info("Connected to Helvar router %s", self.host)
    parser = _router.CommandParser()
    while True:
        try:
            line = await reader.readuntil(_router.COMMAND_TERMINATOR)
        except (asyncio.IncompleteReadError, ConnectionError) as err:
            _LOGGER.warning("Helvar router %s closed the connection: %r", self.host, err)
            self.connected = False
            _schedule_reconnect(self)
            return
        for splitline in line.split(b"$"):
            if not splitline:
                continue
            try:
                if _handle_input_reply(self, splitline):
                    continue
                if _handle_other_control(self, splitline):
                    continue
                command = parser.parse_command(splitline)
            except _router.ParserError as err:
                _LOGGER.debug("Ignoring line from router: %s (%s)", splitline, err)
                continue
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Error handling line from router: %s", splitline)
                continue
            if command.command_type == CommandType.RECALL_SCENE:
                asyncio.create_task(self.handle_scene_recall(command))
                continue
            async with self.command_received:
                self.commands_received.append(command)
                self.command_received.notify_all()


async def _send_command_task(self, command):
    if command.command_type in COMMAND_TYPES_DONT_LISTEN_FOR_RESPONSE:
        return await _orig_send_command_task(self, command)
    async with self._query_semaphore:
        return await _orig_send_command_task(self, command)


def _discover_router_ids(self):
    ids = {int(self.router_id)}
    ids.update(self.extra_router_ids)
    for group in self.groups.groups.values():
        for address in group.devices:
            try:
                if int(address.block) == int(self.cluster_id):
                    ids.add(int(address.router))
            except (AttributeError, TypeError, ValueError):
                continue
    return sorted(ids)


async def _initialize(self):
    if not self.connected:
        await self.connect()
    await get_groups(self)
    self.router_ids = self._discover_router_ids()
    _LOGGER.info("Querying devices on cluster %s routers %s", self.cluster_id, self.router_ids)
    await get_devices(self, self.router_ids)
    await get_scenes(self, self.groups)
    await update_all_last_scenes(self)
    await self.groups.force_update_groups()


# Device types seen in this installation that aiohelvar 0.9.8 does not know.
# Without these they are treated as non-loads and get no light entity.
EXTRA_DIGIDIM_TYPES = {
    (0x05, 0x50, 0x25): ("LC-E-DA", "Helvar LED driver (e.g. LC30-E-DA)", True),
    (0x00, 0x49, 0x24): ("492", "Relay unit", True),
}


def _add_device_types():
    from aiohelvar import static as _static

    for (a, b, c), (part, name, is_load) in EXTRA_DIGIDIM_TYPES.items():
        key = _static.h_2_d(a, b, c)
        if key not in _static.DIGIDIM_TYPES:
            _static.DIGIDIM_TYPES[key] = _static.DigidimType(part, name, is_load)


def apply():
    """Apply the fixes once."""
    global _PATCHED  # noqa: PLW0603
    if _PATCHED:
        return
    _add_device_types()
    _router.Router.__init__ = _router_init
    _router.Router._stream_reader = _stream_reader
    _router.Router._stream_writer = _stream_writer
    _router.Router.reconnect = _reconnect
    _router.Router.handle_scene_recall = _handle_scene_recall
    _router.Router._send_command_task = _send_command_task
    _router.Router._discover_router_ids = _discover_router_ids
    _router.Router.initialize = _initialize
    _router.get_groups = get_groups
    _router.get_devices = get_devices
    _router.get_scenes = get_scenes
    _devices.Devices.update_device = _update_device
    _devices.Device.get_level_for_scene = _get_level_for_scene
    _devices.Devices.set_device_brightness = _set_device_brightness
    _groups.Groups.handle_scene_callback = _handle_scene_callback
    _scenes.Scenes.get_scene = _get_scene
    log_filter = _ExpectedRouterErrors()
    logging.getLogger("aiohelvar.router").addFilter(log_filter)
    logging.getLogger("aiohelvar.devices").addFilter(log_filter)
    _PATCHED = True
    _LOGGER.debug("aiohelvar %s patched", getattr(aiohelvar, "__version__", "0.9.8"))
