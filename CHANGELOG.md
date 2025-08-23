# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).


## [v0.2.0] - 2025-08-23

### Added
- Internal event hooks with `Monalisten.on_internal`

### Changed
- `MonalistenError` can now be imported directly from `monalisten`

### Removed
- `log_auth_warnings` parameter


## [v0.1.1] - 2025-08-20

### Fixed
- Import times have been significantly improved (e.g. importing `PushEvent` can
  be around 20–30x faster (measured on Apple M2: 5.36s → 196ms))
- Non-casefolded headers are no longer ignored
- Empty payloads containing whitespace are no longer considered non-empty


## [v0.1.0] - 2025-08-14

Initial release 🎉


[v0.1.0]: https://github.com/trag1c/monalisten/releases/tag/v0.1.0
[v0.1.1]: https://github.com/trag1c/monalisten/compare/v0.1.0...v0.1.1
[v0.2.0]: https://github.com/trag1c/monalisten/compare/v0.1.1...v0.2.0
