// SPDX-License-Identifier: MIT

package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"strconv"
	"strings"
	"time"

	"github.com/otfabric/go-canbus"
	"github.com/otfabric/go-canbus/capture"
	"github.com/otfabric/go-canbus/socketcan"
)

// flagSet returns a flag set whose errors become usage error documents.
func flagSet(name string) *flag.FlagSet {
	fs := flag.NewFlagSet(name, flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	return fs
}

func parse(fs *flag.FlagSet, args []string) error {
	if err := fs.Parse(args); err != nil {
		return usageErr("%s: %v", fs.Name(), err)
	}
	if fs.NArg() > 0 {
		return usageErr("%s: unexpected argument %q", fs.Name(), fs.Arg(0))
	}
	return nil
}

// common holds the flags of the CAN operations.
type common struct {
	iface     string
	fd, xl    bool
	timeoutMS int
	count     int
}

func (c *common) register(fs *flag.FlagSet, count bool) {
	fs.StringVar(&c.iface, "interface", "vcan0", "CAN interface")
	fs.BoolVar(&c.fd, "fd", false, "CAN FD")
	fs.BoolVar(&c.xl, "xl", false, "CAN XL")
	fs.IntVar(&c.timeoutMS, "timeout-ms", 5000, "time limit")
	if count {
		fs.IntVar(&c.count, "count", 1, "frames or messages")
	}
}

func (c *common) check() error {
	if c.timeoutMS <= 0 {
		return usageErr("--timeout-ms must be positive")
	}
	if c.count < 0 {
		return usageErr("--count must not be negative")
	}
	return checkInterface(c.iface, c.fd, c.xl)
}

func (c *common) context() (context.Context, context.CancelFunc) {
	return context.WithTimeout(context.Background(), time.Duration(c.timeoutMS)*time.Millisecond)
}

// filterList is a repeatable --filter.
type filterList []canbus.Filter

func (l *filterList) String() string { return fmt.Sprint(*l) }

func (l *filterList) Set(s string) error {
	f, err := parseFilter(s)
	if err != nil {
		return err
	}
	*l = append(*l, f)
	return nil
}

// openErr maps an error of socketcan.Open to the contract.
func openErr(iface string, err error) error {
	if errors.Is(err, canbus.ErrInterfaceDown) || errors.Is(err, canbus.ErrUnsupported) {
		return interfaceErr("%s: %v", iface, err)
	}
	return ioErr("%s: %v", iface, err)
}

// ioFailure maps an error of a running operation to the contract.
func ioFailure(op string, err error) error {
	switch {
	case errors.Is(err, context.DeadlineExceeded):
		return timeoutErr("%s: %v", op, err)
	case errors.Is(err, canbus.ErrInterfaceDown):
		return interfaceErr("%s: %v", op, err)
	}
	return ioErr("%s: %v", op, err)
}

func opSend(args []string) error {
	var c common
	var frames string
	var gapUS int
	var recvOwn, noLoopback bool
	fs := flagSet("send")
	c.register(fs, false)
	fs.StringVar(&frames, "frames", "-", "frame documents")
	fs.IntVar(&gapUS, "gap-us", 0, "pause between frames")
	fs.BoolVar(&recvOwn, "recv-own", false, "echo own frames")
	fs.BoolVar(&noLoopback, "no-loopback", false, "disable local loopback")
	if err := parse(fs, args); err != nil {
		return err
	}
	if gapUS < 0 {
		return usageErr("--gap-us must not be negative")
	}
	if err := c.check(); err != nil {
		return err
	}
	docs, err := readFrames(frames)
	if err != nil {
		return err
	}
	for _, d := range docs {
		switch {
		case d.xl && !c.xl:
			return usageErr("CAN XL frame without --xl")
		case !d.xl && d.can.IsFD() && !c.fd:
			return usageErr("CAN FD frame without --fd")
		case !d.xl && d.can.IsError():
			return unsupportedErr("transmitting error frames (socketcan.Conn.Send refuses them)")
		}
	}
	opts := []socketcan.Option{}
	if c.fd || c.xl {
		opts = append(opts, socketcan.WithFD())
	}
	if c.xl {
		opts = append(opts, socketcan.WithXL())
	}
	if recvOwn {
		opts = append(opts, socketcan.WithRecvOwn(), socketcan.WithReceiveBuffer(1<<21))
	}
	if noLoopback {
		opts = append(opts, socketcan.WithoutLoopback())
	}
	conn, err := socketcan.Open(c.iface, opts...)
	if err != nil {
		return openErr(c.iface, err)
	}
	defer conn.Close()
	ctx, cancel := c.context()
	defer cancel()
	sent := 0
	for i := range docs {
		if docs[i].xl {
			err = conn.SendXL(ctx, &docs[i].x)
		} else {
			err = conn.Send(ctx, &docs[i].can)
		}
		if err != nil {
			if errors.Is(err, canbus.ErrInvalidFrame) {
				return usageErr("frame %d: %v", i+1, err)
			}
			return ioFailure("send", err)
		}
		sent++
		if gapUS > 0 {
			time.Sleep(time.Duration(gapUS) * time.Microsecond)
		}
	}
	if !recvOwn {
		emit(result("send", obj{"sent": sent}))
		return nil
	}
	echoed := 0
	for echoed < sent {
		var f canbus.Frame
		var x canbus.XLFrame
		isXL, err := false, error(nil)
		if c.xl {
			isXL, err = conn.ReceiveAny(ctx, &f, &x)
		} else {
			err = conn.Receive(ctx, &f)
		}
		if err != nil {
			break
		}
		switch {
		case isXL && x.Echo:
			emit(event("frame", obj{"frame": xlFrameDoc(&x, c.iface)}))
		case !isXL && f.Echo:
			emit(event("frame", obj{"frame": frameDoc(&f, c.iface)}))
		default:
			continue
		}
		echoed++
	}
	emit(result("send", obj{"sent": sent, "echoed": echoed}))
	if echoed < sent {
		return timeoutErr("%d of %d own frames echoed", echoed, sent)
	}
	return nil
}

// receiver is the shared part of receive and capture.
type receiver struct {
	common
	filters filterList
	join    bool
	errMask string
}

func (r *receiver) register(fs *flag.FlagSet) {
	r.common.register(fs, true)
	fs.Var(&r.filters, "filter", "<id>:<mask>[:e|:s][:inv]")
	fs.BoolVar(&r.join, "join-filters", false, "all filters must match")
	fs.StringVar(&r.errMask, "error-mask", "0", "error classes to receive (hex)")
}

// run opens the socket, prints ready and hands every accepted frame to on
// until count frames arrived or the time is up.
func (r *receiver) run(op string, on func(f *canbus.Frame, x *canbus.XLFrame) error) (int, error) {
	mask, err := strconv.ParseUint(strings.TrimPrefix(strings.ToLower(r.errMask), "0x"), 16, 32)
	if err != nil {
		return 0, usageErr("--error-mask %q is not hex", r.errMask)
	}
	if err := r.check(); err != nil {
		return 0, err
	}
	opts := []socketcan.Option{socketcan.WithReceiveBuffer(1 << 21)}
	if r.fd || r.xl {
		opts = append(opts, socketcan.WithFD())
	}
	if r.xl {
		opts = append(opts, socketcan.WithXL())
	}
	if len(r.filters) > 0 || r.join || mask != 0 {
		opts = append(opts, socketcan.WithFilters(canbus.FilterSet{Filters: r.filters, Join: r.join, ErrorMask: canbus.ErrorClass(mask)}))
	}
	conn, err := socketcan.Open(r.iface, opts...)
	if err != nil {
		return 0, openErr(r.iface, err)
	}
	defer conn.Close()
	emit(event("ready", nil))
	ctx, cancel := r.context()
	defer cancel()
	n := 0
	for n < r.count {
		var f canbus.Frame
		var x canbus.XLFrame
		isXL := false
		var err error
		if r.xl {
			isXL, err = conn.ReceiveAny(ctx, &f, &x)
		} else {
			err = conn.Receive(ctx, &f)
		}
		if err != nil {
			if errors.Is(err, context.DeadlineExceeded) || ctx.Err() != nil {
				break
			}
			return n, ioFailure(op, err)
		}
		if isXL {
			if err := on(nil, &x); err != nil {
				return n, err
			}
		} else {
			// A socket opened for CAN XL also carries CAN FD frames.
			if f.IsFD() && !r.fd {
				continue
			}
			if err := on(&f, nil); err != nil {
				return n, err
			}
		}
		n++
	}
	return n, nil
}

func finish(op string, received, count int) error {
	complete := received >= count
	emit(result(op, obj{"received": received, "complete": complete}))
	if !complete {
		return timeoutErr("received %d of %d", received, count)
	}
	return nil
}

func opReceive(args []string) error {
	var r receiver
	fs := flagSet("receive")
	r.register(fs)
	if err := parse(fs, args); err != nil {
		return err
	}
	n, err := r.run("receive", func(f *canbus.Frame, x *canbus.XLFrame) error {
		if x != nil {
			emit(event("frame", obj{"frame": xlFrameDoc(x, r.iface)}))
		} else {
			emit(event("frame", obj{"frame": frameDoc(f, r.iface)}))
		}
		return nil
	})
	if err != nil {
		return err
	}
	return finish("receive", n, r.count)
}

func opCapture(args []string) error {
	var r receiver
	var output string
	fs := flagSet("capture")
	r.register(fs)
	fs.StringVar(&output, "output", "", "candump log file")
	if err := parse(fs, args); err != nil {
		return err
	}
	if output == "" {
		return usageErr("capture: --output is required")
	}
	out, err := os.Create(output)
	if err != nil {
		return ioErr("%v", err)
	}
	defer out.Close()
	w := capture.NewCandumpWriter(out, r.iface)
	n, err := r.run("capture", func(f *canbus.Frame, x *canbus.XLFrame) error {
		if x != nil {
			return w.WriteXL(x)
		}
		return w.Write(f)
	})
	if cerr := w.Close(); err == nil && cerr != nil {
		err = ioErr("capture: %v", cerr)
	}
	if err != nil {
		return err
	}
	return finish("capture", n, r.count)
}

func opReplay(args []string) error {
	var c common
	var input string
	fs := flagSet("replay")
	c.register(fs, false)
	fs.StringVar(&input, "input", "", "candump log file")
	if err := parse(fs, args); err != nil {
		return err
	}
	if input == "" {
		return usageErr("replay: --input is required")
	}
	if c.xl {
		return unsupportedErr("replay of CAN XL logs")
	}
	if err := c.check(); err != nil {
		return err
	}
	in, err := os.Open(input)
	if err != nil {
		return usageErr("%v", err)
	}
	defer in.Close()
	rd := capture.NewCandumpReader(in)
	var frames []canbus.Frame
	for {
		var f canbus.Frame
		var x canbus.XLFrame
		isXL, err := rd.ReadAny(&f, &x)
		if errors.Is(err, io.EOF) {
			break
		}
		if err != nil {
			return usageErr("%s: %v", input, err)
		}
		if isXL {
			return unsupportedErr("replay of a log with CAN XL frames")
		}
		if f.IsError() {
			continue
		}
		if f.IsFD() && !c.fd {
			return usageErr("the log has CAN FD frames: use --fd")
		}
		frames = append(frames, f)
	}
	opts := []socketcan.Option{}
	if c.fd {
		opts = append(opts, socketcan.WithFD())
	}
	conn, err := socketcan.Open(c.iface, opts...)
	if err != nil {
		return openErr(c.iface, err)
	}
	defer conn.Close()
	ctx, cancel := c.context()
	defer cancel()
	sent := 0
	for i := range frames {
		if err := conn.Send(ctx, &frames[i]); err != nil {
			return ioFailure("replay", err)
		}
		sent++
	}
	emit(result("replay", obj{"sent": sent}))
	return nil
}
