// SPDX-License-Identifier: MIT
//
// canbus-interop adapter for the Rust socketcan crate (socketcan-rs).
//
// Every socket operation goes through the crate: CanSocket / CanFdSocket,
// CanFilter, set_join_filters, set_error_filter, set_loopback,
// set_recv_own_msgs, the frame types and their constructors. This program
// only implements the command line and the JSON documents of
// docs/CONTAINER_CONTRACT.md, with no other dependency.

use std::collections::BTreeMap;
use std::io::{self, BufRead, Write};
use std::process::exit;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use socketcan::id::FdFlags;

use socketcan::{
    CanAnyFrame, CanDataFrame, CanErrorFrame, CanFdFrame, CanFdSocket, CanFilter, CanFrame, CanRemoteFrame,
    CanSocket, EmbeddedFrame, ExtendedId, Frame, Id, Socket, SocketOptions, StandardId,
};

const SCHEMA: &str = "1.0";
const EFF_FLAG: u32 = 0x8000_0000;
const INV_FILTER: u32 = 0x2000_0000;
const EFF_MASK: u32 = 0x1FFF_FFFF;
const SFF_MASK: u32 = 0x7FF;
const FD_LENGTHS: [usize; 16] = [0, 1, 2, 3, 4, 5, 6, 7, 8, 12, 16, 20, 24, 32, 48, 64];

// ── errors and output ───────────────────────────────────────────────────────

struct Fail {
    exit: i32,
    code: &'static str,
    message: String,
}

fn fail(exit: i32, code: &'static str, message: impl Into<String>) -> Fail {
    Fail { exit, code, message: message.into() }
}
fn usage(m: impl Into<String>) -> Fail {
    fail(2, "usage", m)
}
fn unsupported(m: impl Into<String>) -> Fail {
    fail(2, "unsupported", m)
}
fn io_fail(m: impl Into<String>) -> Fail {
    fail(1, "io", m)
}

fn quote(s: &str) -> String {
    let mut out = String::with_capacity(s.len() + 2);
    out.push('"');
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            c if (c as u32) < 0x20 => out.push_str(&format!("\\u{:04x}", c as u32)),
            c => out.push(c),
        }
    }
    out.push('"');
    out
}

fn emit(line: &str) {
    let stdout = io::stdout();
    let mut h = stdout.lock();
    let _ = writeln!(h, "{}", line);
    let _ = h.flush();
}

fn hex(data: &[u8]) -> String {
    data.iter().map(|b| format!("{:02x}", b)).collect()
}

fn unhex(s: &str) -> Result<Vec<u8>, Fail> {
    if s.len() % 2 != 0 {
        return Err(usage(format!("data is not hex: {:?}", s)));
    }
    (0..s.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&s[i..i + 2], 16).map_err(|_| usage(format!("data is not hex: {:?}", s))))
        .collect()
}

// ── frame documents ─────────────────────────────────────────────────────────

struct Doc {
    id: u32,
    extended: bool,
    fd: bool,
    brs: bool,
    esi: bool,
    remote: bool,
    error: bool,
    len: usize,
    data: Vec<u8>,
}

impl Doc {
    fn json(&self, ts: Option<SystemTime>, iface: &str) -> String {
        let mut s = format!(
            "{{\"id\":{},\"extended\":{},\"fd\":{},\"brs\":{},\"esi\":{},\"remote\":{},\"error\":{},\"len\":{},\"data\":\"{}\"",
            self.id, self.extended, self.fd, self.brs, self.esi, self.remote, self.error, self.len, hex(&self.data)
        );
        if let Some(t) = ts {
            if let Ok(d) = t.duration_since(UNIX_EPOCH) {
                s.push_str(&format!(",\"timestamp\":\"{}.{:06}\"", d.as_secs(), d.subsec_micros()));
            }
        }
        s.push_str(&format!(",\"interface\":{}}}", quote(iface)));
        s
    }
}

// A JSON value of a flat frame document: numbers, booleans and strings.
enum Val {
    Num(f64),
    Bool(bool),
    Str(String),
    Null,
}

