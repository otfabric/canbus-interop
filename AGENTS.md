# AGENTS.md — canbus-interop

## What this is

Independent CAN, ISO-TP and DBC reference implementations (can-utils, python-can, can-isotp, cantools, canmatrix, scapy, socketcan-rs) in containers behind one command-line contract, used as oracles by go-canbus and canbusctl. Nothing here depends on go-canbus. Profile: **interoperability**.

## Organisation standards

This repository follows **otfabric/engineering policy 1.0**, profile **interoperability** (`.otfabric/policy.yaml`, mode `baseline`). Where this file and the organisation standards disagree, this file wins here — say so in your report.

## Where the truth lives

| Question | Source |
|---|---|
| Container commands, documents, exit codes | docs/CONTAINER_CONTRACT.md (`contract_version` in versions.yaml) |
| What each stack can do | docs/CAPABILITIES.md |
| Pins (upstream revision, source hash, base image digests) | versions.yaml, checked by `make validate` |
| Fixtures | fixtures/, docs/FIXTURES.md |
| Expected deviations of the stacks | tests/known-differences.tsv |
| Results | docs/COMPATIBILITY.md |

## Hard rules

1. Nothing floats: upstream sources and base images stay pinned, and versions.yaml mirrors the pins. `make validate` must pass.
2. Skips and known differences are never counted as passes.
3. An adapter answers an unsupported operation with the contract's unsupported error, never with a fake success.
4. Contract changes bump `contract_version` and reach every adapter and docs/CONTAINER_CONTRACT.md in the same change.
5. Licences: every redistributed component in THIRD_PARTY_NOTICES.md and `licenses/`; images that may not be redistributed are not published (`published:` in versions.yaml).
6. The release tag equals `interop_version`; bump versions.yaml before tagging.

## Commands

| When you change… | Run |
|---|---|
| anything | `make validate lint` |
| an adapter | `make image-<adapter> smoke` |
| behaviour on CAN | `make vcan selftest` |
| documents or the contract | `make documents` |
| a release | `make release-notes VERSION=vX.Y.Z` |

## Git and releases

Branches and PRs. Do not push to `main`, push tags or publish images unless the maintainer asks in the session.
