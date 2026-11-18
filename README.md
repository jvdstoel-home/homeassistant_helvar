# homeassistant helvar (fork: jvdstoel-home)

This fork adds fixes and features on top of tomplayford/homeassistant_helvar 0.2.3 and aiohelvar 0.9.8.
The aiohelvar fixes are applied at runtime from `aiohelvar_patches.py`.

Changes in 0.3.0:
- Setup waits until groups, devices and scenes are loaded, so lights are created (was 0 lights).
- Only named scenes are loaded (was ~300,000 scene objects); error replies are no longer read as scenes.
- Groups without a last scene no longer crash the select entity.
- Direct level is sent as an integer (L:0 instead of L:0.0, which the router ignored).
- Device types 0x055025 (Helvar LED driver, e.g. LC30-E-DA) and 0x004924 (492 relay) are loads.
- Scene-to-device level lookup used the next scene (off by one).
- After every scene recall (also from wall switches) the real levels of the group's lamps are read back.
- Reader/writer no longer stop silently; the integration reconnects automatically (5 s ... 5 min back-off).
- Max 8 outstanding queries; expected router answers (=23, =27) are no longer logged as errors.
- Analogue inputs of 942 units (C:151 Query Inputs) as sensors over the main TCP session.
  The input wiring is specific to one installation and lives in `helvar_inputs.py`.

Changes in 0.3.1:
- Logbook: every scene recall the router reports (`helvar_scene_recalled`) and device faults from a
  5-minute state poll (`helvar_device_state`) are fired as events and shown in the logbook.

Changes in 0.3.2:
- 490 Blinds Controller channels are covers (open = level 100, close = level 1, stop = level 0;
  this mapping is an assumption still to be confirmed on site).
- DALI devices of unknown type 0xFF (virtual status, e.g. "V: Status Weerstation") are switches.

Changes in 0.3.3:
- New action `helvar.recall_scene` (group, block, scene, optional fade_time) to recall any scene
  of a group, also scenes without a name, e.g. for dashboard buttons that mirror a button panel.

Note: the 910 router drops the integration's TCP session when a second TCP connection from the
same host is opened, and does not answer queries over UDP. Do not poll the router from another
connection on the same host.

---

# homeassistant helvar

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

Changes in 0.3.4:
- Control commands the router reports other than scene recalls (C:12-C:18: direct level,
  proportion, device scene) are logged, shown in the logbook (`helvar_control`) and make the
  integration re-read the levels of the affected lamps. Before, they were silently dropped,
  so e.g. a single on/off button that sets a direct level left Home Assistant out of date.

Changes in 0.4.0:
- Screens (490 Blinds Controller) are driven the way the button panels do it: "modify
  proportion" with P:-1 = up, P:0 = down, F:15; stop = the opposite direction while the
  490 still counts its run time. Covers use C:18 per channel, the new action
  `helvar.screens` (group, open/close/stop) uses C:17 on a blinds group.
- The position cannot be read, so covers show the last commanded direction (assumed
  state); panel presses reported by the router update it too.
- Logbook: the level reported with C:13 is no longer shown (it does not match the lamps).

