# Contributing

## Adding an adapter

1. `adapters/<name>/Dockerfile` (build context: the repository root) and the
   adapter program. Python adapters reuse `adapters/common/cbi.py` (command
   line, documents, exit codes); others implement
   [docs/CONTAINER_CONTRACT.md](docs/CONTAINER_CONTRACT.md) themselves.
2. Pin everything: base image by digest, upstream by version and revision
   (and checksum or lock file); add the entry to [versions.yaml](versions.yaml)
   and make `scripts/check-versions.sh` check it.
3. Declare only capabilities a self-test scenario verifies; add the scenario
   when there is none.
4. Add the upstream licence to [licenses/](licenses) and
   [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md); ship source where the
   licence requires it.
5. Add it to `ADAPTERS` in the Makefile and `ALL_ADAPTERS` in
   `scripts/selftest.py`; `make ci` on Linux.

## Changing the contract

Additions bump the minor `contract_version`, breaking changes the major one
(and `schemaVersion` of the documents). Update the schemas, the contract
document and its version table, and every adapter.

## Conventions

MIT for original files with an `SPDX-License-Identifier: MIT` header;
commits small and reviewable; `make validate lint` before pushing.
