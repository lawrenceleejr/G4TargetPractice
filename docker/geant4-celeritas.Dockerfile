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
RUN python3 -m pip install --no-cache-dir uproot awkward numpy matplotlib pyyaml \
    || pip3 install --no-cache-dir uproot awkward numpy matplotlib pyyaml
COPY gdmltp/ /app/pysrc/gdmltp/
COPY g4tp/ /app/pysrc/g4tp/
COPY pyproject.toml README.md /app/pysrc/
RUN python3 -m pip install --no-cache-dir /app/pysrc || pip3 install --no-cache-dir /app/pysrc
COPY g4sim/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

ENTRYPOINT ["/app/entrypoint.sh"]
