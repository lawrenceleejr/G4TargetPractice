# Celeritas-enabled Geant4 image for GDMLTargetPractice (CPU-only EM offload).
# Previously a heredoc inside build-celeritas-deploy.yml; now checked in.
ARG BASE=ghcr.io/lawrenceleejr/root-geant4-garfield:cpp17_root-v6-26-10_geant4-v11.4.1_garfield-e0a9f171
FROM ${BASE}

# Qt6 runtime libraries for the Geant4 vis drivers + Celeritas build deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    libqt6core6 libqt6gui6 libqt6widgets6 libqt6opengl6 \
    git ca-certificates wget nlohmann-json3-dev \
    && rm -rf /var/lib/apt/lists/*

# Celeritas needs CMake >= 3.24, newer than the base image ships
RUN wget -q https://github.com/Kitware/CMake/releases/download/v3.29.6/cmake-3.29.6-linux-x86_64.tar.gz && \
    tar -xzf cmake-3.29.6-linux-x86_64.tar.gz -C /opt && \
    rm cmake-3.29.6-linux-x86_64.tar.gz
ENV PATH=/opt/cmake-3.29.6-linux-x86_64/bin:$PATH

# HepMC3 (the generator->Geant4 hand-off interchange g4sim links against)
ARG HEPMC3_VERSION=3.3.0
RUN wget -q https://gitlab.cern.ch/hepmc/HepMC3/-/archive/${HEPMC3_VERSION}/HepMC3-${HEPMC3_VERSION}.tar.gz && \
    tar xzf HepMC3-${HEPMC3_VERSION}.tar.gz && \
    cmake -S HepMC3-${HEPMC3_VERSION} -B hepmc3-build \
        -DCMAKE_INSTALL_PREFIX=/usr/local \
        -DHEPMC3_ENABLE_PYTHON=OFF -DHEPMC3_ENABLE_ROOTIO=OFF \
        -DHEPMC3_ENABLE_TEST=OFF -DHEPMC3_BUILD_EXAMPLES=OFF && \
    cmake --build hepmc3-build --target install -j"$(nproc)" && ldconfig && \
    rm -rf HepMC3-${HEPMC3_VERSION}* hepmc3-build

# Build Celeritas (CPU-only) against the base image's Geant4. Geant4 core-geo
# means any user GDML geometry works without conversion.
WORKDIR /opt
RUN git clone --depth 1 --branch v0.6.3 https://github.com/celeritas-project/celeritas.git && \
    cmake -S celeritas -B celeritas-build \
      -DCMAKE_BUILD_TYPE=Release \
      -DCELERITAS_USE_Geant4=ON \
      -DCELERITAS_CORE_GEO=Geant4 \
      -DCELERITAS_USE_CUDA=OFF \
      -DCELERITAS_USE_HIP=OFF \
      -DCELERITAS_USE_ROOT=OFF \
      -DCELERITAS_USE_VecGeom=OFF \
      -DCELERITAS_USE_MPI=OFF \
      -DCELERITAS_BUILD_TESTS=OFF \
      -DCMAKE_INSTALL_PREFIX=/opt/celeritas-install && \
    cmake --build celeritas-build -j$(nproc) && \
    cmake --install celeritas-build && \
    rm -rf celeritas celeritas-build
ENV LD_LIBRARY_PATH=/opt/celeritas-install/lib:/opt/celeritas-install/lib64:$LD_LIBRARY_PATH

# Build g4sim with the Celeritas offload enabled
WORKDIR /app
COPY g4sim/ /app/g4sim/
RUN mkdir -p /app/build && cd /app/build && \
    cmake /app/g4sim/ -DWITH_CELERITAS=ON -DCMAKE_PREFIX_PATH=/opt/celeritas-install && \
    cmake --build .
RUN if [ -f /usr/lib/x86_64-linux-gnu/libQt5Core.so.5 ]; then strip --remove-section=.note.ABI-tag /usr/lib/x86_64-linux-gnu/libQt5Core.so.5; fi
RUN if [ -f /lib/x86_64-linux-gnu/libQt6Core.so.6 ]; then strip --remove-section=.note.ABI-tag /lib/x86_64-linux-gnu/libQt6Core.so.6; fi

COPY scans/ /app/scans/

# gdmltp tooling (pure Python, no ROOT) + deprecated g4tp shim
RUN python3 -m pip install --no-cache-dir --upgrade pip setuptools wheel && \
    python3 -m pip install --no-cache-dir uproot awkward numpy matplotlib pyyaml
COPY gdmltp/ /app/pysrc/gdmltp/
COPY g4tp/ /app/pysrc/g4tp/
COPY pyproject.toml README.md /app/pysrc/
RUN python3 -m pip install --no-cache-dir /app/pysrc && \
    python3 -c "import gdmltp; from gdmltp.backends import genie_convert, achilles_convert; print('gdmltp', gdmltp.__version__)"
COPY g4sim/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

ENTRYPOINT ["/app/entrypoint.sh"]
