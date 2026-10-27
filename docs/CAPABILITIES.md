# Capabilities

What each image declares in `print-capabilities`, and the self-test scenario
that verifies it ([scripts/selftest.py](../scripts/selftest.py); results in
[COMPATIBILITY.md](COMPATIBILITY.md)). A `false` is a limit of the upstream
stack's API (or of the program the adapter drives), not of the kernel.

## Raw CAN

| Feature | canutils | pythoncan | socketcanrs | scapy | Verified by |
|---------|:-:|:-:|:-:|:-:|---|
| Classical CAN, 11/29-bit, lengths 0–8 | ✓ | ✓ | ✓ | ✓ | `frames-standard`, `frames-extended` |
| `fd`: CAN FD, every length to 64 | ✓ | ✓ | ✓ | ✓ | `frames-fd` |
| `brs`: bit-rate switch flag | ✓ | ✓ | ✓ | ✓ | `frames-fd` |
| `esi`: transmit ESI | ✓ | ✓ | ✓ | ✓ | `frames-fd-esi` |
| `remote`: remote frames with DLC | ✓ | ✓ | ✓ | ✓ | `frames-remote` |
| `errorFrames`: receive with an error mask | ✓ | ✓ | ✓ | ✗ ¹ | `error-frames`, `error-frames-masked` |
| `errorFramesTx`: inject error frames (vcan) | ✓ | ✓ | ✓ | ✓ | `error-frames` |
| `filters`: `CAN_RAW_FILTER` | ✓ | ✓ | ✓ | ✓ | `filter-*` |
| `invertFilters`: `CAN_INV_FILTER` | ✓ | ✓ ² | ✓ | ✓ ² | `filter-inverted` |
| `joinFilters`: `CAN_RAW_JOIN_FILTERS` | ✓ | ✗ | ✓ | ✗ | `filter-joined` |
| `recvOwn`: `CAN_RAW_RECV_OWN_MSGS` | ✗ ³ | ✓ | ✓ | ✓ | `recv-own` |
| `disableLoopback`: `CAN_RAW_LOOPBACK` = 0 | ✗ ³ | ✓ | ✓ | ✗ | `no-loopback` |
| capture / replay (candump log) | ✓ | ✓ | – | – | `capture-*`, `replay-*` |

1. Scapy's `NativeCANSocket` has no parameter for `CAN_RAW_ERR_FILTER`.
2. python-can and Scapy pack `can_id`/`can_mask` into `struct can_filter`
   as given, so the kernel's `CAN_INV_FILTER` bit in the identifier passes
   through; neither has an inversion parameter of its own.
3. candump has no option for it; cansend has no option for it.

All four use the kernel's `CAN_RAW`; see [the README](../README.md#what-independent-means-here).

## ISO-TP

| Feature | canutils (kernel `CAN_ISOTP`) | pythoncanisotp (userspace) | Verified by |
|---------|:-:|:-:|---|
| Single and multi-frame, 1–4095 bytes | ✓ | ✓ | `sf-*`, `ff-8`, `mf-*` |
| First-frame escape (> 4095 bytes) | ✓ | ✓ | `ff-escape-5000` |
| Block size, STmin (ms and 100–900 µs) | ✓ | ✓ | `bs-2`, `bs-1-stmin-5ms`, `stmin-300us` |
| Padding | ✓ | ✓ | `padding` |
| `isotpExtendedAddressing` | ✓ | ✓ | `extended-addressing` |
| `isotpMixedAddressing` | ✓ ⁴ | ✓ ⁵ | `mixed-addressing` |
| `isotpExtendedIds`: 29-bit identifiers | ✓ | ✓ | `29-bit-ids` |
| `isotpFD`: CAN FD, TX_DL 64, SF escape | ✓ | ✓ | `fd-sf-escape-50`, `fd-mf-*` |
| Missing flow control detected | ✓ | ✓ | `no-flow-control` |
| Invalid sequences rejected | ✓ | ✓ | `injected-*` |

4. The kernel carries the address extension of mixed addressing in the first
   data byte, as with extended addressing (`CAN_ISOTP_EXTEND_ADDR`).
5. 11-bit identifiers only, and one address extension for both directions:
   python-can-isotp's `Mixed_29bits` uses the fixed 0x18CE/0x18CD
   identifiers of ISO 15765-2.

## DBC

| Feature | cantools | canmatrix | Verified by |
|---------|:-:|:-:|---|
| Intel/Motorola, signed, scaling, value tables, 64-bit raw | ✓ | ✓ | `decode-basic`, `decode-wide`, `encode-*` |
| `dbcMultiplexing` | ✓ | ✓ | `decode-mux`, `encode-mux` |
| `dbcExtendedMultiplexing` | ✓ | ✓ decode, ✗ encode ⁶ | `decode-extmux`, `encode-extmux` |
| `dbcFD`: messages up to 64 bytes | ✓ | ✓ | `decode-fd`, `encode-fd` |
| `dbcFloat`: `SIG_VALTYPE_` | ✓ | ✓ | `decode-float`, `encode-float` |
| `encodeRaw` | ✓ | ✓ | – |
| KCD | – | ✓ (read, convert) | `kcd-convert-basic`, `decode-kcd-basic` |

6. canmatrix 1.3.3 `Frame.encode` raises `EncodingComplexMultiplexed`.
   Known behavioural differences between the two are listed in
   [tests/known-differences.tsv](../tests/known-differences.tsv).
