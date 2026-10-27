# Fixtures

All fixtures are original work of this repository (MIT). They are copied into
every image under `/fixtures` (`print-fixture <path>`), and
`scripts/validate-fixtures.py` checks them against [schemas/](../schemas)
and the cross-field rules of the contract.

## Frames (`fixtures/frames/*.jsonl`)

JSON Lines of [frame documents](CONTAINER_CONTRACT.md#frame-document); `#`
lines are comments.

| File | Frames | Covers |
|------|--------|--------|
| `standard.jsonl` | 27 | 11-bit identifiers 0x000, 0x123, 0x7FF, every classical length 0–8 |
| `extended.jsonl` | 36 | 29-bit identifiers 0, 0x123 (same number as a standard one), 0x12345678, 0x1FFFFFFF, lengths 0–8 |
| `remote.jsonl` | 8 | Remote frames with requested lengths 0, 1, 4, 8, 11- and 29-bit |
| `fd.jsonl` | 64 | CAN FD, every legal length (0–8, 12, 16, 20, 24, 32, 48, 64), with and without BRS, 11- and 29-bit |
| `fd-esi.jsonl` | 6 | CAN FD with ESI set |
| `mixed.jsonl` | 42 | Classical, remote and FD frames interleaved, sent with `--fd`: classical frames must stay classical |
| `error.jsonl` | 5 | Error frames (classes controller, bus-off, lost arbitration, protocol violation, error counters) |
| `burst.jsonl` | 2000 | Classical frames; bytes 0–3 a big-endian sequence number for order and loss checks |

## DBC (`fixtures/dbc/`)

Each `<name>.dbc` comes with `<name>.frames.jsonl` (frames to decode) and
`<name>.messages.jsonl` (physical values to encode).

| Database | Covers |
|----------|--------|
| `basic.dbc` | Intel signals filling 64 bits; 12-bit field across bytes; signed 8 and 13 bits; scaling with offset (0.1, −40); Motorola signals incl. 10 bits across bytes, signed with scaling, offset −100; 29-bit message; value table; comments; senders/receivers. Vectors include data too short and too long, unknown identifiers, and a value exactly halfway between two raw values in decimal arithmetic (25.15 at factor 0.1) |
| `wide.dbc` | 64-bit unsigned Intel, 64-bit signed Motorola, 32-bit pairs; values that a float64 cannot hold (2^64−1, 2^53+1, −2^63) |
| `mux.dbc` | Simple multiplexing (M / m0 / m1 / m2), Motorola signal in a branch, a signal outside multiplexing, a multiplexer value without branch |
| `extmux.dbc` | Extended multiplexing (`SG_MUL_VAL_`): a multiplexed multiplexor (`m0M`), value ranges |
| `fd.dbc` | CAN FD messages of 64 and 12 bytes (`VFrameFormat` StandardCAN_FD / ExtendedCAN_FD, `BusType`), signals in the last bytes |
| `float.dbc` | IEEE 754 single (Intel and Motorola) and double signals (`SIG_VALTYPE_`), scaled float; −0, denormals, infinities |
| `attributes.dbc` | Attribute definitions of every object type with defaults (`GenMsgCycleTime`, `GenMsgSendType`, `GenSigStartValue`, …), `VAL_TABLE_`, value tables with negative values, `BO_TX_BU_`, comments |

## KCD (`fixtures/kcd/`)

`basic.kcd`: a Kayak network definition with Intel and big-endian signals,
scaling, labels, a 29-bit message and multiplexing, with
`basic.frames.jsonl`. The self-test converts it with canmatrix and compares
cantools' decoding of the converted DBC with canmatrix's decoding of the KCD.
