# Glossary

Domain terms used in code, docs, and reviews. Keep names here in sync with the code.

**Protocol digest**: the uppercase 32-character MD5 of the account password that Orvibo's cloud and MixPad gateways accept as the login credential. It is a reusable secret, not a safe verifier. In code: `auth.credentials.ProtocolDigest`, built with `ProtocolDigest.from_password(...)` (typed password) or `ProtocolDigest(...)` (stored digest). _Avoid_: password hash, prehashed password.

**Credential secret**: the secrets.yaml entry holding a protocol digest. The config entry stores only its key name (`password_hash_secret`). It is either *managed* (written by the integration inside `# BEGIN/END orvibo_lan` markers) or *manual* (maintained by the user and never rewritten).

**Inline credential**: a protocol digest or plaintext password stored directly in config-entry data by versions before 5. It exists only so migration can move it into a credential secret.

**Error family**: the exception tree a package owns, defined in that package's `exceptions.py` and rooted in `OrviboLanError`.

**Device profile**: everything the integration knows about one Orvibo device type code, defined as one row in `devices/profiles.DEVICE_PROFILES`. Unknown types get an empty profile: no platforms, not hidden, controllable. _Avoid_: comparing raw type codes outside `devices/profiles.py`.

**ThingModel**: Orvibo's newer property-based wire format (`order: "set property"`, state under `properties`), as opposed to the legacy `value1`–`value4` fields. A profile's `thing_model` flag selects it.

**Hidden type**: a device type for MixPad gateways and other infrastructure (switch bases, IR remotes, cameras, music hosts, RF devices). It is never offered for selection, registered, or exposed as an entity.

**Home snapshot**: one home's device catalogue built once from the cloud readtable: normalized devices (hidden types removed), their cloud state, room names, and MixPad gateway addresses. In code: `devices.catalog.HomeSnapshot`, returned by `CloudClient.fetch_home()` and loaded into the coordinator with `load_home(...)`. _Avoid_: re-running normalization or room lookup outside `devices/catalog.py`.

**Device family**: the adapter that owns one family's wire format in both directions: it reads merged state ("is on", brightness, position) and builds control payloads. In code: `devices.families` (`LightFamily`, `PlugFamily`, `CoverFamily`, `FanFamily`, `ClimateFamily`). Entities translate between a family and Home Assistant and never decode `valueN` fields themselves.

**Gateway message**: one decoded frame from a MixPad. Its routing fields (command, device id, gateway uid) and whether it is a device update are read by `protocol.message`, the single reading shared by the gateway connection and LAN state admission.
