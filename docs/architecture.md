# Architecture overview

Orvibo Local combines cloud discovery with local control through MixPad gateways.

## How it works

1. The configuration flow signs in to Orvibo and lets you choose a home and devices.
2. The cloud client retrieves device topology, gateway addresses, and read-only attributes.
3. The gateway manager keeps local connections to MixPad open for control and live state updates.
4. The coordinator merges cloud and LAN state and updates Home Assistant entities.

Cloud access is required for initial topology discovery, so startup is not fully offline.

## Device support

Devices are exposed as lights, switches (plugs), covers, climate, fans, and read-only sensors, according to each device type's profile. Support depends on the model and protocol, not the product name. Locks stay read-only. Devices that communicate directly over Wi-Fi, BLE, IR, or another cloud may need a different implementation.

## Design principles

- One reader handles each gateway connection and routes replies and live updates.
- State generations stop older cloud data from overwriting newer local updates.
- Shared entity behavior keeps device identity, gateway association, and availability consistent.
- Connections, tasks, and listeners are closed when the integration unloads.

## Credential storage

The config entry stores only a secret key name. The reusable password digest lives in Home Assistant's `secrets.yaml` and is resolved at startup and on entry reload. Older entries that stored credentials inline are migrated automatically.

The integration preserves unrelated secrets and comments, and updates only its own marked entries, using atomic, owner-only writes. Reauthentication rotates the managed digest without changing the key name. Under the integration's options, **Credential secret key** can point to a manually managed key instead; its value must be the protocol digest, not the original password.

This keeps credentials out of integration settings, but it does not encrypt them. Treat `secrets.yaml` and backups as sensitive. Backups made before migration may still contain inline credentials.

## Code organization

Home Assistant discovers the lifecycle, setup flow, and entity platform entry points at the integration root. Those files delegate to the implementation packages:

| Package | Responsibility |
| --- | --- |
| `runtime/` | Entry lifecycle, coordinator, and Home Assistant updates |
| `flows/` | Setup and options flows, shared account validation, and selection forms |
| `entities/` | Shared entity behavior and platform implementations |
| `devices/` | Device profiles, home snapshot, device families, registry identity, selection, and control payloads |
| `state/` | LAN admission, sensor normalization, immutable snapshots, and reconciliation |
| `auth/` | Protocol digest, secret storage, and privacy helpers |
| `cloud/` | Cloud authentication and discovery |
| `gateway/` | LAN sessions, discovery, and connection management |
| `protocol/` | Shared constants, frame codec and framing, gateway message reading, and serial allocation |

Tests mirror these packages.

### Device profiles

Every per-device-type fact lives in one read-only table in `devices/profiles.py`: platforms, hidden infrastructure, status-only locks, ThingModel payloads, light colour mode, and legacy sensor fields. Callers ask `profile_for(device_type)` instead of comparing type codes. Rules that depend on a sub-type, such as relays, on/off lights, and plugs, live beside it in `devices/capabilities.py`. Neither module imports Home Assistant, so the cloud probe can load them on its own.

Per-capability light formats (`LightWire`), fan state format, cover class, lock batteries, and property measurements are profile facts too, so command builders and entities never branch on type codes.

### Device families

Each device family adapter in `devices/families.py` reads merged state and builds that family's control payloads, so the reading and the command for a type cannot drift apart. Entities only translate between a family and Home Assistant. The command builders in `devices/control/` are the families' internals; their wire output, including field order, is pinned by JSON fixtures.

### Home snapshot

`CloudClient.fetch_home()` returns one `HomeSnapshot` (`devices/catalog.py`): devices normalized and hidden types removed, cloud state, room names, and MixPad gateway addresses. The setup flows, the coordinator, and the cloud probe all consume it. Registry identity for devices and gateways comes from `devices/identity.py`, shared by lifecycle registration and entities.

### Credentials

Credentials travel as a single validated `ProtocolDigest` value, built once from a typed password or from storage. The cloud client, gateway connections, and coordinator accept only that value. Secret storage exposes two intents: `async_store_digest` writes or rotates a digest, and `async_migrate_to_secret` moves a legacy inline digest into `secrets.yaml`.

### Errors

Each package defines its own error family in an `exceptions.py` beside the code that raises it (`auth/`, `cloud/`, `gateway/`, `protocol/`, `state/`). Every family derives from `OrviboLanError` in the root `exceptions.py`. Credential failures, whether a malformed inline digest or an unreadable secret, all surface as `CredentialError`.

### State

LAN admission validates ownership and payloads before the coordinator reconciles state. The gateway connection and LAN admission read message routing fields through the same `protocol/message.py`. The coordinator owns generations, background tasks, and notifications; it takes its cloud source and gateway manager as constructor arguments, and `load_home(...)` is the one way a snapshot enters it. The state store holds wire fields only; sensor values (battery, temperature, door state) are derived once per change when entity-facing state is rebuilt. Protocol packets and state snapshots share one recursive freezing implementation.

See the [contributing guide](../CONTRIBUTING.md) for development checks and the [README](../README.md#security) for protocol limitations.
