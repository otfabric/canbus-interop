# Container contract

Version: **1.2** (`contract_version` in [versions.yaml](../versions.yaml))

Every adapter image exposes the same commands, flags, JSON documents and exit
codes. Consumers (go-canbus's `interop/` suite, this repository's self-test)
depend on this document and on [`schemas/`](../schemas), never on an adapter's
source. A breaking change bumps the major version, an addition the minor one.
Every JSON document carries `"schemaVersion": "1.0"`: it names the
compatible line and changes only with the major version.

| Version | Change |
|---------|--------|
| 1.0 | First release (canbus-interop v0.1.0) |
| 1.1 | [`log-convert`](#log-convert-pythoncan) (pythoncan): Vector ASC, Vector BLF, PEAK TRC, CSV and candump logs through python-can's readers and writers, `.jsonl` frame documents; capabilities `logAsc`, `logBlf`, `logTrc`, `logCsv`; result field `frames`. [ARXML](#arxml) databases for `decode`, `encode` (cantools, canmatrix) and `convert` (canmatrix); capability `arxml`. Fixtures `fixtures/logs/` and `fixtures/arxml/`. Additions only (canbus-interop v0.2.0) |
| 1.2 | [slcan interfaces](#slcan-interfaces-pythoncan): `send` and `receive` with `--interface slcan:<pyserial URL>` (pythoncan, python-can's slcan interface over pyserial 3.5); capability `slcan`. Additions only (canbus-interop v0.3.0) |

## Image layout

| Item | Value |
|------|-------|
| Image | `ghcr.io/otfabric/canbus-interop-<adapter>` |
| Entrypoint | `canbus-interop` |
| Default command | `print-capabilities` |
| Network | `--network host`: CAN interfaces are network devices of a network namespace, and ordinary Docker networks do not carry CAN. The harness creates `vcan` interfaces in the host namespace and runs every container in it. CAN raw and ISO-TP sockets need no capability. |
| Fixtures | `/fixtures` (a copy of [`fixtures/`](../fixtures)) |

## Commands

| Command | Purpose |
|---------|---------|
| `print-capabilities` | Capability document: operations and features |
| `print-version` | Version document: upstream, version, revision, licence |
| `print-fixture <path>` | Print a bundled fixture (relative to `/fixtures`) to stdout |
| `send` | Transmit frames read as JSON Lines from `--frames <file>` or stdin |
| `receive` | Receive frames, print them as events |
| `capture` | Receive frames into a candump log file (`--output`) |
| `replay` | Transmit a candump log file (`--input`) |
| `decode` | Decode frames with a database (`--db`) |
| `encode` | Encode messages with a database (`--db`) |
| `convert` | Convert a database between formats (`--input`, `--output`) |
| `log-convert` | Convert a CAN trace between log formats (`--input`, `--output`; 1.1) |
| `isotp-send` | Send ISO-TP messages |
| `isotp-receive` | Receive ISO-TP messages |

An operation that is not listed in `operations` of `print-capabilities`, or a
flag that needs a feature the image declares `false`, ends with exit code 2
and an error document with code `unsupported`.

### Common flags

| Flag | Meaning |
|------|---------|
| `--interface <name>` | CAN interface (default `vcan0`); (1.2) `slcan:<pyserial URL>` for a serial-line CAN peer, see [slcan interfaces](#slcan-interfaces-pythoncan) |
| `--fd` | Open the socket in CAN FD mode (required to send or receive FD frames) |
| `--timeout-ms <n>` | Overall time limit of the operation (default 5000) |
| `--count <n>` | Stop after n frames/messages (receive, isotp-receive; default 1) |

### `send`

`--frames <file|->` JSON Lines, one [frame document](#frame-document) per line
(lines starting with `#` are comments). `--gap-us <n>` pause between frames
(default 0). Prints `{"type":"result","operation":"send","sent":<n>}`.

`--no-loopback` disables local loopback on the sending socket
(`CAN_RAW_LOOPBACK` = 0): other sockets of the host do not see the frames;
on `vcan` nothing receives them. Needs feature `disableLoopback`.

`--recv-own` enables `CAN_RAW_RECV_OWN_MSGS` on the sending socket and reads
back its own transmissions: one `frame` event per echoed frame, and
`"echoed":<n>` in the result (exit 3 when fewer than sent arrive within
`--timeout-ms`). Needs feature `recvOwn`.

### `receive`

Flags: `--count`, `--timeout-ms`, `--fd`, `--filter <id>:<mask>[:e|:s][:inv]`
(repeatable; identifier and mask in hex; `e`/`s` restrict to
extended/standard identifiers, `inv` inverts; semantics of Linux
`CAN_RAW_FILTER`: a frame passes when any filter matches),
`--join-filters` (all filters must match, `CAN_RAW_JOIN_FILTERS`),
`--error-mask <hex>` (receive error frames of these classes,
`CAN_RAW_ERR_FILTER`).

Without `--fd`, the receiver gets no CAN FD frames, as a socket without
`CAN_RAW_FD_FRAMES`. (candump always enables FD frames: the canutils
adapter drops FD frames from its output when `--fd` is not given.)

Output, one JSON document per line (event stream):

1. `{"type":"ready"}` once the socket is bound and filters are set. The
   harness transmits only after this line.
2. `{"type":"frame","frame":{...}}` for every received frame.
3. `{"type":"result","operation":"receive","received":<n>,"complete":<bool>}`;
   `complete` is false when the timeout ended the operation first (exit 3).

### `capture` / `replay`

`capture --output <file> --count <n> --timeout-ms <n>`: same events as
`receive` (frames not printed), the file in candump `-L` log format.
`replay --input <file> [--fd]`: transmit every frame of the log, as fast as
possible (`canplayer -t` semantics); result `{"type":"result",
"operation":"replay","sent":<n>}`.

### `decode` / `encode`

`decode --db <file> --frames <file|->` → one line per input frame:
`{"type":"decoded","id":<n>,"extended":<b>,"message":"<name>","signals":{"<sig>":{"raw":"<decimal integer>","physical":<number>,"label":"<value-table text, if any>"}}}`
or `{"type":"decode-error","id":<n>,"extended":<b>,"error":"<text>"}`.
Raw values are decimal strings so 64-bit values are exact; floating-point
signals report `raw` as the integer bit pattern. A physical value that is not
finite is the string `"nan"`, `"inf"` or `"-inf"`. Only the signals the
stack considers active (multiplexing) are listed.

`encode --db <file> --messages <file|->`, input lines
`{"message":"<name>","signals":{"<sig>":<physical number>}}` (with `--raw`:
raw integer strings) → `{"type":"encoded","message":"<name>","id":<n>,"extended":<b>,"data":"<hex>"}`
or `{"type":"encode-error","message":"<name>","error":"<text>"}`.
Every signal of the message (for multiplexed messages: every signal active
for the given multiplexer value) is given; unused bits are 0. Physical values
are converted to raw values by the stack itself (its rounding).

### `convert` (canmatrix)

`convert --input <file> --output <file>`: convert a database between the
formats the stack supports, chosen by file extension (e.g. `.kcd` to
`.dbc`). Result `{"type":"result","operation":"convert","input":"...","output":"...","messages":<n>}`.
Files are exchanged through a mounted directory (the self-test mounts `/work`).

### ARXML

(1.1) With feature `arxml`, `decode` and `encode` take an AUTOSAR 4 ARXML
system description as `--db` (`*.arxml`), and canmatrix `convert` reads it
(`.arxml` to `.dbc`). What both oracles read consistently, and where they
fall short (a PDU not at bit 0 of its frame), is in
[FIXTURES.md](FIXTURES.md#arxml-fixturesarxml).

### `log-convert` (pythoncan)

(1.1) `log-convert --input <file> --output <file>` reads a CAN trace with
python-can's `LogReader` and writes it with its `Logger`, each format
chosen by extension: `.log` (candump), `.asc` (Vector ASC, feature
`logAsc`), `.blf` (Vector BLF, `logBlf`), `.trc` (PEAK TRC, written as
version 2.1, `logTrc`), `.csv` (`logCsv`) and `.jsonl` (frame documents,
lossless both ways). Result
`{"type":"result","operation":"log-convert","input":"...","output":"...","frames":<n>}`
(`frames`: frames handed to the writer). Files go through a mounted
directory. What each format keeps is measured in
[LOG_FORMATS.md](LOG_FORMATS.md): only BLF and `.jsonl` are lossless.

### slcan interfaces (pythoncan)

(1.2) With feature `slcan`, `send` and `receive` take `--interface
slcan:<url>`: python-can's slcan interface (LAWICEL ASCII, the protocol of
serial CAN adapters such as the CANable) over a
[pyserial URL](https://pyserial.readthedocs.io/en/latest/url_handlers.html),
for example `slcan:socket://127.0.0.1:20000` (a TCP server on the host;
containers run with `--network host`) or `slcan:/dev/ttyACM0` (a device the
container is given). No CAN interface is checked. On opening, python-can
sends `C`, `S6` (500 kbit/s), an empty record and `O`; on closing `C`. CAN FD
frames go as `d`/`D`/`b`/`B` records. slcan carries no error state
indicator, error frames, echoes or filters: `send` of frames with `esi` or
`error`, and `--recv-own`, `--no-loopback`, `--filter` and `--error-mask`
end with exit code 2 (`unsupported`). Other operations on an slcan interface
are `unsupported` too.

### `isotp-send` / `isotp-receive`

| Flag | Meaning |
|------|---------|
| `--tx-id <hex>` / `--rx-id <hex>` | CAN identifiers (hex); `--extended-ids` for 29-bit |
| `--addressing normal\|extended\|mixed` | with `--tx-ext <hex>` / `--rx-ext <hex>` (target address / address extension) |
| `--fd --tx-dl <8..64>` | CAN FD frames with that link-layer data length |
| `--bs <n>` / `--stmin <n>` | flow-control block size and STmin byte the **receiver** sends |
| `--padding <hex>` | pad frames to full length with this byte |
| `--data <hex>` | (send) the payload; or `--size <n>` for a deterministic payload `byte(i % 251)` |
| `--count <n>` | messages to send or receive (default 1) |

`isotp-receive` prints `{"type":"ready"}`, then `{"type":"message","len":<n>,"data":"<hex>"}`
per message, then a result. `isotp-send` prints
`{"type":"result","operation":"isotp-send","sent":<n>}`; it ends when the
whole message was transmitted (the kernel's `CAN_ISOTP_WAIT_TX_DONE`,
python-can-isotp's blocking send), and fails with exit 1 (`protocol`) when the
peer sends no flow control in time or an overflow, or exit 3 on
`--timeout-ms`.

A reception that fails (wrong sequence number, consecutive-frame timeout) is
not reported as a message: the receiver keeps waiting. An adapter may reject
a combination its stack cannot express with `unsupported` (python-can-isotp:
mixed addressing with 29-bit identifiers, or different `--tx-ext` and
`--rx-ext` with mixed addressing).

`ready` of the canutils adapter is printed once the kernel lists the new
receiver of isotprecv or candump in `/proc/net/can/rcvlist_*`: the programs
print nothing when they are bound.

## Frame document

```json
{"id": 291, "extended": false, "fd": false, "brs": false, "esi": false,
 "remote": false, "error": false, "len": 3, "data": "a1b2c3",
 "timestamp": "1700000000.123456", "interface": "vcan0"}
```

`id` without flag bits; `len` the payload length (for remote frames the
requested DLC); `data` lower-case hex of exactly `len` bytes (empty for
remote frames); `timestamp` and `interface` are optional in input.

## Capability document

```json
{"schemaVersion":"1.0","adapter":"canutils","operations":["send","receive",...],
 "features":{"fd":true,"brs":true,"esi":true,"remote":true,"errorFrames":true,"errorFramesTx":true,
   "filters":true,"invertFilters":true,"joinFilters":true,"recvOwn":true,
   "isotpFD":true,"isotpExtendedAddressing":true,"isotpMixedAddressing":true,
   "isotpExtendedIds":true,"dbcMultiplexing":true,"dbcExtendedMultiplexing":true,
   "dbcFD":true,"dbcFloat":true,"encodeRaw":true}}
```

| Feature | Meaning |
|---------|---------|
| `fd`, `brs`, `remote` | send and receive CAN FD frames / with bit-rate switch / remote frames |
| `esi` | transmit a frame with the ESI flag (every receiver reports it) |
| `errorFrames` | `--error-mask` (receive error frames) |
| `errorFramesTx` | `send` of frame documents with `"error":true` (raw `CAN_ERR_FLAG` frames; only `vcan` lets userspace inject them) |
| `filters`, `invertFilters`, `joinFilters` | `--filter`, `:inv`, `--join-filters` |
| `recvOwn`, `disableLoopback` | `send --recv-own`, `send --no-loopback` |
| `isotpFD`, `isotpExtendedAddressing`, `isotpMixedAddressing`, `isotpExtendedIds` | ISO-TP over CAN FD, address modes, 29-bit identifiers |
| `dbcMultiplexing`, `dbcExtendedMultiplexing`, `dbcFD`, `dbcFloat` | DBC constructs the stack decodes |
| `encodeRaw` | `encode --raw` |
| `arxml` | (1.1) `decode`/`encode`/`convert` accept AUTOSAR 4 ARXML |
| `logAsc`, `logBlf`, `logTrc`, `logCsv` | (1.1) `log-convert` reads and writes the format |
| `slcan` | (1.2) `send`/`receive` accept `--interface slcan:<pyserial URL>` |

Every document is described by a JSON Schema in [`schemas/`](../schemas):
`capabilities`, `version`, `frame`, `event` (every line of an operation's
output), `result`, `error`, `decoded`, `encoded`, `encode-input`.

`esi`: the image can *transmit* a frame with the ESI flag set (receivers
always report it).

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | The operation failed (I/O error, protocol error, decode failure of the stack) |
| 2 | Usage error or unsupported operation/feature |
| 3 | Timeout before the operation completed |
| 4 | Environment: interface missing or down |

On failure the last stdout line is an error document
`{"type":"error","code":"usage|unsupported|timeout|io|protocol|interface","message":"..."}`.
Diagnostics go to stderr only.