// Parses one flat JSON object (no nested values), as frame documents are.
fn parse_flat(line: &str) -> Result<BTreeMap<String, Val>, Fail> {
    let bad = || usage(format!("not a flat JSON object: {}", line));
    let b: Vec<char> = line.trim().chars().collect();
    let mut i = 0;
    let ws = |i: &mut usize| {
        while *i < b.len() && b[*i].is_whitespace() {
            *i += 1
        }
    };
    let string = |i: &mut usize| -> Result<String, Fail> {
        if b.get(*i) != Some(&'"') {
            return Err(bad());
        }
        *i += 1;
        let mut s = String::new();
        while *i < b.len() && b[*i] != '"' {
            if b[*i] == '\\' {
                *i += 1;
                match b.get(*i) {
                    Some('n') => s.push('\n'),
                    Some(c) => s.push(*c),
                    None => return Err(bad()),
                }
            } else {
                s.push(b[*i]);
            }
            *i += 1;
        }
        if *i >= b.len() {
            return Err(bad());
        }
        *i += 1;
        Ok(s)
    };
    let mut m = BTreeMap::new();
    ws(&mut i);
    if b.get(i) != Some(&'{') {
        return Err(bad());
    }
    i += 1;
    loop {
        ws(&mut i);
        if b.get(i) == Some(&'}') {
            break;
        }
        let k = string(&mut i)?;
        ws(&mut i);
        if b.get(i) != Some(&':') {
            return Err(bad());
        }
        i += 1;
        ws(&mut i);
        let v = match b.get(i) {
            Some('"') => Val::Str(string(&mut i)?),
            Some('t') if line.trim()[i..].starts_with("true") => {
                i += 4;
                Val::Bool(true)
            }
            Some('f') if line.trim()[i..].starts_with("false") => {
                i += 5;
                Val::Bool(false)
            }
            Some('n') if line.trim()[i..].starts_with("null") => {
                i += 4;
                Val::Null
            }
            Some(_) => {
                let st = i;
                while i < b.len() && (b[i].is_ascii_digit() || "+-.eE".contains(b[i])) {
                    i += 1
                }
                let t: String = b[st..i].iter().collect();
                Val::Num(t.parse().map_err(|_| bad())?)
            }
            None => return Err(bad()),
        };
        m.insert(k, v);
        ws(&mut i);
        match b.get(i) {
            Some(',') => i += 1,
            Some('}') => break,
            _ => return Err(bad()),
        }
    }
    Ok(m)
}

fn doc_from_json(line: &str) -> Result<Doc, Fail> {
    let m = parse_flat(line)?;
    let flag = |k: &str| matches!(m.get(k), Some(Val::Bool(true)));
    let id = match m.get("id") {
        Some(Val::Num(n)) if *n >= 0.0 && n.fract() == 0.0 => *n as u32,
        _ => return Err(usage(format!("frame document without a valid id: {}", line))),
    };
    let data = match m.get("data") {
        Some(Val::Str(s)) => unhex(s)?,
        _ => Vec::new(),
    };
    let len = match m.get("len") {
        Some(Val::Num(n)) => *n as usize,
        _ => data.len(),
    };
    let d = Doc {
        id,
        extended: flag("extended"),
        fd: flag("fd"),
        brs: flag("brs"),
        esi: flag("esi"),
        remote: flag("remote"),
        error: flag("error"),
        len,
        data,
    };
    let limit = if d.extended || d.error { EFF_MASK } else { SFF_MASK };
    if d.id > limit {
        return Err(usage(format!("identifier 0x{:X} out of range", d.id)));
    }
    if d.fd {
        if d.remote {
            return Err(usage("CAN FD frames have no remote form"));
        }
        if !FD_LENGTHS.contains(&d.len) {
            return Err(usage(format!("CAN FD length {} is not a valid FD length", d.len)));
        }
    } else {
        if d.brs || d.esi {
            return Err(usage("BRS/ESI only exist on CAN FD frames"));
        }
        if d.len > 8 {
            return Err(usage(format!("classical CAN length {} > 8", d.len)));
        }
    }
    if d.remote {
        if !d.data.is_empty() {
            return Err(usage("remote frame with data"));
        }
    } else if d.data.len() != d.len {
        return Err(usage(format!("len {} does not match {} data bytes", d.len, d.data.len())));
    }
    if d.error && (d.extended || d.fd || d.remote) {
        return Err(usage("an error frame is neither extended, FD nor remote"));
    }
    Ok(d)
}

fn can_id(d: &Doc) -> Result<Id, Fail> {
    if d.extended {
        ExtendedId::new(d.id).map(Id::Extended).ok_or_else(|| usage("bad extended id"))
    } else {
        StandardId::new(d.id as u16).map(Id::Standard).ok_or_else(|| usage("bad standard id"))
    }
}

