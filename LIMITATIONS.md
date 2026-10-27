# Limitations

* **One kernel CAN stack.** The raw-CAN references are four independent
  userspace clients of the same Linux `CAN_RAW` code. They catch mistakes in
  frame construction, flags, filters and socket options of an implementation
  under test, not differences between CAN controllers.
* **No physical layer.** `vcan` has no bit timing, arbitration, ACK, error
  confinement or bus-off. BRS and ESI are flag bits; error frames are
  injected data. See [INTEROPERABILITY.md](INTEROPERABILITY.md#what-virtual-can-shows-and-what-needs-hardware).
  No scenario here needs or uses hardware.
* **Timing is not asserted.** STmin and block sizes are exercised (the
  transfers succeed with the flow-control values set), but the self-test
  does not measure the gaps between consecutive frames. Delays inside
  containers and Python make sub-millisecond assertions unreliable.
* **Unpaced bursts lose frames in userspace receivers.** Python and the JSON
  pipe are slower than the kernel; the kernel drops what overflows a
  receiver's socket buffer. `burst-unpaced` only asserts order and reports
  the loss; the paced `frames-burst` (250 µs between frames, about a 500
  kbit/s bus) must be lossless.
* **ISO-TP overflow and wait frames** (`FC.WAIT`, `FC.OVFLW`) cannot be
  provoked through the contract: neither isotprecv nor python-can-isotp can
  be told to answer with them. The `injected-*` scenarios cover invalid
  sequences from the receiver's side only.
* **canutils readiness** is detected from `/proc/net/can/rcvlist_*` because
  candump and isotprecv print nothing when bound; a process that binds
  without a receiver entry would not be seen as ready.
* **canutils without --fd** drops CAN FD frames from candump's output
  (candump always enables `CAN_RAW_FD_FRAMES`).
* **DBC oracles disagree** on data longer than the message, on multiplexer
  values without a branch, and canmatrix cannot encode extended multiplexing
  ([tests/known-differences.tsv](tests/known-differences.tsv)). Neither is
  normative: DBC has no public specification.
* **KCD** is covered by one fixture and canmatrix's reading of it. ARXML is
  not covered.
* **CAN XL**, J1939, CANopen and UDS are out of scope.
