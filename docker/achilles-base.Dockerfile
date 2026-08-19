# Achilles base image for GDMLTargetPractice, built from source so users never
# compile anything themselves. Provides the `achilles` binary (with its data
# files installed) on PATH; Achilles's CMake fetches its bundled dependencies
# (HepMC3, fmt, spdlog, yaml-cpp, ...) at configure time.
#
# Built by .github/workflows/build-generator-bases.yml and published as
# ghcr.io/<owner>/g4targetpractice-achilles-base; the fast per-push achilles
# app image (docker/achilles.Dockerfile) layers gdmltp + the driver on top.
ARG UBUNTU=ubuntu:22.04
FROM ${UBUNTU}

ARG ACHILLES_REF=main

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gfortran cmake git wget curl ca-certificates \
    python3 python3-pip python3-dev \
    zlib1g-dev libhdf5-dev libgsl-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt

RUN git clone --recursive --branch ${ACHILLES_REF} --depth 1 \
      https://github.com/AchillesGen/Achilles.git /opt/achilles-src && \
    cmake -S /opt/achilles-src -B /opt/achilles-build \
      -DCMAKE_BUILD_TYPE=Release \
      -DCMAKE_INSTALL_PREFIX=/opt/achilles \
      -DACHILLES_ENABLE_TESTING=OFF && \
    cmake --build /opt/achilles-build -j"$(nproc)" && \
    (cmake --install /opt/achilles-build || true)

# Belt and braces for run-time data resolution: keep the source data/ tree and
# the built binaries available regardless of how complete `cmake --install` is
# for the pinned ref.
RUN mkdir -p /opt/achilles/bin /opt/achilles/share/achilles && \
    if [ -d /opt/achilles-build/bin ]; then cp -r /opt/achilles-build/bin/. /opt/achilles/bin/; fi && \
    if [ -d /opt/achilles-src/data ]; then cp -r /opt/achilles-src/data /opt/achilles/share/achilles/; fi && \
    rm -rf /opt/achilles-build && \
    ls /opt/achilles/bin

ENV ACHILLES_DIR=/opt/achilles
ENV PATH=/opt/achilles/bin:${PATH}
ENV LD_LIBRARY_PATH=/opt/achilles/lib:/opt/achilles/lib64

# Sanity: the binary must exist and link.
RUN command -v achilles && (achilles --help >/dev/null 2>&1 || ldd "$(command -v achilles)")

WORKDIR /work