fn from_classic(f: &CanFrame) -> Doc {
    match f {
        CanFrame::Data(f) => Doc {
            id: f.raw_id() & EFF_MASK,
            extended: f.is_extended(),
            fd: false,
            brs: false,
            esi: false,
            remote: false,
            error: false,
            len: f.data().len(),
            data: f.data().to_vec(),
        },
        CanFrame::Remote(f) => Doc {
            id: f.raw_id() & EFF_MASK,
            extended: f.is_extended(),
            fd: false,
            brs: false,
            esi: false,
            remote: true,
            error: false,
            len: f.dlc(),
            data: Vec::new(),
        },
        CanFrame::Error(f) => Doc {
            id: f.id_word() & EFF_MASK,
            extended: false,
            fd: false,
            brs: false,
            esi: false,
            remote: false,
            error: true,
            len: f.data().len(),
            data: f.data().to_vec(),
        },
    }
}

fn from_any(f: &CanAnyFrame) -> Doc {
    match f {
        CanAnyFrame::Normal(f) => from_classic(&CanFrame::Data(*f)),
        CanAnyFrame::Remote(f) => from_classic(&CanFrame::Remote(*f)),
        CanAnyFrame::Error(f) => from_classic(&CanFrame::Error(*f)),
        CanAnyFrame::Fd(f) => Doc {
            id: f.raw_id() & EFF_MASK,
            extended: f.is_extended(),
            fd: true,
            brs: f.is_brs(),
            esi: f.is_esi(),
            remote: false,
            error: false,
            len: f.data().len(),
            data: f.data().to_vec(),
        },
    }
}

// ── command line ────────────────────────────────────────────────────────────

struct Filter {
    id: u32,
    mask: u32,
    invert: bool,
}

struct Args {
    command: String,
    positional: Vec<String>,
    interface: String,
    fd: bool,
    timeout_ms: u64,
    count: usize,
    frames: String,
    gap_us: u64,
    filters: Vec<Filter>,
    join: bool,
    error_mask: u32,
    recv_own: bool,
    no_loopback: bool,
}

fn parse_filter(s: &str) -> Result<Filter, Fail> {
    let parts: Vec<&str> = s.split(':').collect();
    let bad = || usage(format!("filter {:?}: want <id>:<mask>[:e|:s][:inv]", s));
    if parts.len() < 2 {
        return Err(bad());
    }
    let mut id = u32::from_str_radix(parts[0], 16).map_err(|_| bad())?;
    let mut mask = u32::from_str_radix(parts[1], 16).map_err(|_| bad())?;
    let mut invert = false;
    for p in &parts[2..] {
        match *p {
            "e" => {
                id |= EFF_FLAG;
                mask |= EFF_FLAG
            }
            "s" => mask |= EFF_FLAG,
            "inv" => invert = true,
            _ => return Err(bad()),
        }
    }
    Ok(Filter { id, mask, invert })
}

fn parse_args() -> Result<Args, Fail> {
    let argv: Vec<String> = std::env::args().skip(1).collect();
    let mut a = Args {
        command: argv.first().cloned().unwrap_or_else(|| "print-capabilities".into()),
        positional: Vec::new(),
        interface: "vcan0".into(),
        fd: false,
        timeout_ms: 5000,
        count: 1,
        frames: "-".into(),
        gap_us: 0,
        filters: Vec::new(),
        join: false,
        error_mask: 0,
        recv_own: false,
        no_loopback: false,
    };
    let mut i = 1;
    let value = |i: &mut usize| -> Result<String, Fail> {
        *i += 1;
        argv.get(*i).cloned().ok_or_else(|| usage(format!("{} needs a value", argv[*i - 1])))
    };
    let num = |s: String| -> Result<u64, Fail> { s.parse().map_err(|_| usage(format!("not a number: {}", s))) };
    while i < argv.len() {
        match argv[i].as_str() {
            "--interface" => a.interface = value(&mut i)?,
            "--fd" => a.fd = true,
            "--timeout-ms" => a.timeout_ms = num(value(&mut i)?)?,
            "--count" => a.count = num(value(&mut i)?)? as usize,
            "--frames" => a.frames = value(&mut i)?,
            "--gap-us" => a.gap_us = num(value(&mut i)?)?,
            "--filter" => a.filters.push(parse_filter(&value(&mut i)?)?),
            "--join-filters" => a.join = true,
            "--error-mask" => {
                let v = value(&mut i)?;
                a.error_mask = u32::from_str_radix(&v, 16).map_err(|_| usage("--error-mask is hex"))?
            }
            "--recv-own" => a.recv_own = true,
            "--no-loopback" => a.no_loopback = true,
            // (contract 1.3) No CAN XL in this adapter: refused, not unknown.
            "--xl" => return Err(unsupported("CAN XL")),
            s if s.starts_with("--") => return Err(usage(format!("unknown flag {}", s))),
            s => a.positional.push(s.to_string()),
        }
        i += 1;
    }
    if a.timeout_ms == 0 {
        return Err(usage("--timeout-ms must be positive"));
    }
    Ok(a)
}

