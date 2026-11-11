# Orvibo Local

Home Assistant integration for controlling Orvibo Zigbee devices through MixPad gateways on your local network.

## Features

- Local control and live state updates through MixPad.
- Lights, plugs (as switches), covers, climate, fans, and read-only sensors, depending on device capabilities.
- Account, home, and device selection through the Home Assistant UI.
- Gateway discovery, connection recovery, and cloud topology refresh.

Cloud sign-in and topology discovery are required at startup. Device support varies by model and protocol, and hardware coverage is limited.

## Installation

### Manual

1. Copy `custom_components/orvibo_lan` into your Home Assistant configuration directory:

   ```text
   config/
   └── custom_components/
       └── orvibo_lan/
           ├── __init__.py
           ├── manifest.json
           └── ...
   ```

2. Restart Home Assistant.
3. Open **Settings → Devices & services → Add integration** and search for **Orvibo Local**.
4. Sign in with your Orvibo account, then choose your home and devices.

The integration uses the `orvibo_lan` domain, so it cannot be loaded alongside another integration with the same domain. Back up your configuration before replacing one.

### HACS

Add this repository as a HACS custom repository. It uses the standard `custom_components/orvibo_lan` layout.

## Usage

Supported devices appear as Home Assistant entities. To change which devices are exposed, open the integration's options. To refresh cloud topology and state on demand, call `orvibo_lan.refresh_devices`.

MixPad must be reachable from Home Assistant on TCP port 8088. UDP discovery uses port 10000.

## Security

Run the integration on a trusted LAN, and protect Home Assistant's storage, backups, and logs:

- The gateway protocol uses a publicly known initial encryption key.
- The reusable password digest is stored in `secrets.yaml`; the config entry holds only its key name.
- Cloud sign-in may fall back to a GET request that carries the account and password digest.

See [credential storage](docs/architecture.md#credential-storage) for details.

## Documentation

- [Architecture overview](docs/architecture.md)
- [Contributing guide](CONTRIBUTING.md): development checks, a local Home Assistant instance, and diagnostics
- [Glossary](GLOSSARY.md)

Bug reports and sanitized device reports are welcome through [GitHub Issues](https://github.com/warittornc/ha-orvibo-local/issues).

## License

[MIT](LICENSE). This project is derived from [mozzie1121/orvibo-lan-control](https://github.com/mozzie1121/orvibo-lan-control); see [attributions](docs/attributions.md).
