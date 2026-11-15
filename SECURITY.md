# Security

## Reporting

Report vulnerabilities privately through GitHub's security advisories of
this repository ("Report a vulnerability"), not in public issues. Problems
of an upstream stack belong to that project; tell us too when it affects the
images.

## The images

* Test tools: run them only against virtual CAN or a bench bus. They send
  whatever frames they are given; the contract has no safety interlock.
  **Never point them at a vehicle, machine or plant bus.**
* They need `--network host` (CAN interfaces live in a network namespace) but
  no added capabilities: CAN raw and ISO-TP sockets are unprivileged. Do not
  run them `--privileged`.
* Base images are pinned by digest; can-utils by version and the SHA-256 of
  its tarball; socketcan-rs and the crates it links by Cargo.lock (version
  and checksum); every Python package, the transitive ones included, by
  version and the SHA-256 of its wheels (`pip install --require-hashes
  --only-binary=:all:`). `scripts/check-versions.sh` keeps
  [versions.yaml](versions.yaml) in step with them and fails on a
  requirement without a hash.
* Adapters read fixtures and input files given on the command line and
  never execute input. JSON input is parsed with the language's standard
  parser (the Rust adapter's flat-object parser rejects anything else).
