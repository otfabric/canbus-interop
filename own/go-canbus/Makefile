# The canbus-interop-otfabric image, from the repository root:
#   make -f own/go-canbus/Makefile image smoke interop
#
# Apart from the top-level Makefile on purpose: this image is not in ADAPTERS
# and not in a release of the harness. interop needs Linux with the vcan
# interfaces (make vcan).

IMAGE ?= ghcr.io/otfabric/canbus-interop-otfabric:dev
# The harness release of the reference images to test against.
VERSION ?= $(shell git tag -l 'v[0-9]*.[0-9]*.[0-9]*' --sort=-v:refname | head -1)
REFERENCES ?= canutils pythoncan socketcanrs scapy pythoncanisotp cantools canmatrix
SUITES ?= raw isotp dbc xl
BASE_REGISTRY ?= docker.io/library
ADMIN ?= sudo
DOCKER ?= docker

# The latest go-canbus release, as the workflow builds it.
UPSTREAM_VERSION ?= $(shell git ls-remote --tags --refs https://github.com/otfabric/go-canbus.git 'v[0-9]*' | sed 's,.*refs/tags/,,' | grep -E '^v[0-9]+\.[0-9]+\.[0-9]+$$' | sort -V | tail -1)
UPSTREAM_SHA ?= $(shell git ls-remote --tags https://github.com/otfabric/go-canbus.git 'refs/tags/$(UPSTREAM_VERSION)^{}' | cut -f1)

export VERSION SUITES ADMIN DOCKER
export ADAPTER_IMAGE_otfabric = $(IMAGE)

.PHONY: image smoke interop

image:
	$(DOCKER) build --build-arg BASE_REGISTRY=$(BASE_REGISTRY) --build-arg UPSTREAM_VERSION=$(UPSTREAM_VERSION) --build-arg UPSTREAM_SHA=$(UPSTREAM_SHA) --build-arg ADAPTER_VERSION=$(UPSTREAM_VERSION) --tag $(IMAGE) --file own/go-canbus/Dockerfile .

smoke:
	scripts/smoke.sh otfabric

interop:
	scripts/interop.sh otfabric $(REFERENCES)
