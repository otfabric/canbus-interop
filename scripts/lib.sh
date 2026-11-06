#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
#
# Shared helpers of the shell scripts. Source, do not execute.
#
# Environment: REGISTRY (default ghcr.io/otfabric), VERSION (image tag,
#              default dev), IMAGE_TEMPLATE (image name with {adapter}, takes
#              precedence over REGISTRY and VERSION), ADAPTER_IMAGE_<adapter>.

REGISTRY="${REGISTRY:-ghcr.io/otfabric}"
VERSION="${VERSION:-dev}"
if [[ -z "${IMAGE_TEMPLATE:-}" ]]; then
    IMAGE_TEMPLATE="${REGISTRY}/canbus-interop-{adapter}:${VERSION}"
fi
export IMAGE_TEMPLATE

# image_of <adapter>: ADAPTER_IMAGE_<adapter> names an image outside the
# release set, which this repository's scripts know nothing about.
image_of() {
    local override="ADAPTER_IMAGE_$1"
    if [[ -n "${!override:-}" ]]; then
        echo "${!override}"
    else
        local placeholder='{adapter}'
        echo "${IMAGE_TEMPLATE//"${placeholder}"/$1}"
    fi
}
