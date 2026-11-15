# SPDX-License-Identifier: MIT
# canbus-interop adapter: python-can-isotp 2.0.7 (MIT AND LGPL-3.0-only).
# Build context: the repository root (make image-pythoncanisotp).

ARG BASE_REGISTRY=docker.io/library
FROM ${BASE_REGISTRY}/python:3.12-slim-bookworm@sha256:6dd8b6dab6b3adc7812bab69eca5dbdc1a5cc690ad28306d234ffb4ef8ac9753

ARG ADAPTER_VERSION=dev
ENV UPSTREAM_REVISION=4a672cecb8b5b448ebe7174447efb295550ebb90 \
    ADAPTER_VERSION=${ADAPTER_VERSION} \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt/canbus-interop

# Every package, including the transitive ones, is pinned by version and
# installed only from a wheel whose sha256 requirements.txt lists.
COPY adapters/pythoncanisotp/requirements.txt /opt/canbus-interop/requirements.txt
RUN pip install --no-cache-dir --root-user-action=ignore --no-deps --only-binary=:all: --require-hashes \
        -r /opt/canbus-interop/requirements.txt \
    && pip check

COPY adapters/common/cbi.py adapters/pythoncanisotp/adapter.py /opt/canbus-interop/
COPY fixtures /fixtures
COPY LICENSE THIRD_PARTY_NOTICES.md /usr/share/doc/canbus-interop/
COPY licenses /usr/share/doc/canbus-interop/licenses
# The licence texts again under /licenses/<component>/ (THIRD_PARTY_NOTICES.md).
COPY LICENSE THIRD_PARTY_NOTICES.md /licenses/canbus-interop/
COPY licenses/python-can-isotp-MIT.txt /licenses/python-can-isotp/
COPY licenses/python-can-LGPL-3.0.txt licenses/python-can-GPL-3.0.txt /licenses/python-can/
RUN printf '#!/bin/sh\nexec python3 /opt/canbus-interop/adapter.py "$@"\n' > /usr/local/bin/canbus-interop \
    && chmod 0755 /usr/local/bin/canbus-interop

LABEL org.opencontainers.image.source="https://github.com/otfabric/canbus-interop" \
      org.opencontainers.image.description="canbus-interop adapter: python-can-isotp 2.0.7" \
      org.opencontainers.image.version="${ADAPTER_VERSION}" \
      org.opencontainers.image.licenses="MIT AND MIT AND LGPL-3.0-only"

ENTRYPOINT ["canbus-interop"]
CMD ["print-capabilities"]
