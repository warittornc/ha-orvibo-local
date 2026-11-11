# Attributions

## Upstream

ha-orvibo-local is derived from [mozzie1121/orvibo-lan-control](https://github.com/mozzie1121/orvibo-lan-control) at commit [`76fa449`](https://github.com/mozzie1121/orvibo-lan-control/tree/76fa44904b7315deddc918ba5f5dfc218d48682f), which is released under the MIT License. The gateway protocol, discovery, cloud client, and state handling build directly on that code. This repository has since reorganized, rewritten, and extended it; its history records those changes.

Upstream's hardware claims have not been re-verified for this project.

## Acknowledged references

Upstream credits these projects. No material from them was imported directly, and no endorsement by their authors is implied.

- [maycode0-0/orvibo-lan](https://github.com/maycode0-0/orvibo-lan): engineering rewrite and architecture.
- [yinjimmy/orvibohomebridge](https://github.com/yinjimmy/orvibohomebridge): online-control implementation reference.
- [mozzie1121/orvibohomebridge](https://github.com/mozzie1121/orvibohomebridge/blob/main/custom_components/orvibohomebridge/https_client.py): consulted to confirm the separate account and device table reads.

## License

This project is licensed under the [MIT License](../LICENSE). As MIT requires, the upstream copyright notice (`Copyright (c) 2025 Hermes / Nous Research`, preserved as found) is kept in `LICENSE` alongside this project's notice.
