#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
#
# check-versions.sh: fail when versions.yaml disagrees with the build inputs
# (Dockerfiles of adapters/ and own/, requirements.txt, Cargo.toml/Cargo.lock),
# the contract or the tools of the workflows and the Makefile, or when a build
# input is not pinned by hash: every implementation records source_sha256 or
# wheel_sha256, every Python requirement carries --hash=sha256: and is
# installed with --require-hashes.
set -euo pipefail
cd "$(dirname "$0")/.."
exec python3 - <<'PY'
import glob, re, sys

def parse(path):
    """The subset of YAML versions.yaml uses: nested maps by indentation, scalars, [lists]."""
    root, stack = {}, [(-1, None)]
    stack[0] = (-1, root)
    for raw in open(path):
        line = raw.split(" #")[0].rstrip() if not raw.lstrip().startswith("#") else ""
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        key, _, value = line.strip().partition(":")
        value = value.strip()
        while stack[-1][0] >= indent:
            stack.pop()
        parent = stack[-1][1]
        if value in ("", ">-"):
            parent[key] = {} if value == "" else ""
            if value == "":
                stack.append((indent, parent[key]))
        else:
            parent[key] = value.strip('"')
    return root

def logical_lines(path):
    """The lines of a file with backslash continuations joined."""
    lines, cur = [], ""
    for raw in open(path):
        raw = raw.rstrip("\r\n")
        if raw.endswith("\\"):
            cur += raw[:-1] + " "
            continue
        lines.append(cur + raw)
        cur = ""
    if cur:
        lines.append(cur)
    return lines

def requirements(path):
    """(spec, [sha256, ...]) for every requirement of a requirements file."""
    out = []
    for line in logical_lines(path):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        out.append((line.split()[0], re.findall(r"--hash=sha256:([0-9a-f]{64})(?![0-9a-f])", line)))
    return out

def norm(name):
    return re.sub(r"[-_.]+", "-", name).lower()

v = parse("versions.yaml")
errors = []
def need(path, text, what):
    if text not in open(path).read():
        errors.append("%s: %s not found (%s)" % (path, text, what))

SHA256 = re.compile(r"^[0-9a-f]{64}$")
PINNED = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*==[^=\s]+$")

contract = open("docs/CONTAINER_CONTRACT.md").read()
if "Version: **%s**" % v["contract_version"] not in contract:
    errors.append("docs/CONTAINER_CONTRACT.md does not say Version: **%s**" % v["contract_version"])

bases = v["base_images"]
for name, ref in bases.items():
    if not re.search(r"@sha256:[0-9a-f]{64}$", ref):
        errors.append("versions.yaml: base_images.%s is not pinned by digest: %s" % (name, ref))

def check_bases(df):
    """Every FROM of a Dockerfile, with the defaults of its ARGs substituted, is in base_images."""
    text = open(df).read()
    args = dict(re.findall(r"^ARG (\w+)=(\S+)", text, re.M))
    for ref in re.findall(r"^FROM \$\{BASE_REGISTRY\}/(\S+)", text, re.M):
        ref = re.sub(r"\$\{(\w+)\}", lambda m: args.get(m.group(1), m.group(0)), ref)
        if ref not in bases.values():
            errors.append("%s: base image %s is not in versions.yaml base_images" % (df, ref))
    return text

