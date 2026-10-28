# Third-party notices

The adapters, scripts, schemas, fixtures and documentation of this repository
are original work of OT Fabric under the MIT licence ([LICENSE](LICENSE)).
Nothing of the upstream stacks is copied into this repository: the images
fetch them at build time, pinned by version and checksum or lock file
([versions.yaml](versions.yaml)), and keep them under their own licences.
Each image carries this file and [licenses/](licenses) in
`/usr/share/doc/canbus-interop/`.

| Image | Component | Licence | Licence text | Source |
|-------|-----------|---------|--------------|--------|
| canutils | linux-can/can-utils v2025.01 (cansend, candump, canplayer, isotpsend, isotprecv) | GPL-2.0-only OR BSD-3-Clause (per file; the headers of `include/linux` are GPL-2.0-only WITH Linux-syscall-note) | [GPL-2.0-only](licenses/can-utils-GPL-2.0-only.txt), [BSD-3-Clause](licenses/can-utils-BSD-3-Clause.txt), [Linux-syscall-note](licenses/can-utils-Linux-syscall-note.txt) | The complete source of the binaries is in the image: `/usr/share/src/can-utils-v2025.01.tar.gz` (SHA-256 `88b30fea…6915`), and at https://github.com/linux-can/can-utils/tree/v2025.01 |
| pythoncan, pythoncanisotp, cantools | python-can 4.6.1 | LGPL-3.0-only | [LGPL-3.0](licenses/python-can-LGPL-3.0.txt), [GPL-3.0](licenses/python-can-GPL-3.0.txt) | Installed from PyPI as Python source; https://github.com/hardbyte/python-can/tree/v4.6.1 |
| pythoncan | pyserial 3.5 | BSD-3-Clause | [BSD-3-Clause](licenses/pyserial-BSD-3-Clause.txt) | Installed from PyPI as Python source; https://github.com/pyserial/pyserial/tree/v3.5 |
| socketcanrs | socketcan crate 4.0.0 (socketcan-rs) | MIT | [MIT](licenses/socketcan-rs-MIT.txt) | https://github.com/socketcan-rs/socketcan-rs/tree/v4.0.0 |
| socketcanrs | Crates linked into the binary (Cargo.lock: libc, nix, socket2, bitflags, embedded-can, nb, hex, log, smallvec, thiserror, memoffset, cfg-if, …) | MIT OR Apache-2.0 / MIT | Collected from each crate into `/usr/share/doc/socketcan-rs/crates/` of the image | crates.io |
| scapy | Scapy 2.8.0 | GPL-2.0-only | [GPL-2.0](licenses/scapy-GPL-2.0.txt) | Installed from PyPI as Python source; https://github.com/secdev/scapy/tree/v2.8.0 |
| pythoncanisotp | python-can-isotp 2.0.7 (`can-isotp`) | MIT | [MIT](licenses/python-can-isotp-MIT.txt) | https://github.com/pylessard/python-can-isotp/tree/v2.0.7 |
| cantools | cantools 45.1.1 and its dependencies (bitstruct, textparser, crccheck, argparse-addons: MIT) | MIT | [MIT](licenses/cantools-MIT.txt) | https://github.com/cantools/cantools/tree/45.1.1 |
| canmatrix | canmatrix 1.3.3 and its dependencies (attrs: MIT, click: BSD-3-Clause, lxml: BSD-3-Clause) | BSD-2-Clause | [BSD-2-Clause](licenses/canmatrix-BSD-2-Clause.txt) | https://github.com/ebroecker/canmatrix |
| all | Debian bookworm base system, CPython 3.12 (official `python` and `debian` images) | Debian package licences (`/usr/share/doc/*/copyright` in each image), PSF-2.0 | in the image | https://hub.docker.com/_/debian, https://hub.docker.com/_/python |

The Python adapters import their stack (python-can, Scapy, …) at run time;
they are separate MIT-licensed programs that use those libraries through
their public interfaces. The socketcanrs adapter is statically linked with
the MIT and MIT/Apache-2.0 crates above.
