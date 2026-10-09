#!/usr/bin/env bash
set -euo pipefail

SCRIPT_PATH=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)
DOCKERFILE="${SCRIPT_PATH}/Dockerfile"
PROJECT_ROOT="$(cd "${SCRIPT_PATH}/.." && pwd)"
BSP_ROOT="$(cd "${PROJECT_ROOT}/../.." && pwd)"
OPTEE_OS_BUILD_DIR="${BSP_ROOT}/u-boot-zlg/build/optee-os"

readonly SCRIPT_PATH
readonly DOCKERFILE
readonly PROJECT_ROOT BSP_ROOT OPTEE_OS_BUILD_DIR

# shellcheck source=containers/common.sh
source "${SCRIPT_PATH}/common.sh"

CONTAINER_ENGINE=""
CHECK_ONLY=false

usage() {
    echo "usage: $(basename "$0") [--engine ENGINE] [--check] [--] COMMAND [ARG...]"
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
}

container_check_image_exists() {
    if ! "${CONTAINER_ENGINE}" image inspect "$(container_image_ref)" >/dev/null 2>&1; then
        echo "error: image not found: $(container_image_ref); run build-container.sh first" >&2
        exit 1
    fi
}

container_run_docker_command() {
    echo "Container: Running command in $(container_image_ref)"

    # Run as the host user so artifacts written into the mounted /work are
    # owned by the caller and deletable without sudo. podman gets keep-id
    # (UID mapping, resolves to a real username inside the container); docker
    # has no equivalent and falls back to an explicit --user.
    local user_args=()
    if [[ "${CONTAINER_ENGINE}" == "podman" ]]; then
        user_args=(--userns=keep-id)
    else
        user_args=(--user "$(id -u):$(id -g)")
    fi

    # Mount the OP-TEE OS build tree (contains the TA dev kit) read-only so the
    # Makefile's TA_DEV_KIT_DIR -- resolved relative to /work as
    # /u-boot-zlg/build/optee-os/... -- is reachable inside the container.
    local devkit_mount=()
    if [[ -d "${OPTEE_OS_BUILD_DIR}" ]]; then
        devkit_mount=(-v "${OPTEE_OS_BUILD_DIR}:/u-boot-zlg/build/optee-os:ro")
    else
        echo "Container: warning: ${OPTEE_OS_BUILD_DIR} not found; TA build will fail" >&2
    fi

    "${CONTAINER_ENGINE}" run --rm \
        "${user_args[@]}" \
        "${devkit_mount[@]}" \
        -v "${PWD}:/work" \
        -w /work \
        "$(container_image_ref)" \
        "$@"
}

container_run() {
    container_select_engine
    container_validate_environment
    container_load_metadata

    if [[ "${CHECK_ONLY}" == "true" ]]; then
        container_check_image_exists
        echo "Container: Image $(container_image_ref) is available"
        return
    fi

    container_check_image_exists
    container_run_docker_command "$@"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
    --)
        shift
        break
        ;;
    --engine)
        if [[ $# -lt 2 ]]; then
            echo "error: --engine requires a value" >&2
            usage >&2
            exit 1
        fi
        CONTAINER_ENGINE="$2"
        shift 2
        ;;
    --check)
        CHECK_ONLY=true
        shift
        ;;
    -h|--help)
        usage
        exit 0
        ;;
    -*)
        echo "error: unknown option: $1" >&2
        usage >&2
        exit 1
        ;;
    *)
        break
        ;;
    esac
done

if [[ "${CHECK_ONLY}" != "true" && $# -eq 0 ]]; then
    echo "error: command is required" >&2
    usage >&2
    exit 1
fi

container_run "$@"
