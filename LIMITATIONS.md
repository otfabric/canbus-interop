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
* **Userspace ISO-TP at STmin 0.** python-can-isotp as receiver, advertising
  STmin 0 and block size 0, occasionally misses consecutive frames of long
  messages (the kernel drops them from its full socket buffer, then the
  sequence number is wrong). The 5000-byte scenarios therefore use STmin 1 ms;
  up to 4095 bytes run at STmin 0.
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
* **KCD** is covered by one fixture and canmatrix's reading of it. **ARXML**
  (contract 1.1) is covered by cantools and canmatrix on the CAN subset of
  AUTOSAR 4; canmatrix 1.3.3 reads only the selector of multiplexed PDUs,
  and both place a PDU at byte 0 of its frame where AUTOSAR gives an offset
  (known differences).
* **CAN XL** (contract 1.3) has one reference stack: can-utils. python-can,
  socketcan-rs and Scapy have no CAN XL and report the capability as
  absent. VCIDs need Linux ≥ 6.9 on the host.
* J1939, CANopen and UDS are out of scope.

## Follow-ups

Ordered by value; none is in progress (work paused 2026-10-29). The
ecosystem view is in
[go-canbus ROADMAP.md](https://github.com/otfabric/go-canbus/blob/main/ROADMAP.md).

1. **A scripted ISO-TP peer** that answers with `FC.WAIT` and `FC.OVFLW` on
   request, so implementations' handling of them is cross-checked (today
   only their own receivers exercise it).
2. **Timing assertions** for ISO-TP STmin and block size, measured from
   kernel timestamps on a monitor socket rather than inside containers.
3. **More CAN XL stacks** as they gain support (python-can, socketcan-rs,
   Scapy): the weekly upstream workflow reports new versions.
4. **More ARXML and KCD fixtures** from real projects (container and secured
   PDUs, signal groups) once implementations support them.
5. **Upstream reports** for the ARXML PDU-offset and multiplexed-PDU
   differences (cantools, canmatrix) with the fixtures here.
6. **Hardware**: a bench with real controllers is the only way past the
   single-kernel, no-physical-layer limits above.
