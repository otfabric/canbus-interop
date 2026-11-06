// SPDX-License-Identifier: MIT

package main

import (
	"context"
	"encoding/hex"
	"errors"
	"flag"
	"strconv"
	"strings"
	"time"

	"github.com/otfabric/go-canbus"
	"github.com/otfabric/go-canbus/isotp"
	"github.com/otfabric/go-canbus/socketcan"
)

// hexByte and hexID are flag values in hexadecimal.
type hexValue struct {
	v   uint64
	set bool
	max uint64
}

func (h *hexValue) String() string { return strconv.FormatUint(h.v, 16) }

func (h *hexValue) Set(s string) error {
	v, err := strconv.ParseUint(strings.TrimPrefix(strings.ToLower(s), "0x"), 16, 32)
	if err != nil || v > h.max {
		return usageErr("not a hex value up to 0x%X: %q", h.max, s)
	}
	h.v, h.set = v, true
	return nil
}

type isotpFlags struct {
	common
	txID, rxID   hexValue
	extendedIDs  bool
	addressing   string
	txExt, rxExt hexValue
	txDL         int
	bs           int
	stmin        hexValue
	padding      hexValue
	data         string
	size         int
}

func (t *isotpFlags) register(fs *flag.FlagSet, send bool) {
	t.common.register(fs, true)
	t.txID.max, t.rxID.max = effMask, effMask
	t.txExt.max, t.rxExt.max, t.stmin.max, t.padding.max = 0xFF, 0xFF, 0xFF, 0xFF
	fs.Var(&t.txID, "tx-id", "transmit identifier (hex)")
	fs.Var(&t.rxID, "rx-id", "receive identifier (hex)")
	fs.BoolVar(&t.extendedIDs, "extended-ids", false, "29-bit identifiers")
	fs.StringVar(&t.addressing, "addressing", "normal", "normal, extended or mixed")
	fs.Var(&t.txExt, "tx-ext", "transmitted address byte (hex)")
	fs.Var(&t.rxExt, "rx-ext", "received address byte (hex)")
	fs.IntVar(&t.txDL, "tx-dl", 8, "CAN FD link-layer data length")
	fs.IntVar(&t.bs, "bs", 0, "block size of this receiver's flow control")
	fs.Var(&t.stmin, "stmin", "STmin byte of this receiver's flow control (hex)")
	fs.Var(&t.padding, "padding", "pad byte (hex)")
	if send {
		fs.StringVar(&t.data, "data", "", "payload (hex)")
		fs.IntVar(&t.size, "size", 0, "deterministic payload of this size")
	}
}

func (t *isotpFlags) config() (isotp.Config, error) {
	if !t.txID.set || !t.rxID.set {
		return isotp.Config{}, usageErr("--tx-id and --rx-id are required")
	}
	limit := uint64(sffMask)
	if t.extendedIDs {
		limit = effMask
	}
	if t.txID.v > limit || t.rxID.v > limit {
		return isotp.Config{}, usageErr("identifier out of range")
	}
	cfg := isotp.Config{
		TxID: canbus.ID(t.txID.v), RxID: canbus.ID(t.rxID.v), ExtendedIDs: t.extendedIDs,
		BlockSize: uint8(t.bs), STmin: isotp.DecodeSTmin(byte(t.stmin.v)),
		// Up to the first frame escape's sizes (fixtures send 5000 bytes).
		MaxMessageSize: 1 << 20,
		// A kernel ISO-TP sender on vcan can miss a flow control that
		// answers faster than it processes the echo of its own frame
		// (isotp.Config.FlowControlDelay).
		FlowControlDelay: 200 * time.Microsecond,
		QueueSize:        64,
	}
	switch t.addressing {
	case "normal":
		cfg.Addressing = isotp.Normal
	case "extended":
		cfg.Addressing = isotp.Extended
	case "mixed":
		cfg.Addressing = isotp.Mixed
	default:
		return isotp.Config{}, usageErr("--addressing must be normal, extended or mixed")
	}
	if t.addressing != "normal" {
		if !t.txExt.set || !t.rxExt.set {
			return isotp.Config{}, usageErr("--addressing %s needs --tx-ext and --rx-ext", t.addressing)
		}
		cfg.TxAddress, cfg.RxAddress = byte(t.txExt.v), byte(t.rxExt.v)
	}
	switch t.txDL {
	case 8, 12, 16, 20, 24, 32, 48, 64:
	default:
		return isotp.Config{}, usageErr("--tx-dl must be 8, 12, 16, 20, 24, 32, 48 or 64")
	}
	if t.txDL > 8 && !t.fd {
		return isotp.Config{}, usageErr("--tx-dl > 8 needs --fd")
	}
	if t.bs < 0 || t.bs > 255 {
		return isotp.Config{}, usageErr("--bs is a byte")
	}
	if t.fd {
		cfg.FD, cfg.TxDL = true, t.txDL
	}
	if t.padding.set {
		b := byte(t.padding.v)
		cfg.Padding, cfg.PadByte = true, &b
	}
	if t.xl {
		return isotp.Config{}, unsupportedErr("ISO-TP over CAN XL")
	}
	return cfg, nil
}

