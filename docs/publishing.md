# Publishing checklist (GitHub open source)

Use this once before the first public release.

## 1. Create the GitHub repository

1. On GitHub: **New repository** → name `wit_ble5` (or `wit-ble5`)
2. **Public**, do **not** initialize with README (this repo already has one)
3. No need for a separate license file on GitHub create (LICENSE is already in-tree)

## 2. Replace `OWNER` placeholders

Search/replace `OWNER` with your GitHub username or org in:

- `README.md` (badges / clone URL)
- `pyproject.toml` → `[project.urls]`
- `CHANGELOG.md` compare/release links

```bash
# example
rg -n 'OWNER' -g '!docs/publishing.md'
```

## 3. Push `main`

```bash
cd /path/to/wit_ble5
git branch -M main
git remote add origin git@github.com:YOUR_USER/wit_ble5.git
git push -u origin main
```

## 4. Enable repository settings

- **Settings → Actions → General**: allow Actions; allow GitHub Actions to create/approve PRs if you use Dependabot
- **Settings → Code security**: enable Dependabot alerts / Private vulnerability reporting (matches `SECURITY.md`)
- **About**: add description, topics: `witmotion`, `ble`, `imu`, `python`, `bluetooth`
- Optional: link Discussions

## 5. Verify CI

Open the Actions tab after the first push. Workflow **CI** should run on `ubuntu-latest` + `macos-latest` for Python 3.10–3.13.

Local equivalent:

```bash
pip install -e ".[dev]"
make ci
```

## 6. Cut a release

1. Update `CHANGELOG.md` (move Unreleased → version section)
2. Bump `version` in `pyproject.toml` / `wit_ble5/__init__.py` if needed
3. Commit, then tag:

```bash
git tag -a v0.1.0 -m "v0.1.0"
git push origin v0.1.0
```

Workflow **Release** builds wheels and creates a GitHub Release with assets.

## 7. Optional: PyPI

1. Create project on https://pypi.org
2. Configure [Trusted Publishing](https://docs.pypi.org/trusted-publishers/) for this GitHub repo
3. Uncomment the `publish-pypi` job in `.github/workflows/release.yml`
4. Re-tag or re-run the release workflow

## 8. Disclaimer for users

This is an **unofficial** community client for WitMotion BLE 5.0 modules. It is not affiliated with WitMotion. Protocol docs are public; binary vendor apps remain proprietary.
