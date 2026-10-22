# The build environment for ohsdigi's release binaries (tools/build-ohsdigi.sh).
#
# Debian bookworm, not the Debian 13 that the development machine runs: a binary linked on 13
# needs glibc 2.38+ and will not load on Raspberry Pi OS bookworm (2.36) -
# the same gap that once broke another project's deploy. Building on the oldest
# system we ship to is what makes one .so serve all of them.
#
# One image cross-builds all three targets: native amd64, arm64 with
# Debian's aarch64 cross-gcc as the linker (no Pi is needed to build), and
# Windows x64 with mingw-w64 (PyO3 links python3.dll by raw-dylib, so no
# Windows Python is needed either). The Rust toolchain is pinned by the base
# image's digest, so a rebuild of the image gets the same compiler.
#
# The image also makes the ohs-ohsdigi wheels (tools/build-wheels.sh) with
# maturin, pinned by version and hash in rust/ohsdigi/wheel-requirements.txt
# and installed into a venv of its own, so it never meets the Debian
# Python's packages. The bare-module build (tools/build-ohsdigi.sh) does not
# use it; the Rust toolchain both build with is the same one.
ARG BASE=docker.io/library/rust:1.98.1-bookworm@sha256:c49256cbe5ea0188bc658a689500d70c41eb51f009a7a7be209caf60a944f3ec
FROM ${BASE}
RUN apt-get update \
 && apt-get install -y --no-install-recommends gcc-aarch64-linux-gnu libc6-dev-arm64-cross gcc-mingw-w64-x86-64 python3-venv \
 && rm -rf /var/lib/apt/lists/*
RUN rustup target add aarch64-unknown-linux-gnu x86_64-pc-windows-gnu
ENV CARGO_TARGET_AARCH64_UNKNOWN_LINUX_GNU_LINKER=aarch64-linux-gnu-gcc \
    CARGO_TARGET_X86_64_PC_WINDOWS_GNU_LINKER=x86_64-w64-mingw32-gcc
COPY ohsdigi/wheel-requirements.txt /opt/wheel-requirements.txt
RUN python3 -m venv /opt/maturin \
 && /opt/maturin/bin/pip install --no-cache-dir --require-hashes --only-binary=:all: -r /opt/wheel-requirements.txt
