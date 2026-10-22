# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- GitHub Actions CI (lint + tests on Ubuntu / macOS)
- Release workflow for tagged versions (`v*`)
- OSS docs: LICENSE, CONTRIBUTING, SECURITY, CODE_OF_CONDUCT, issue templates

## [0.1.0] - 2026-10-21

### Added

- Cross-platform BLE client for WitMotion BLE 5.0 IMU (`WT9011DCL-BT50` / `WT901BLE*`)
- CLI: `wit-ble5 scan` / `connect` / `gui`
- Realtime GUI: connect/disconnect, IMU plots, 3D + top-down trajectory, speed display
- Trajectory modes: hybrid (default), tip, translate
- Unit tests for protocol parsing and trajectory tracker

[Unreleased]: https://github.com/OWNER/wit_ble5/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/OWNER/wit_ble5/releases/tag/v0.1.0
