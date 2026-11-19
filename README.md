# homeassistant helvar (fork: jvdstoel-home)

This fork adds fixes and features on top of tomplayford/homeassistant_helvar 0.2.3 and aiohelvar 0.9.8.
The aiohelvar fixes are applied at runtime from `aiohelvar_patches.py`.

Note: the 910 router drops the integration's TCP session when a second TCP connection from the
same host is opened, and does not answer queries over UDP. Do not poll the router from another
connection on the same host.

Some parts are specific to one installation: the weather station inputs (`helvar_inputs.py`),
the blinds scene mapping (scene 1.1 = down, 1.15 = up), Dutch logbook texts and a few names.

## Changelog (newest first)

### 0.6.3
- Light sensors: the lowest input step (raw 1, ~392 lx) is shown as 0 lx, so the sensors read
  0 at night instead of flickering between 0 and 392 lx.

### 0.6.2
- After a scene or command, the integration reads the real level of each lamp in the group.
  When the router reports a lamp on while Home Assistant expected it off (or the other way
  round), a `helvar_level_corrected` event is fired and shown in the logbook, e.g. "router meldt
  aan (100 %) na scène 1.15 in 45 Woonk+keuken uit; HA verwachtte uit".

### 0.6.1
- Screens verified on site: scene 1.1 = down, scene 1.15 = up (on a blinds group with C:11, or
  on one channel with C:12); stop = "modify proportion" in the opposite direction while moving
  (C:17 group / C:18 channel; P:-1 while going down, P:0 while going up). 0.5.0 had up and down
  the wrong way round.

### 0.6.0
- Home Assistant no longer waits for Helvar at startup. Setup only opens the connection;
  discovery of groups, devices and scene tables (1-2 minutes) runs as a background task, and the
  platforms add their entities when it has finished. Until then the Helvar entities show as
  unavailable. If discovery fails, the integration reloads after 60 s.

### 0.5.1
- Cover timer callbacks run in the event loop (fixes a thread-safety error).

### 0.5.0
- Screens up/down go through scenes, like the weather sequences. Covers use C:12 (recall scene on
  one device), `helvar.screens` uses C:11 on a blinds group. (Up/down corrected in 0.6.1.)
- Scene recalls on groups with screens (weather sequences, HA) update the cover state.

### 0.4.2
- Covers show the scene table of their channel (`scene_levels`).

### 0.4.1
- Test action `helvar.send_raw`: send one raw HelvarNet command over the main connection.

### 0.4.0
- Screens (490 Blinds Controller): new action `helvar.screens` (group, open/close/stop).
- The position cannot be read, so covers show the last commanded direction (assumed state);
  panel presses reported by the router update it too.
- Logbook: the level reported with C:13 is no longer shown (it does not match the lamps).

### 0.3.4
- Control commands the router reports other than scene recalls (C:12-C:18: direct level,
  proportion, device scene) are logged, shown in the logbook (`helvar_control`) and make the
  integration re-read the levels of the affected lamps. Before, they were silently dropped, so
  e.g. a single on/off button that sets a direct level left Home Assistant out of date.

### 0.3.3
- New action `helvar.recall_scene` (group, block, scene, optional fade_time) to recall any scene
  of a group, also scenes without a name, e.g. for dashboard buttons that mirror a button panel.

### 0.3.2
- 490 Blinds Controller channels are covers.
- DALI devices of unknown type 0xFF (virtual status, e.g. "V: Status Weerstation") are switches.

### 0.3.1
- Logbook: every scene recall the router reports (`helvar_scene_recalled`) and device faults from
  a 5-minute state poll (`helvar_device_state`) are fired as events and shown in the logbook.

### 0.3.0
- Setup waits until groups, devices and scenes are loaded, so lights are created (was 0 lights).
- Only named scenes are loaded (was ~300,000 scene objects); error replies are no longer read as
  scenes.
- Groups without a last scene no longer crash the select entity.
- Direct level is sent as an integer (L:0 instead of L:0.0, which the router ignored).
- Device types 0x055025 (Helvar LED driver, e.g. LC30-E-DA) and 0x004924 (492 relay) are loads.
- Scene-to-device level lookup used the next scene (off by one).
- After every scene recall (also from wall switches) the real levels of the group's lamps are read
  back.
- Reader/writer no longer stop silently; the integration reconnects automatically (5 s ... 5 min
  back-off).
- Max 8 outstanding queries; expected router answers (=23, =27) are no longer logged as errors.
- Analogue inputs of 942 units (C:151 Query Inputs) as sensors over the main TCP session.

---

## Original README (upstream)

This is a simple Home Assistant Integration for Helvar Lighting Systems.  Specifically the 9XX series Routers. 

All the heavy lifting is done by the [aiohelvar](https://github.com/tomplayford/aiohelvar) library.

## Features

You can control:
 - Individual lights (on DALI, DMX and SBUS)
   - Dimming, dimming over time
 - Groups
   - Setting scenes
     - Dimming between scenes, dimming over time
   - Relative and absolute adjustments to groups

The integration will receive push notifications (if you enable them on the router) about scene changes from the router. These are fed back to the entities state, so things show the current levels. Updates from individual devices are not sent by the router. 

For general use, this should cover most needs. I use it at home and it works well. 

## Installation

You'll need to install HACS first, then set this up as a custom repository.

## Usage

Enable the integration and you'll be prompted for your routers IP address and port. 

The integration will then pull all lighting devices, groups and scenes. 

- The lighting devices will be added as light entities.
- The groups will be added as select entities, and you'll be able to select from the group's available scenes.

## Limitations 

Many! But the following are probably the most significant:

  - Not tested with more than one Router (I only have one)
  - Not tested with RGB or WW/CW adjustable lights 
  - Helvar does not provide API access to input devices, so they're not available 
  - All the other limitations listed on the library README.
  - I'm sure there are bugs. 


## Help

I don't really like the Home Assistant select card scene integration - perhaps we need a custom one. Or integration with the HomeAssistant scenes setup. Not sure.

Submit to HomeAssistant. 


  ## Disclaimer

Halvar (TM) is a registered trademark of Helvar Ltd.

This software is not officially endorsed by Helvar Ltd. in any way.

The authors of this software provide no support, guarantees, or warranty for its use, features, safety, or suitability for any task. We do not recommend you use it for anything at all, and we don't accept any liability for any damages that may result from its use.

This software is licensed under the Apache License 2.0. See the LICENCE file for more details.