fn capabilities() -> String {
    format!(
        "{{\"schemaVersion\":\"{}\",\"adapter\":\"socketcanrs\",\"features\":{{\"fd\":true,\"brs\":true,\"esi\":true,\"remote\":true,\"errorFrames\":true,\"errorFramesTx\":true,\"filters\":true,\"invertFilters\":true,\"joinFilters\":true,\"recvOwn\":true,\"disableLoopback\":true}},\"operations\":[\"send\",\"receive\"]}}",
        SCHEMA
    )
}

fn version() -> String {
    let env = |k: &str| std::env::var(k).unwrap_or_default();
    format!(
        "{{\"schemaVersion\":\"{}\",\"adapter\":\"socketcanrs\",\"upstream\":\"socketcan-rs\",\"repository\":\"https://github.com/socketcan-rs/socketcan-rs\",\"version\":{},\"revision\":{},\"license\":\"MIT\",\"language\":\"Rust\"}}",
        SCHEMA,
        quote(&env("UPSTREAM_VERSION")),
        quote(&env("UPSTREAM_REVISION"))
    )
}

// ── sockets ─────────────────────────────────────────────────────────────────

enum Sock {
    Classic(CanSocket),
    Fd(CanFdSocket),
}

impl Sock {
    fn open(a: &Args) -> Result<Sock, Fail> {
        let r = if a.fd {
            CanFdSocket::open(&a.interface).map(Sock::Fd)
        } else {
            CanSocket::open(&a.interface).map(Sock::Classic)
        };
        r.map_err(|e| fail(4, "interface", format!("{}: {}", a.interface, e)))
    }

    fn opts(&self) -> &dyn SocketOptionsDyn {
        match self {
            Sock::Classic(s) => s,
            Sock::Fd(s) => s,
        }
    }

    fn send(&self, d: &Doc) -> Result<(), Fail> {
        if d.error {
            let f = CanErrorFrame::new_error(d.id, &d.data).map_err(|e| usage(format!("invalid error frame: {}", e)))?;
            let r = match self {
                Sock::Fd(s) => s.write_frame(&f),
                Sock::Classic(s) => s.write_frame(&f),
            };
            return r.map_err(|e| io_fail(format!("send: {}", e)));
        }
        let id = can_id(d)?;
        let r = if d.fd {
            let mut flags = FdFlags::empty();
            if d.brs {
                flags |= FdFlags::BRS;
            }
            if d.esi {
                flags |= FdFlags::ESI;
            }
            let f = CanFdFrame::with_flags(id, &d.data, flags).ok_or_else(|| usage("invalid FD frame"))?;
            match self {
                Sock::Fd(s) => s.write_frame(&f),
                Sock::Classic(_) => return Err(usage("CAN FD frame without --fd")),
            }
        } else if d.remote {
            let f = CanRemoteFrame::new_remote(id, d.len).ok_or_else(|| usage("invalid remote frame"))?;
            match self {
                Sock::Fd(s) => s.write_frame(&f),
                Sock::Classic(s) => s.write_frame(&f),
            }
        } else {
            let f = CanDataFrame::new(id, &d.data).ok_or_else(|| usage("invalid data frame"))?;
            match self {
                Sock::Fd(s) => s.write_frame(&f),
                Sock::Classic(s) => s.write_frame(&f),
            }
        };
        r.map_err(|e| io_fail(format!("send: {}", e)))
    }

