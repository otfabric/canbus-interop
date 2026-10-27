# SPDX-License-Identifier: MIT
# canbus-interop adapter: scapy 2.8.0 (GPL-2.0-only).
# Build context: the repository root (make image-scapy).

ARG BASE_REGISTRY=docker.io/library
FROM ${BASE_REGISTRY}/python:3.12-slim-bookworm@sha256:6dd8b6dab6b3adc7812bab69eca5dbdc1a5cc690ad28306d234ffb4ef8ac9753

ARG ADAPTER_VERSION=dev
ENV UPSTREAM_REVISION=e2e35c07bce2f40e7513e1b29a6d300d5329dbc3 \
    ADAPTER_VERSION=${ADAPTER_VERSION} \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt/canbus-interop

# Every package, including the transitive ones, is pinned.
COPY adapters/scapy/requirements.txt /opt/canbus-interop/requirements.txt
RUN pip install --no-cache-dir --root-user-action=ignore --no-deps -r /opt/canbus-interop/requirements.txt \
    && pip check

COPY adapters/common/cbi.py adapters/scapy/adapter.py /opt/canbus-interop/
COPY fixtures /fixtures
COPY LICENSE THIRD_PARTY_NOTICES.md /usr/share/doc/canbus-interop/
COPY licenses /usr/share/doc/canbus-interop/licenses
RUN printf '#!/bin/sh\nexec python3 /opt/canbus-interop/adapter.py "$@"\n' > /usr/local/bin/canbus-interop \
    && chmod 0755 /usr/local/bin/canbus-interop

LABEL org.opencontainers.image.source="https://github.com/otfabric/canbus-interop" \
      org.opencontainers.image.description="canbus-interop adapter: scapy 2.8.0" \
      org.opencontainers.image.version="${ADAPTER_VERSION}" \
      org.opencontainers.image.licenses="MIT AND GPL-2.0-only"

ENTRYPOINT ["canbus-interop"]
CMD ["print-capabilities"]
