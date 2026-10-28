# Log formats (pythoncan `log-convert`)

`log-convert --input <file> --output <file>` (contract 1.1) reads and writes
CAN traces with python-can 4.6.1's own `LogReader` and `Logger`, the format
chosen by the file extension. `.jsonl` is the contract's frame documents and
is lossless both ways, so `log-convert x.blf x.jsonl` shows exactly what
python-can read, and `log-convert x.jsonl x.asc` makes python-can write a
file from known frames.

| Extension | Format | Capability |
|-----------|--------|------------|
| `.log` | candump log (can-utils `candump -L`) | (always) |
| `.asc` | Vector ASC | `logAsc` |
| `.blf` | Vector BLF (binary, zlib containers) | `logBlf` |
| `.trc` | PEAK TRC (written as version 2.1) | `logTrc` |
| `.csv` | python-can CSV | `logCsv` |
| `.jsonl` | contract frame documents | (always) |

## What survives a round trip

Measured by writing every frame of `fixtures/frames` (standard, extended,
remote, every CAN FD length with BRS, ESI, error frames, mixed) with
python-can's writer and reading the file back with its reader
(`scripts/gen-log-fixtures.sh` produces the committed evidence in
`fixtures/logs/`). A ✓ means identifier, format flags, length and data come
back unchanged.

| Frames | candump `.log` | ASC | BLF | TRC 2.1 | CSV |
|--------|----------------|-----|-----|---------|-----|
| Classical, 11-bit | ✓ | ✓ | ✓ | ✓ | ✓ |
| Classical, 29-bit | ✓ | ✓ | ✓ | ✓ | ✓ |
| Remote frames | requested DLC lost (read back as 0) | ✓ | ✓ | not written | ✓ |
| CAN FD with data, BRS | ✓ | ✓ | ✓ | not written | read back as classical |
| CAN FD with ESI | ✓ | ✓ | ✓ | not written | read back as classical |
| CAN FD with 0 data bytes | ✓ | read back as a remote FD frame (reader) | ✓ | not written | read back as classical |
| Error frames | class and data lost (read back as id 0) | class and data lost (`ErrorFrame` line) | ✓ | not written | ✓ |
| Timestamps | µs | offsets µs; the start only to the ms (Begin Triggerblock) | ✓ | ✓ | ✓ |

BLF is the only lossless format besides JSON Lines. A reader under test can
be compared with python-can's reading of the same file (the
`fixtures/logs/<format>.read.jsonl` files), losses included; a writer under
test can be checked by having python-can read its output
(`log-convert out.asc out.jsonl`).

Notes:

* `frames` in the result counts frames handed to the writer. The TRC writer
  of python-can 4.6.1 skips remote and CAN FD frames with a warning on
  stderr: the file holds fewer.
* `asc.read.jsonl` contains documents with `"fd":true,"remote":true` (the
  0-byte FD frames as python-can's ASC reader returns them). They are not
  valid input frames; they record the reader's behaviour.
* ASC files carry the date they were written; a regenerated ASC fixture
  differs in that line only.
