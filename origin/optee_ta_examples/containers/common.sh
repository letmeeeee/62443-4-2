#!/usr/bin/env bash

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    echo "error: containers/common.sh is a library and must be sourced" >&2
    exit 1
fi

IMAGE_NAME=""
IMAGE_TAG=""
TOOLBOX_NAME=""

container_dockerfile_metadata() {
    local key="$1"

    sed -n "s/^# ${key}: //p" "${DOCKERFILE}" | head -n 1
}

container_load_metadata() {
    if [[ -z "${DOCKERFILE:-}" ]]; then
        echo "error: DOCKERFILE is not set" >&2
        exit 1
    fi

    IMAGE_NAME=$(container_dockerfile_metadata "Image")
    IMAGE_TAG=$(container_dockerfile_metadata "Tag")
    TOOLBOX_NAME=$(container_dockerfile_metadata "Toolbox")

    if [[ -z "${IMAGE_NAME}" ]]; then
        echo "error: Dockerfile metadata is missing Image" >&2
        exit 1
    fi

    if [[ -z "${IMAGE_TAG}" ]]; then
        echo "error: Dockerfile metadata is missing Tag" >&2
        exit 1
    fi

    if [[ -z "${TOOLBOX_NAME}" ]]; then
        echo "error: Dockerfile metadata is missing Toolbox" >&2
        exit 1
    fi
}

container_image_ref() {
    echo "${IMAGE_NAME}:${IMAGE_TAG}"
}
