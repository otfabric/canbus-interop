// SPDX-License-Identifier: MIT

// Command canbus-interop is the canbus-interop-otfabric image: go-canbus
// behind the container contract (docs/CONTAINER_CONTRACT.md).
//
// It is OT Fabric's own stack, not an independent implementation: results
// against it are never independent evidence for go-canbus (README.md).
package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path"
	"path/filepath"
	"strings"
)

const (
	adapterName   = "otfabric"
	schemaVersion = "1.0"
	fixtureRoot   = "/fixtures"
)

// Set with -ldflags by the Dockerfile.
var (
	adapterVersion   = "dev"
	upstreamVersion  = "dev"
	upstreamRevision = "0000000000000000000000000000000000000000"
)

// Exit codes of the contract.
const (
	exitOK      = 0
	exitFailure = 1
	exitUsage   = 2
	exitTimeout = 3
	exitEnv     = 4
)

// allOperations in the contract's order.
var allOperations = []string{
	"send", "receive", "capture", "replay", "decode", "encode",
	"isotp-send", "isotp-receive", "convert", "log-convert",
}

// handlers are the operations go-canbus offers here. convert, log-convert
// and slcan interfaces are not exposed (README.md).
var handlers = map[string]func(args []string) error{
	"send":          opSend,
	"receive":       opReceive,
	"capture":       opCapture,
	"replay":        opReplay,
	"decode":        opDecode,
	"encode":        opEncode,
	"isotp-send":    opISOTPSend,
	"isotp-receive": opISOTPReceive,
}

// features is the capability document's feature set: what go-canbus's
// public API does. Error frames cannot be sent (socketcan.Conn.Send
// refuses them).
var features = map[string]bool{
	"fd":                      true,
	"brs":                     true,
	"esi":                     true,
	"remote":                  true,
	"errorFrames":             true,
	"errorFramesTx":           false,
	"filters":                 true,
	"invertFilters":           true,
	"joinFilters":             true,
	"recvOwn":                 true,
	"disableLoopback":         true,
	"isotpFD":                 true,
	"isotpExtendedAddressing": true,
	"isotpMixedAddressing":    true,
	"isotpExtendedIds":        true,
	"dbcMultiplexing":         true,
	"dbcExtendedMultiplexing": true,
	"dbcFD":                   true,
	"dbcFloat":                true,
	"encodeRaw":               true,
	"arxml":                   true,
	"logAsc":                  false,
	"logBlf":                  false,
	"logTrc":                  false,
	"logCsv":                  false,
	"slcan":                   false,
	"xl":                      true,
}

// adapterError ends an operation with an error document and an exit code.
type adapterError struct {
	exit    int
	code    string
	message string
}

func (e *adapterError) Error() string { return e.message }

func usageErr(format string, a ...any) error {
	return &adapterError{exitUsage, "usage", fmt.Sprintf(format, a...)}
}

func unsupportedErr(format string, a ...any) error {
	return &adapterError{exitUsage, "unsupported", fmt.Sprintf(format, a...)}
}

func timeoutErr(format string, a ...any) error {
	return &adapterError{exitTimeout, "timeout", fmt.Sprintf(format, a...)}
}

func ioErr(format string, a ...any) error {
	return &adapterError{exitFailure, "io", fmt.Sprintf(format, a...)}
}

func protocolErr(format string, a ...any) error {
	return &adapterError{exitFailure, "protocol", fmt.Sprintf(format, a...)}
}

func interfaceErr(format string, a ...any) error {
	return &adapterError{exitEnv, "interface", fmt.Sprintf(format, a...)}
}

var stdout io.Writer = os.Stdout

// emit writes one JSON document as one line on stdout. os.Stdout is not
// buffered: every line reaches the harness at once.
func emit(doc any) {
	b, err := json.Marshal(doc)
	if err != nil {
		panic(err)
	}
	_, _ = stdout.Write(append(b, '\n'))
}

type obj = map[string]any

func event(kind string, fields obj) obj {
	doc := obj{"schemaVersion": schemaVersion, "type": kind}
	for k, v := range fields {
		doc[k] = v
	}
	return doc
}

func result(operation string, fields obj) obj {
	doc := obj{"schemaVersion": schemaVersion, "type": "result", "operation": operation}
	for k, v := range fields {
		doc[k] = v
	}
	return doc
}

func main() {
	os.Exit(run(os.Args[1:]))
}

func run(args []string) int {
	if len(args) == 0 {
		args = []string{"print-capabilities"}
	}
	err := dispatch(args)
	if err == nil {
		return exitOK
	}
	var ae *adapterError
	if !errors.As(err, &ae) {
		ae = &adapterError{exitFailure, "io", err.Error()}
	}
	fmt.Fprintf(os.Stderr, "canbus-interop: %s\n", ae.message)
	emit(obj{"schemaVersion": schemaVersion, "type": "error", "code": ae.code, "message": ae.message})
	return ae.exit
}

func dispatch(args []string) error {
	cmd := args[0]
	switch cmd {
	case "print-capabilities":
		emit(capabilities())
		return nil
	case "print-version":
		emit(versionDoc())
		return nil
	case "print-fixture":
		if len(args) != 2 {
			return usageErr("print-fixture <path>")
		}
		return printFixture(args[1])
	}
	if h, ok := handlers[cmd]; ok {
		return h(args[1:])
	}
	for _, op := range allOperations {
		if op == cmd {
			return unsupportedErr("operation %s is not supported by %s", cmd, adapterName)
		}
	}
	return usageErr("unknown command %q", cmd)
}

func capabilities() obj {
	var ops []string
	for _, op := range allOperations {
		if _, ok := handlers[op]; ok {
			ops = append(ops, op)
		}
	}
	return obj{"schemaVersion": schemaVersion, "adapter": adapterName, "operations": ops, "features": features}
}

func versionDoc() obj {
	return obj{
		"schemaVersion": schemaVersion,
		"adapter":       adapterName,
		"upstream":      "go-canbus",
		"repository":    "https://github.com/otfabric/go-canbus",
		"version":       upstreamVersion,
		"revision":      upstreamRevision,
		"license":       "MIT",
		"language":      "Go",
		"isotp":         "go-canbus userspace ISO-TP (isotp.Conn) over CAN_RAW",
		"transport":     "Linux SocketCAN CAN_RAW (go-canbus socketcan)",
		// Our own library: never independent evidence for it (contract 1.4).
		"independentEngine": false,
	}
}

func printFixture(rel string) error {
	p := path.Clean(path.Join(fixtureRoot, rel))
	if !strings.HasPrefix(p, fixtureRoot+"/") {
		return usageErr("no fixture %s", rel)
	}
	b, err := os.ReadFile(filepath.FromSlash(p))
	if err != nil {
		return usageErr("no fixture %s", rel)
	}
	_, err = stdout.Write(b)
	return err
}
