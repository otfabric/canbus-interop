# SPDX-License-Identifier: MIT
# canbus-interop adapter: socketcan-rs (crate socketcan 4.0.0, MIT), a Rust
# SocketCAN library. src/main.rs implements the container contract on top of
# the crate's CanSocket/CanFdSocket. Cargo.lock pins every crate.
# Build context: the repository root (make image-socketcanrs).

ARG BASE_REGISTRY=docker.io/library

FROM ${BASE_REGISTRY}/rust:1.95-slim-bookworm@sha256:d7482085ff5b415f84dba5647ae71606650bdef00db7aeb69f4b3d170c3e4082 AS build
WORKDIR /src
COPY adapters/socketcanrs/Cargo.toml adapters/socketcanrs/Cargo.lock ./
COPY adapters/socketcanrs/src ./src
RUN cargo build --release --locked \
    && mkdir -p /out/licenses \
    && cp target/release/canbus-interop-socketcanrs /out/canbus-interop \
    && for d in "${CARGO_HOME:-/usr/local/cargo}"/registry/src/*/*/; do \
         n=$(basename "$d"); for l in "$d"LICENSE*; do [ -f "$l" ] && cp "$l" "/out/licenses/$n-$(basename "$l")"; done; \
       done; true

FROM ${BASE_REGISTRY}/debian:bookworm-slim@sha256:7ff6ba31527b9e336162fa061746c366c4b2032f4d2cff2078bea43f78efe3f8
ARG ADAPTER_VERSION=dev
ENV UPSTREAM_VERSION=4.0.0 \
    UPSTREAM_REVISION=cfa0d101a8c2fbaed1d5d1e7e11eb6fbdcfc30bd \
    ADAPTER_VERSION=${ADAPTER_VERSION}
COPY --from=build /out/canbus-interop /usr/local/bin/canbus-interop
COPY --from=build /out/licenses/ /usr/share/doc/socketcan-rs/crates/
COPY fixtures /fixtures
COPY LICENSE THIRD_PARTY_NOTICES.md /usr/share/doc/canbus-interop/
COPY licenses /usr/share/doc/canbus-interop/licenses

LABEL org.opencontainers.image.source="https://github.com/otfabric/canbus-interop" \
      org.opencontainers.image.description="canbus-interop adapter: socketcan-rs 4.0.0" \
      org.opencontainers.image.version="${ADAPTER_VERSION}" \
      org.opencontainers.image.licenses="MIT AND (MIT OR Apache-2.0)"

ENTRYPOINT ["canbus-interop"]
CMD ["print-capabilities"]
