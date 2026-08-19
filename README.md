# QLC+ for Home Assistant

QLC+ is a Home Assistant custom integration for QLC+ 4.14.x. It uses QLC+'s built-in WebSocket Web API directly: no OSC bridge and no Virtual Console widgets are required. Each discovered QLC+ Function (Scene, Chaser, Collection, Script, and so on) is exposed as a switch named after the Function.

## Compatibility and setup

This integration targets QLC+ 4.14.x and requires its Web Access/WebSocket server to be enabled (start QLC+ with `-w` / `--web`). The default endpoint is `ws://<qlc-host>:9999/qlcplusWS`; port `9999` is prefilled in the config flow. Configure the host, port, and optional SSL in **Settings → Devices & services → Add integration → QLC+**.

To install with HACS, add `https://github.com/Q-Squared-Systems/home-assistant-qlcplus` as a custom **Integration** repository, download **QLC+**, and restart Home Assistant. This repository contains exactly one integration under `custom_components/qlcplus`, as required by HACS.

## How Functions work

On setup and every shared refresh, the integration obtains QLC+'s Function list and resolves the numeric IDs internally. You use `House Red`, not `12`.

Each Function is a switch. Turning one on/off sends QLC+'s `setFunctionStatus` command and immediately refreshes authoritative state. QLC+ 4's Function API has no documented Function-state push notification, so a single shared 15-second coordinator poll reads the Function list and status of all Functions. This makes changes from QLC+, MIDI, OSC, scripts, and other clients visible without every entity polling independently.

QLC+ does not expose a stable Function UUID. Entity identity is therefore based on server identity plus normalized Function type, name, and duplicate occurrence. Numeric-ID-only changes are transparent. Renaming a Function creates a new identity; duplicate type/name pairs are handled deterministically by occurrence and service calls by that name are rejected as ambiguous.

## Filtering

Open **Configure** on the QLC+ integration to select individual Functions, Function types, and/or a name prefix. Leave all three filters blank to expose every Function. A Function matching any selected filter is exposed. Changing filters reloads the entry.

## Services

`qlcplus.start_function`, `qlcplus.stop_function`, and `qlcplus.set_function_state` take a Function name. If more than one QLC+ server exists, add `entry_id`. `qlcplus.refresh_functions` forces rediscovery.

```yaml
action: qlcplus.start_function
data:
  function: "House Red"
```

```yaml
automation:
  - alias: Turn dance floor red
    triggers:
      - trigger: state
        entity_id: binary_sensor.some_trigger
        to: "on"
    actions:
      - action: switch.turn_on
        target:
          entity_id: switch.qlc_house_red
```

## Limitations

The QLC+ Web API is pipe-delimited and upstream splits command fields on `|`; Function names containing `|` are not safely representable by the protocol. QLC+'s `setFunctionStatus` has no reply, so a command is verified by the immediate shared refresh. QLC+ 4 does not provide an API endpoint for its server version, so version compatibility is documented rather than programmatically asserted.

## Development

Tests mock the asynchronous WebSocket transport; a QLC+ installation is not needed for ordinary development. Run the Home Assistant test suite from a development environment with `pytest`.
