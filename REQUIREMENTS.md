# Requirements

What this repository must do and must not do.
[docs/CONTAINER_CONTRACT.md](docs/CONTAINER_CONTRACT.md) and
[docs/FIXTURES.md](docs/FIXTURES.md) are the specifications that follow from
it.

## Purpose

Independent, reproducible interoperability validation for CAN, ISO-TP and DBC
software: established third-party implementations, packaged as containers that
all behave the same way, so that a library can be tested against real
implementation diversity without owning any of it.

## R1 - Repository isolation

- R1.1 This repository does not import, build, link against or depend on any
  library under test, and contains no test logic or expectation specific to
  one. The one exception is `own/` with its workflow: images of OT Fabric's own
  stacks, published for others to test against (`own/go-canbus/README.md`). The
  rest of the repository does not know them, and they are not part of a release.
  CI fails when `adapters/`, `fixtures/`, `schemas/`, `scripts/`, `tests/` or the
  Makefile name one.
- R1.2 A consumer depends on published images and the documented contract
  only. It does not need a checkout of this repository to run its tests.
- R1.3 No third-party code from here is copied into a consumer, and the
  contract does not shape a consumer's public API.

## R2 - Reference implementations

- R2.1 Every adapter runs an established third-party stack, pinned by version
  and checksum or lock file (versions.yaml), and declares only what a self-test
  scenario verifies.
- R2.2 Skips and known differences never count as passes.
