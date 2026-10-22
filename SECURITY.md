# Security Policy

## Supported versions

| Version | Supported |
| ------- | --------- |
| 0.1.x   | Yes       |

## Reporting a vulnerability

Please **do not** open a public issue for security problems.

Email the maintainer listed in `pyproject.toml` / GitHub profile, or use GitHub **Private vulnerability reporting** if enabled on the repository.

Include:

- Affected version / commit
- OS and Python version
- Reproduction steps
- Impact (e.g. unexpected BLE GATT writes, dependency CVEs)

## Scope notes

- This project talks to nearby BLE devices you choose to connect to. Treat unknown devices with care.
- Do not submit NVR / camera / cloud credentials into this repository; that belongs in other products.
- Dependency updates are welcome via Dependabot / PRs.
