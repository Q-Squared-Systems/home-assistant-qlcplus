# QLC+ for Home Assistant

QLC+ is a Home Assistant custom integration for QLC+ 4.14.x. It uses QLC+'s built-in WebSocket Web API directly: no OSC bridge is required. Compatible Virtual Console widgets are set up automatically, while regular QLC+ Functions are optional.

## Compatibility and setup

This integration targets QLC+ 4.14.x and requires its Web Access/WebSocket server to be enabled (start QLC+ with `-w` / `--web`). The default endpoint is `ws://<qlc-host>:9999/qlcplusWS`; port `9999` is prefilled in the config flow. Configure the host, port, and optional SSL in **Settings → Devices & services → Add integration → QLC+**.

To install with HACS, add `https://github.com/Q-Squared-Systems/home-assistant-qlcplus` as a custom **Integration** repository, download **QLC+**, and restart Home Assistant. This repository contains exactly one integration under `custom_components/qlcplus`, as required by HACS. Releases use semantic version tags so HACS can offer normal updates.

## Virtual Console widgets

All compatible Virtual Console widgets are discovered automatically. Buttons and Audio Triggers are exposed as switches; Sliders are exposed as 0–255 number entities. Widget controls use QLC+'s direct high-rate WebSocket API, and pushed WebSocket feedback keeps their state current.

New entities use a `QLC` name prefix, resulting in Home Assistant entity IDs such as `switch.qlc_house_red`. Home Assistant preserves existing entity IDs to avoid breaking dashboards and automations.

The integration also creates a `binary_sensor` named **QLC Online**. It is on while Home Assistant has a successful coordinator update and an active QLC+ WebSocket connection.

VC **Toggle** buttons are supported as switches. QLC+ defines value `255` as a button press and `0` as a release; a Toggle button changes state on each press, so the integration checks `getWidgetStatus` before issuing a press. VC **Flash** buttons are momentary controls and are not supported as Home Assistant switches.

## Optional Functions

On setup and every shared refresh, the integration obtains QLC+'s Function list and resolves the numeric IDs internally. You use `House Red`, not `12`.

Selected Functions are switches. Turning one on/off sends QLC+'s `setFunctionStatus` command. QLC+ pushes Function state events over the same WebSocket connection; the integration uses those for immediate feedback and retains a shared 15-second refresh as reconciliation.

QLC+ does not expose a stable Function UUID. Entity identity is therefore based on server identity plus normalized Function type, name, and duplicate occurrence. Numeric-ID-only changes are transparent. Renaming a Function creates a new identity; duplicate type/name pairs are handled deterministically by occurrence and service calls by that name are rejected as ambiguous.

## Filtering

Open **Configure** on the QLC+ integration to select individual Functions, Function types, and/or a name prefix. Regular Function entities are opt-in: with no filter, none are exposed. A Function matching any selected filter is exposed. Changing filters reloads the entry.

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