    // Reads one frame; None when the timeout passed first.
    fn recv(&self, timeout: Duration) -> Result<Option<(Doc, Option<SystemTime>)>, Fail> {
        let t = if timeout.is_zero() { Duration::from_millis(1) } else { timeout };
        let r = match self {
            Sock::Classic(s) => s
                .set_read_timeout(t)
                .and_then(|_| s.read_frame_with_timestamp())
                .map(|(f, ts)| (from_classic(&f), Some(ts))),
            Sock::Fd(s) => s
                .set_read_timeout(t)
                .and_then(|_| s.read_frame_with_timestamp())
                .map(|(f, ts)| (from_any(&f), Some(ts))),
        };
        match r {
            Ok(v) => Ok(Some(v)),
            Err(e) if e.kind() == io::ErrorKind::WouldBlock || e.kind() == io::ErrorKind::TimedOut => Ok(None),
            Err(e) => Err(io_fail(format!("receive: {}", e))),
        }
    }
}

// SocketOptions is not object safe (generic set_filters); the options used
// here, as a small object-safe facade.
trait SocketOptionsDyn {
    fn filters(&self, f: &[CanFilter]) -> io::Result<()>;
    fn join(&self, on: bool) -> io::Result<()>;
    fn error_filter(&self, mask: u32) -> io::Result<()>;
    fn loopback(&self, on: bool) -> io::Result<()>;
    fn recv_own(&self, on: bool) -> io::Result<()>;
    fn timestamps(&self) -> io::Result<()>;
}

impl<T: SocketOptions> SocketOptionsDyn for T {
    fn filters(&self, f: &[CanFilter]) -> io::Result<()> {
        self.set_filters(f)
    }
    fn join(&self, on: bool) -> io::Result<()> {
        self.set_join_filters(on)
    }
    fn error_filter(&self, mask: u32) -> io::Result<()> {
        self.set_error_filter(mask)
    }
    fn loopback(&self, on: bool) -> io::Result<()> {
        self.set_loopback(on)
    }
    fn recv_own(&self, on: bool) -> io::Result<()> {
        self.set_recv_own_msgs(on)
    }
    fn timestamps(&self) -> io::Result<()> {
        self.set_recv_timestamp(true)
    }
}

fn opt(r: io::Result<()>, what: &str) -> Result<(), Fail> {
    r.map_err(|e| io_fail(format!("{}: {}", what, e)))
}

fn check_interface(name: &str) -> Result<(), Fail> {
    let base = format!("/sys/class/net/{}", name);
    let flags = std::fs::read_to_string(format!("{}/flags", base))
        .map_err(|_| fail(4, "interface", format!("interface {} does not exist", name)))?;
    let flags = u32::from_str_radix(flags.trim().trim_start_matches("0x"), 16).unwrap_or(0);
    if flags & 1 == 0 {
        return Err(fail(4, "interface", format!("interface {} is down", name)));
    }
    Ok(())
}

// ── operations ──────────────────────────────────────────────────────────────

fn read_frames(path: &str) -> Result<Vec<Doc>, Fail> {
    let reader: Box<dyn BufRead> = if path == "-" {
        Box::new(io::BufReader::new(io::stdin()))
    } else {
        Box::new(io::BufReader::new(
            std::fs::File::open(path).map_err(|e| usage(format!("{}: {}", path, e)))?,
        ))
    };
    let mut out = Vec::new();
    for line in reader.lines() {
        let line = line.map_err(|e| io_fail(e.to_string()))?;
        let t = line.trim();
        if t.is_empty() || t.starts_with('#') {
            continue;
        }
        out.push(doc_from_json(t)?);
    }
    Ok(out)
}

