# SPDX-License-Identifier: MIT
#
# canbus-interop-otfabric: OT Fabric's own CAN stack behind the container contract.
# Not an independent implementation: see README.md.
#
# Build from the repository root:
#   make -f own/go-canbus/Makefile image
#
# The build takes the go-canbus release as UPSTREAM_VERSION (the released git tag,
# which is the Go module version) and its commit as UPSTREAM_SHA. There is no pin
# in this repository: the workflow passes the latest release. A build never uses
# main. go.mod and go.sum here are only a starting point for local work.

ARG BASE_REGISTRY=docker.io/library
# golang:1.27.2-trixie and debian:trixie-slim, multi-arch indexes
# (linux/amd64 and linux/arm64).
ARG GOLANG_DIGEST=sha256:e58d6f83b3416618d8bcac2b3dde1b7f7e3c4a77d25e88637f8bbae81536c48d
ARG DEBIAN_DIGEST=sha256:f6b08b09a05725f9431502d3b5714f5c4576e82c1a84fa1debe0c24a7e0c3ec4

FROM ${BASE_REGISTRY}/golang:1.27.2-trixie@${GOLANG_DIGEST} AS build

ARG UPSTREAM_VERSION
ARG UPSTREAM_SHA
ARG ADAPTER_VERSION=dev
ARG GOPROXY=https://proxy.golang.org

ENV CGO_ENABLED=0 GOPROXY=${GOPROXY} GOSUMDB=sum.golang.org GOTOOLCHAIN=local
WORKDIR /src
COPY own/go-canbus/go.mod own/go-canbus/go.sum own/go-canbus/*.go ./

RUN set -eu; \
    test -n "${UPSTREAM_VERSION}" || { echo "UPSTREAM_VERSION is required" >&2; exit 1; }; \
    echo "${UPSTREAM_SHA}" | grep -Eq '^[0-9a-f]{40}$'; \
    go get "github.com/otfabric/go-canbus@${UPSTREAM_VERSION}"; \
    go mod tidy; \
    built="$(go list -m -f '{{.Version}}' github.com/otfabric/go-canbus)"; \
    test "${built}" = "${UPSTREAM_VERSION}" || { echo "go.mod has go-canbus ${built}, want ${UPSTREAM_VERSION}" >&2; exit 1; }; \
    go mod download && go mod verify; \
    origin="$(go mod download -json "github.com/otfabric/go-canbus@${UPSTREAM_VERSION}" \
        | sed -nE 's/^[[:space:]]*"Hash": "([0-9a-f]{40})".*/\1/p')"; \
    if [ -n "${origin}" ] && [ "${origin}" != "${UPSTREAM_SHA}" ]; then \
        echo "go-canbus ${UPSTREAM_VERSION} is commit ${origin}, not ${UPSTREAM_SHA}" >&2; exit 1; \
    fi

RUN set -eu; \
    test -z "$(gofmt -l .)"; \
    go vet ./...; \
    go test ./...; \
    go build -trimpath -ldflags "-s -w \
        -X main.adapterVersion=${ADAPTER_VERSION} \
        -X main.upstreamVersion=${UPSTREAM_VERSION} \
        -X main.upstreamRevision=${UPSTREAM_SHA}" \
        -o /out/canbus-interop .; \
    mkdir -p /out/licenses/go; \
    cp "$(go env GOROOT)/LICENSE" /out/licenses/go/LICENSE; \
    go version -m /out/canbus-interop | awk '$1 == "dep" { print $2, $3 }' > /out/licenses/BUNDLED-MODULES.txt; \
    test -s /out/licenses/BUNDLED-MODULES.txt; \
    while read -r module modversion; do \
        dir="$(go list -m -f '{{.Dir}}' "${module}")"; \
        mkdir -p "/out/licenses/${module}"; \
        for file in "${dir}"/LICENSE* "${dir}"/LICENCE* "${dir}"/COPYING* "${dir}"/NOTICE*; do \
            if [ -f "${file}" ]; then cp "${file}" "/out/licenses/${module}/"; fi; \
        done; \
        test -n "$(ls "/out/licenses/${module}")" || { echo "no licence file in ${module} ${modversion}" >&2; exit 1; }; \
    done < /out/licenses/BUNDLED-MODULES.txt

FROM ${BASE_REGISTRY}/debian:trixie-slim@${DEBIAN_DIGEST} AS runtime

ARG ADAPTER_VERSION=dev
ARG UPSTREAM_VERSION

# CAN raw sockets need no capability: the adapter runs as an ordinary user.
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin interop

COPY --from=build /out/canbus-interop /usr/local/bin/canbus-interop
COPY --from=build /out/licenses /licenses
COPY LICENSE /licenses/canbus-interop/LICENSE
COPY fixtures /fixtures

LABEL org.opencontainers.image.title="canbus-interop-otfabric" \
      org.opencontainers.image.description="OT Fabric go-canbus behind the canbus-interop container contract, for testing. Not an independent implementation." \
      org.opencontainers.image.source="https://github.com/otfabric/canbus-interop" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="${UPSTREAM_VERSION}"

USER interop

ENTRYPOINT ["canbus-interop"]
CMD ["print-capabilities"]
