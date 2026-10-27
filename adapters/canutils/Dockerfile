# SPDX-License-Identifier: MIT
# canbus-interop adapter: linux-can/can-utils v2025.01 (GPL-2.0-only OR
# BSD-3-Clause, per file). The CAN work is done by the upstream programs
# cansend, candump, canplayer, isotpsend and isotprecv (the last two use the
# Linux kernel's CAN_ISOTP implementation); adapter.py only translates the
# container contract to their command lines and their output to JSON.
# The source the binaries were built from is shipped in the image, in
# /usr/share/src/can-utils-v2025.01.tar.gz.
# Build context: the repository root (make image-canutils).

ARG BASE_REGISTRY=docker.io/library

FROM ${BASE_REGISTRY}/debian:bookworm-slim@sha256:7ff6ba31527b9e336162fa061746c366c4b2032f4d2cff2078bea43f78efe3f8 AS build
ARG CAN_UTILS_VERSION=v2025.01
ARG CAN_UTILS_SHA256=88b30feace372c4a61e6adb2534791c0cfba6123ebcca7f59bbb76580d4a6915
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl gcc libc6-dev make \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src
RUN curl -fsSLo can-utils.tar.gz "https://github.com/linux-can/can-utils/archive/refs/tags/${CAN_UTILS_VERSION}.tar.gz" \
    && echo "${CAN_UTILS_SHA256}  can-utils.tar.gz" | sha256sum -c - \
    && tar xzf can-utils.tar.gz \
    && make -C "can-utils-${CAN_UTILS_VERSION#v}" -j"$(nproc)" cansend candump canplayer isotpsend isotprecv \
    && mkdir -p /out/bin /out/src /out/licenses \
    && cd "can-utils-${CAN_UTILS_VERSION#v}" \
    && cp cansend candump canplayer isotpsend isotprecv /out/bin/ \
    && cp LICENSES/* /out/licenses/ \
    && cp /src/can-utils.tar.gz "/out/src/can-utils-${CAN_UTILS_VERSION}.tar.gz"

FROM ${BASE_REGISTRY}/debian:bookworm-slim@sha256:7ff6ba31527b9e336162fa061746c366c4b2032f4d2cff2078bea43f78efe3f8
ARG ADAPTER_VERSION=dev
ENV UPSTREAM_VERSION=v2025.01 \
    UPSTREAM_REVISION=01083a64ebf28cc716efe2d2fd51c141042ae34b \
    ADAPTER_VERSION=${ADAPTER_VERSION} \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt/canbus-interop
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=build /out/bin/ /usr/local/bin/
COPY --from=build /out/src/ /usr/share/src/
COPY --from=build /out/licenses/ /usr/share/doc/can-utils/LICENSES/
COPY adapters/common/cbi.py adapters/canutils/adapter.py /opt/canbus-interop/
COPY fixtures /fixtures
COPY LICENSE THIRD_PARTY_NOTICES.md /usr/share/doc/canbus-interop/
COPY licenses /usr/share/doc/canbus-interop/licenses
RUN printf '#!/bin/sh\nexec python3 /opt/canbus-interop/adapter.py "$@"\n' > /usr/local/bin/canbus-interop \
    && chmod 0755 /usr/local/bin/canbus-interop

LABEL org.opencontainers.image.source="https://github.com/otfabric/canbus-interop" \
      org.opencontainers.image.description="canbus-interop adapter: linux-can/can-utils v2025.01 (kernel CAN_RAW and CAN_ISOTP)" \
      org.opencontainers.image.version="${ADAPTER_VERSION}" \
      org.opencontainers.image.licenses="MIT AND (GPL-2.0-only OR BSD-3-Clause)"

ENTRYPOINT ["canbus-interop"]
CMD ["print-capabilities"]