fn op_send(a: &Args) -> Result<(), Fail> {
    let frames = read_frames(&a.frames)?;
    if frames.iter().any(|f| f.fd) && !a.fd {
        return Err(usage("CAN FD frame without --fd"));
    }
    check_interface(&a.interface)?;
    let s = Sock::open(a)?;
    opt(s.opts().loopback(!a.no_loopback), "loopback")?;
    opt(s.opts().recv_own(a.recv_own), "recv own")?;
    if a.recv_own {
        opt(s.opts().timestamps(), "timestamps")?;
    }
    for f in &frames {
        s.send(f)?;
        if a.gap_us > 0 {
            std::thread::sleep(Duration::from_micros(a.gap_us));
        }
    }
    let mut echoed = 0;
    if a.recv_own {
        let end = Instant::now() + Duration::from_millis(a.timeout_ms);
        while echoed < frames.len() {
            let left = end.saturating_duration_since(Instant::now());
            if left.is_zero() {
                break;
            }
            match s.recv(left)? {
                Some((d, ts)) => {
                    emit(&format!(
                        "{{\"schemaVersion\":\"{}\",\"type\":\"frame\",\"frame\":{}}}",
                        SCHEMA,
                        d.json(ts, &a.interface)
                    ));
                    echoed += 1;
                }
                None => break,
            }
        }
        emit(&format!(
            "{{\"schemaVersion\":\"{}\",\"type\":\"result\",\"operation\":\"send\",\"sent\":{},\"echoed\":{}}}",
            SCHEMA,
            frames.len(),
            echoed
        ));
        if echoed < frames.len() {
            return Err(fail(3, "timeout", format!("{} of {} own frames echoed", echoed, frames.len())));
        }
        return Ok(());
    }
    emit(&format!(
        "{{\"schemaVersion\":\"{}\",\"type\":\"result\",\"operation\":\"send\",\"sent\":{}}}",
        SCHEMA,
        frames.len()
    ));
    Ok(())
}

fn op_receive(a: &Args) -> Result<(), Fail> {
    check_interface(&a.interface)?;
    let s = Sock::open(a)?;
    if !a.filters.is_empty() {
        let fs: Vec<CanFilter> = a
            .filters
            .iter()
            .map(|f| {
                if f.invert {
                    CanFilter::new_inverted(f.id & !INV_FILTER, f.mask)
                } else {
                    CanFilter::new(f.id, f.mask)
                }
            })
            .collect();
        opt(s.opts().filters(&fs), "filters")?;
    }
    if a.join {
        opt(s.opts().join(true), "join filters")?;
    }
    opt(s.opts().error_filter(a.error_mask), "error filter")?;
    opt(s.opts().timestamps(), "timestamps")?;
    emit(&format!("{{\"schemaVersion\":\"{}\",\"type\":\"ready\"}}", SCHEMA));
    let end = Instant::now() + Duration::from_millis(a.timeout_ms);
    let mut n = 0;
    while n < a.count {
        let left = end.saturating_duration_since(Instant::now());
        if left.is_zero() {
            break;
        }
        match s.recv(left)? {
            Some((d, ts)) => {
                emit(&format!(
                    "{{\"schemaVersion\":\"{}\",\"type\":\"frame\",\"frame\":{}}}",
                    SCHEMA,
                    d.json(ts, &a.interface)
                ));
                n += 1;
            }
            None => break,
        }
    }
    let complete = n >= a.count;
    emit(&format!(
        "{{\"schemaVersion\":\"{}\",\"type\":\"result\",\"operation\":\"receive\",\"received\":{},\"complete\":{}}}",
        SCHEMA, n, complete
    ));
    if !complete {
        return Err(fail(3, "timeout", format!("received {} of {}", n, a.count)));
    }
    Ok(())
}

fn print_fixture(a: &Args) -> Result<(), Fail> {
    let p = a.positional.first().ok_or_else(|| usage("print-fixture needs a path"))?;
    if p.contains("..") {
        return Err(usage(format!("no fixture {}", p)));
    }
    let data = std::fs::read(format!("/fixtures/{}", p)).map_err(|_| usage(format!("no fixture {}", p)))?;
    io::stdout().write_all(&data).map_err(|e| io_fail(e.to_string()))
}

fn run() -> Result<(), Fail> {
    let a = parse_args()?;
    match a.command.as_str() {
        "print-capabilities" => {
            emit(&capabilities());
            Ok(())
        }
        "print-version" => {
            emit(&version());
            Ok(())
        }
        "print-fixture" => print_fixture(&a),
        "send" => op_send(&a),
        "receive" => op_receive(&a),
        "capture" | "replay" | "decode" | "encode" | "convert" | "isotp-send" | "isotp-receive" => Err(
            unsupported(format!("operation {} is not supported by socketcanrs", a.command)),
        ),
        c => Err(usage(format!("unknown command {}", c))),
    }
}

fn main() {
    if let Err(f) = run() {
        emit(&format!(
            "{{\"schemaVersion\":\"{}\",\"type\":\"error\",\"code\":\"{}\",\"message\":{}}}",
            SCHEMA,
            f.code,
            quote(&f.message)
        ));
        exit(f.exit);
    }
}
