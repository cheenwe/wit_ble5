# Contributing / 贡献指南

Thanks for your interest in **wit-ble5**. Contributions are welcome.

## Code of Conduct

Be respectful and constructive. Do not commit secrets, credentials, private BLE addresses tied to real deployments, or proprietary vendor firmware dumps.

## Development setup

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest -q
ruff check .
```

Hardware is **not** required for unit tests (`tests/`). BLE scan/connect needs a WitMotion BLE 5.0 module and system Bluetooth permission.

## Before opening a PR

- [ ] `pytest -q` passes
- [ ] `ruff check .` passes (or equivalent formatting)
- [ ] Change is focused (one concern per PR)
- [ ] New behavior has tests when practical
- [ ] Docs / README updated if user-facing

## Workflow

1. Fork and clone
2. `git checkout -b feat/my-change`
3. Commit with [Conventional Commits](https://www.conventionalcommits.org/): `feat:`, `fix:`, `docs:`, `test:`, `ci:`, `chore:`
4. Open a Pull Request against `main`
5. Wait for CI (GitHub Actions) to go green

## Branching

- `main` — always releasable
- Feature / fix branches for PRs
- Releases are tagged `vX.Y.Z` (see [CHANGELOG.md](CHANGELOG.md))

## Questions

Use GitHub Issues. Include OS, Python version, sensor model, and logs (`wit-ble5 scan` / connect errors).
