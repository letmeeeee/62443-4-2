# -----------------------------------------------------------------------------
# Image: optee-builder
# Tag: latest
# Toolbox: optee-builder
# Purpose: Debian build environment for root filesystem and firmware builds.
# Base: debian:trixie
# Maintainer: Zesty39
#
# Notes:
#   - Used for local Debian image and firmware build workflows.
#   - Keep package versions pinned when reproducibility is required.
#   - Do not include credentials or private keys in the image.
# -----------------------------------------------------------------------------

FROM debian:trixie

ARG USERNAME=builder
ARG USER_UID=1000
ARG USER_GID=1000
ARG CREATE_USER=true

ENV DEBIAN_FRONTEND=noninteractive
ENV LANG=en_US.UTF-8
ENV LC_ALL=en_US.UTF-8
ENV LANGUAGE=en_US:en

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    wget \
    gnupg \
    sudo \
    passwd \
    util-linux \
    libcap2-bin \
    zsh \
    locales \
    fontconfig \
    && rm -rf /var/lib/apt/lists/*

RUN sed -i 's/^# *en_US.UTF-8 UTF-8/en_US.UTF-8 UTF-8/' /etc/locale.gen && \
    locale-gen en_US.UTF-8 && \
    update-locale LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 LANGUAGE=en_US:en

RUN dpkg --add-architecture arm64

RUN rm -f /etc/apt/sources.list && \
    rm -f /etc/apt/sources.list.d/* && \
    cat > /etc/apt/sources.list.d/debian.sources <<'EOF'
Types: deb
URIs: http://deb.debian.org/debian
Suites: trixie trixie-updates
Components: main contrib non-free non-free-firmware
Architectures: amd64 arm64
Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg

Types: deb
URIs: http://deb.debian.org/debian-security
Suites: trixie-security
Components: main contrib non-free non-free-firmware
Architectures: amd64 arm64
Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg
EOF

RUN apt-get update && apt-get install -y --no-install-recommends \
    make \
    gcc-aarch64-linux-gnu \
    python3 \
    python3-cryptography \
    libc6-dev:arm64 \
    optee-client-dev:arm64 \
    && rm -rf /var/lib/apt/lists/*

ENV CROSS_COMPILE=aarch64-linux-gnu-
ENV LIBTEEC_LIB=/usr/lib/aarch64-linux-gnu

RUN mkdir -p /work && \
    if [ "${CREATE_USER}" = "true" ]; then \
        if getent group "${USER_GID}" >/dev/null; then \
            useradd --uid "${USER_UID}" \
                    --gid "${USER_GID}" \
                    --create-home \
                    --shell /bin/bash \
                    "${USERNAME}"; \
        else \
            groupadd --gid "${USER_GID}" "${USERNAME}"; \
            useradd --uid "${USER_UID}" \
                    --gid "${USER_GID}" \
                    --create-home \
                    --shell /bin/bash \
                    "${USERNAME}"; \
        fi && \
        usermod -aG sudo "${USERNAME}" && \
        echo "${USERNAME} ALL=(ALL) NOPASSWD:ALL" > "/etc/sudoers.d/${USERNAME}" && \
        chmod 0440 "/etc/sudoers.d/${USERNAME}" && \
        chown -R "${USER_UID}:${USER_GID}" "/home/${USERNAME}" /work; \
    fi

LABEL com.github.containers.toolbox="true"

WORKDIR /work

CMD ["/bin/bash"]