for name, impl in v["implementations"].items():
    df = "adapters/%s/Dockerfile" % name
    text = check_bases(df)
    need(df, "UPSTREAM_REVISION=" + impl["revision"], "revision")
    hashes = [k for k in ("source_sha256", "wheel_sha256") if k in impl]
    if not hashes:
        errors.append("versions.yaml: %s has neither source_sha256 nor wheel_sha256" % name)
    for k in hashes:
        if not SHA256.match(impl[k]):
            errors.append("versions.yaml: %s.%s is not a sha256: %s" % (name, k, impl[k]))
    if "package" in impl:
        req = "adapters/%s/requirements.txt" % name
        need(req, "%s==%s" % (impl["package"], impl["version"]), "package pin")
        wheels = []
        for spec, digests in requirements(req):
            if not PINNED.match(spec):
                errors.append("%s: %s is not pinned to one version" % (req, spec))
            if not digests:
                errors.append("%s: %s has no --hash=sha256:" % (req, spec))
            if norm(spec.partition("==")[0]) == norm(impl["package"]):
                wheels = digests
        if "wheel_sha256" not in impl:
            errors.append("versions.yaml: %s installs a wheel and has no wheel_sha256" % name)
        elif impl["wheel_sha256"] not in wheels:
            errors.append("%s: wheel_sha256 of %s (versions.yaml) is not a hash of %s==%s"
                          % (req, name, impl["package"], impl["version"]))
        installs = [l for l in logical_lines(df) if "pip install" in l]
        if not installs:
            errors.append("%s: no pip install" % df)
        for l in installs:
            for flag in ("--require-hashes", "--only-binary=:all:", "--no-deps"):
                if flag not in l.split():
                    errors.append("%s: pip install without %s" % (df, flag))
    if name == "canutils":
        need(df, "CAN_UTILS_VERSION=" + impl["version"], "version")
        need(df, "CAN_UTILS_SHA256=" + impl.get("source_sha256", "?"), "source hash")
    if name == "socketcanrs":
        need("adapters/socketcanrs/Cargo.toml", 'version = "=%s"' % impl["version"], "crate pin")
        need("adapters/socketcanrs/Cargo.lock", 'name = "socketcan"\nversion = "%s"' % impl["version"], "lock")
        need(df, "UPSTREAM_VERSION=" + impl["version"], "version")
        m = re.search(r'name = "%s"\nversion = "%s"\nsource = "[^"]*"\nchecksum = "([0-9a-f]{64})"'
                      % (re.escape(impl["crate"]), re.escape(impl["version"])),
                      open("adapters/socketcanrs/Cargo.lock").read())
        if not m or m.group(1) != impl.get("source_sha256"):
            errors.append("adapters/socketcanrs/Cargo.lock: the checksum of %s %s is not source_sha256 (versions.yaml)"
                          % (impl["crate"], impl["version"]))

# OT Fabric's own images: their base images, through the ARG defaults the
# FROM lines use (GOLANG_DIGEST, DEBIAN_DIGEST).
for df in sorted(glob.glob("own/*/Dockerfile")):
    check_bases(df)

# Tools: every pip/pipx install of the workflows and the Makefile names a
# version of versions.yaml tools (or requirements-dev.txt, which must), and
# every tool image they run is the pinned one.
tools = v.get("tools") or {}
if not tools:
    errors.append("versions.yaml: no tools")
packages = {norm(k): t for k, t in tools.items() if "@" not in t}
images = {t.split("@")[0].rsplit(":", 1)[0]: t for t in tools.values() if "@" in t}
for t in images.values():
    if not re.search(r"@sha256:[0-9a-f]{64}$", t):
        errors.append("versions.yaml: tool image %s is not pinned by digest" % t)
for spec, _ in requirements("requirements-dev.txt"):
    name, _, version = spec.partition("==")
    if not PINNED.match(spec) or packages.get(norm(name)) != version:
        errors.append("requirements-dev.txt: %s is not the version of versions.yaml tools" % spec)
for path in ["Makefile"] + sorted(glob.glob(".github/workflows/*.yml")):
    for line in logical_lines(path):
        for m in re.finditer(r"\bpipx? install\b(.*)", line):
            words = iter(m.group(1).replace("'", " ").replace('"', " ").split())
            for w in words:
                if w in ("&&", "||", ";", "|"):
                    break
                if w in ("-r", "--requirement"):
                    f = next(words, "")
                    if f.rsplit("/", 1)[-1] != "requirements-dev.txt":
                        errors.append("%s: pip install -r %s (want requirements-dev.txt)" % (path, f))
                    continue
                if w.startswith("-"):
                    continue
                name, _, version = w.partition("==")
                if not PINNED.match(w) or packages.get(norm(name)) != version:
                    errors.append("%s: %s is installed without the version of versions.yaml tools" % (path, w))
    text = open(path).read()
    for image, pinned in images.items():
        for ref in re.findall(r"(?:^|[\s/])(%s[:@][^\s'\"]+)" % re.escape(image), text, re.M):
            if ref != pinned:
                errors.append("%s: %s (versions.yaml tools: %s)" % (path, ref, pinned))
    for ref in re.findall(r"(?:\$\(TOOLS_REGISTRY\)|\$\{\{? *(?:env\.)?TOOLS_REGISTRY *\}?\})/library/([^\s'\"]+)", text):
        if ref not in bases.values():
            errors.append("%s: tool image library/%s is not in versions.yaml base_images" % (path, ref))

if errors:
    print("versions.yaml disagrees with the build inputs:")
    for e in errors:
        print("  " + e)
    sys.exit(1)
print("versions.yaml agrees with %d adapters, %d own Dockerfile(s), the tools and the contract"
      % (len(v["implementations"]), len(glob.glob("own/*/Dockerfile"))))
PY