// dial opens a userspace ISO-TP connection (go-canbus isotp.Conn) on a
// CAN_RAW socket of the interface.
func (t *isotpFlags) dial(cfg isotp.Config) (*isotp.Conn, func(), error) {
	if err := t.check(); err != nil {
		return nil, nil, err
	}
	opts := []socketcan.Option{socketcan.WithReceiveBuffer(1 << 21)}
	if t.fd {
		opts = append(opts, socketcan.WithFD())
	}
	conn, err := socketcan.Open(t.iface, opts...)
	if err != nil {
		return nil, nil, openErr(t.iface, err)
	}
	bus, err := canbus.NewBus(conn, canbus.WithStartOnSubscribe())
	if err != nil {
		conn.Close()
		return nil, nil, ioErr("bus: %v", err)
	}
	c, err := isotp.Dial(bus, cfg)
	if err != nil {
		bus.Close()
		return nil, nil, usageErr("isotp: %v", err)
	}
	return c, func() { c.Close(); bus.Close() }, nil
}

func opISOTPSend(args []string) error {
	var t isotpFlags
	fs := flagSet("isotp-send")
	t.register(fs, true)
	if err := parse(fs, args); err != nil {
		return err
	}
	var payload []byte
	switch {
	case t.data != "" && t.size != 0:
		return usageErr("--data and --size exclude each other")
	case t.data != "":
		var err error
		if payload, err = hex.DecodeString(t.data); err != nil {
			return usageErr("--data is not hex")
		}
	case t.size >= 1:
		payload = make([]byte, t.size)
		for i := range payload {
			payload[i] = byte(i % 251)
		}
	default:
		return usageErr("--data or --size (at least 1) is required")
	}
	cfg, err := t.config()
	if err != nil {
		return err
	}
	c, closeFn, err := t.dial(cfg)
	if err != nil {
		return err
	}
	defer closeFn()
	ctx, cancel := t.context()
	defer cancel()
	for i := 0; i < t.count; i++ {
		if err := c.Send(ctx, payload); err != nil {
			if errors.Is(err, context.DeadlineExceeded) {
				return timeoutErr("isotp-send: message %d: %v", i+1, err)
			}
			return protocolErr("isotp-send: message %d: %v", i+1, err)
		}
	}
	emit(result("isotp-send", obj{"sent": t.count}))
	return nil
}

func opISOTPReceive(args []string) error {
	var t isotpFlags
	fs := flagSet("isotp-receive")
	t.register(fs, false)
	if err := parse(fs, args); err != nil {
		return err
	}
	cfg, err := t.config()
	if err != nil {
		return err
	}
	c, closeFn, err := t.dial(cfg)
	if err != nil {
		return err
	}
	defer closeFn()
	emit(event("ready", nil))
	ctx, cancel := t.context()
	defer cancel()
	received := 0
	for received < t.count {
		msg, err := c.Receive(ctx)
		if err != nil {
			if ctx.Err() != nil {
				break
			}
			if errors.Is(err, canbus.ErrClosed) {
				return ioErr("isotp-receive: %v", err)
			}
			// A failed reception (wrong sequence number, timeout of a
			// consecutive frame) is no message: keep waiting.
			continue
		}
		emit(event("message", obj{"len": len(msg), "data": hex.EncodeToString(msg)}))
		received++
	}
	return finish("isotp-receive", received, t.count)
}
