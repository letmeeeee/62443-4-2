#!/usr/bin/env bash
set -euo pipefail

SCRIPT_PATH=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)
DOCKERFILE="${SCRIPT_PATH}/Dockerfile"

readonly SCRIPT_PATH
readonly DOCKERFILE

# shellcheck source=containers/common.sh
source "${SCRIPT_PATH}/common.sh"

CONTAINER_ENGINE=""
BUILD_TOOLBOX=false
CHECK_ONLY=false

usage() {
    echo "usage: $(basename "$0") [--engine ENGINE] [--toolbox] [--check]"
}

container_select_engine() {
    if [[ -n "${CONTAINER_ENGINE}" ]]; then
        return
    fi

    if command -v podman >/dev/null 2>&1; then
        CONTAINER_ENGINE="podman"
    elif command -v docker >/dev/null 2>&1; then
        CONTAINER_ENGINE="docker"
    else
        echo "error: neither podman nor docker was found" >&2
        exit 1
    fi
}

container_validate_environment() {
    if [[ ! -f "${DOCKERFILE}" ]]; then
        echo "error: Dockerfile not found: ${DOCKERFILE}" >&2
        exit 1
    fi

    if [[ "${BUILD_TOOLBOX}" == "true" ]] && ! command -v toolbox >/dev/null 2>&1; then
        echo "error: toolbox was not found" >&2
        exit 1
    fi
}

container_build_image() {
    echo "Container: Building $(container_image_ref) from ${DOCKERFILE}"
    "${CONTAINER_ENGINE}" build -f "${DOCKERFILE}" -t "$(container_image_ref)" "${SCRIPT_PATH}"
}

container_check_image() {
    echo "Container: Checking image $(container_image_ref)"
    "${CONTAINER_ENGINE}" image inspect "$(container_image_ref)" >/dev/null
}

container_build_toolbox_image() {
    if toolbox list --containers | awk 'NR > 1 {print $2}' | grep -Fxq "${TOOLBOX_NAME}"; then
        echo "Toolbox: Removing existing ${TOOLBOX_NAME}"
        toolbox rm --force "${TOOLBOX_NAME}"
    fi

    echo "Toolbox: Creating ${TOOLBOX_NAME} from $(container_image_ref)"
    toolbox create --image "$(container_image_ref)" "${TOOLBOX_NAME}"
}

container_build() {
    container_select_engine
    container_validate_environment
    container_load_metadata

    if [[ "${CHECK_ONLY}" == "true" ]]; then
        container_check_image
        return
    fi

    container_build_image

    if [[ "${BUILD_TOOLBOX}" == "true" ]]; then
        container_build_toolbox_image
    fi
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --engine)
            if [[ $# -lt 2 ]]; then
                echo "error: --engine requires a value" >&2
                usage >&2
                exit 1
            fi
            CONTAINER_ENGINE="$2"
            shift 2
            ;;
        --toolbox)
            BUILD_TOOLBOX=true
            shift
            ;;
        --check)
            CHECK_ONLY=true
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "error: unknown option: $1" >&2
            usage >&2
            exit 1
            ;;
    esac
done

container_build
