FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        python3 \
        python3-pip \
        python3-venv \
        python3-dev \
        # OpenCV / Flet desktop runtime (headless GUI + preview)
        libegl1 \
        libgles2 \
        libgl1 \
        libglib2.0-0 \
        libgtk-3-0 \
        libgstreamer1.0-0 \
        libgstreamer-plugins-base1.0-0 \
        # Screenshots / manual GUI verification
        scrot \
        xdotool \
        imagemagick \
        xvfb \
    && rm -rf /var/lib/apt/lists/*

# Cloud Agent VMs run as ubuntu
RUN useradd -m -s /bin/bash ubuntu || true
USER ubuntu
WORKDIR /home/ubuntu
