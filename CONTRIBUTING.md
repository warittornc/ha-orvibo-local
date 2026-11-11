# Contributing

## Setup and checks

Use [uv](https://docs.astral.sh/uv/) for Python and dependencies. Python 3.11 is pinned in `.python-version`, and `uv.lock` records the development environment. Home Assistant loads the integration directly, so there is no Python package to build.

```sh
git clone https://github.com/warittornc/ha-orvibo-local.git
cd ha-orvibo-local
uv sync --locked
uv run --locked ruff check custom_components tests
uv run --locked mypy custom_components/orvibo_lan
uv run --locked pytest --cov=custom_components.orvibo_lan --cov-report=term-missing
```

CI runs the same three checks, plus HACS, hassfest, and actionlint validation on GitHub.

Change dependency constraints deliberately and commit the updated lockfile. The lockfile pins only the development environment; Home Assistant installs manifest requirements separately.

## Guidelines

- Keep secrets, account identifiers, session keys, real device IDs, and complete control payloads out of logs and test fixtures. Mask identifiers with `auth/privacy.py`.
- Keep one reader per gateway connection, and clean up tasks and sessions explicitly.
- Record per-device-type facts in `devices/profiles.py` rather than comparing type codes elsewhere. See the [glossary](GLOSSARY.md) for domain terms.
- Device support needs protocol evidence. Passing tests alone do not establish hardware compatibility.
- Keep the license notices in `LICENSE` intact.

## Versioning

`manifest.json` is the version source; bump it with each user-facing change. There is no build step or release archive: HACS installs `custom_components/orvibo_lan` straight from the repository.

## Local Home Assistant

With a Docker engine and Compose v2 available (for example OrbStack or Docker Desktop):

```sh
docker compose up -d --wait --wait-timeout 180
```

Open [localhost:8125](http://127.0.0.1:8125), complete onboarding, and add **Orvibo Local**. Once configured, controls operate real devices.

The container runs Home Assistant 2026.11.1. The integration code and `dev/configuration.yaml` are mounted read-only from this checkout. Accounts, settings, and history persist in a dedicated Docker volume. To change the port or timezone, copy `.env.example` to `.env`.

After editing code or configuration:

```sh
docker compose restart homeassistant
docker compose logs --tail=100 -f homeassistant
```

Home Assistant saves entity registry changes made during startup after about three minutes, or on shutdown. Allow for that before inspecting `.storage` files.

The Docker engine must be able to reach MixPad on your LAN. UDP discovery broadcasts may not cross Docker's VM networking; TCP connections use the gateway addresses provided by the cloud.

`docker compose down` stops the instance and keeps its data. `docker compose down --volumes` also deletes accounts, settings, and history.

## Cloud discovery diagnostic

Run the offline mock first:

```sh
uv run --locked python dev/probe_cloud.py --mock
```

For a live read, enter your account and password at the hidden prompts:

```sh
uv run --locked python dev/probe_cloud.py
```

The probe uses the same global endpoint as the integration (homemate.orvibo.com) and checks both device-table scopes for every home. Use `--family-index 0` to limit it to the first home.

The JSON report shows response structure, counts, and the production parser's result. Credentials, identifiers, and scalar values are omitted, and no control commands are sent. Exit codes: 0 means devices were parsed for every probed home, 2 means discovery is unresolved, and 1 means the probe could not run or authenticate.

To also test local gateway sign-in:

```sh
uv run --locked python dev/probe_cloud.py --probe-lan
```

This sends Hello and Login to the private gateway addresses from discovery and reports acceptance, rejection, or an inconclusive transport error. Connections are closed afterward. A successful cloud sign-in does not prove that MixPad accepts the same credentials locally.

## Credential secrets

Setup and migration store the protocol digest in `/config/secrets.yaml` and keep only its key name in the config entry. **Sign in again** rotates keys that the integration manages. **Credential secret key** selects an existing, manually managed key instead; the integration never overwrites a manual key with a different value. Reload the integration after editing the file.

Never share or commit `secrets.yaml`. It is plaintext and may be included in backups. It holds the digest rather than your password, but the digest is still a reusable login secret.
