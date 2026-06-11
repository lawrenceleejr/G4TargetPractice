 FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

# Install dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    wget \
    git \
    gdb \
    libxerces-c-dev \
    libexpat1-dev \
    libgl1-mesa-dev \
    libxmu-dev \
    libxi-dev \
    libmotif-dev \
    emacs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt

RUN wget https://root.cern.ch/download/root_v6.28.12.Linux-ubuntu22-x86_64-gcc11.4.tar.gz && \
    tar -xzf root_v6.28.12.Linux-ubuntu22-x86_64-gcc11.4.tar.gz && \
    rm root_v6.28.12.Linux-ubuntu22-x86_64-gcc11.4.tar.gz
    
# Download Geant4
RUN wget https://gitlab.cern.ch/geant4/geant4/-/archive/v11.4.1/geant4-v11.4.1.tar.gz \
 && tar -xzf geant4-v11.4.1.tar.gz

# Build Geant4
RUN mkdir geant4-build && cd geant4-build && \
    cmake ../geant4-v11.4.1 \
      -DCMAKE_BUILD_TYPE=Debug \
      -DGEANT4_USE_NEUTRINO=ON \
      -DGEANT4_USE_G4NDL=ON \
      -DGEANT4_USE_RADIOACTIVE_DECAY=ON \
      -DGEANT4_BUILD_MULTITHREADED=ON \
      -DGEANT4_USE_GDML=ON \
      -DGEANT4_USE_OPENGL_X11=OFF \
      -DGEANT4_USE_QT=OFF \
      -DGEANT4_USE_UISESSION=ON \
      -DGEANT4_INSTALL_DATA=ON \
      -DCMAKE_INSTALL_PREFIX=/opt/geant4-install \
 && make -j4 && make install

# Setup environment
ENV GEANT4_DIR=/opt/geant4-install
ENV PATH=/opt/geant4-install/bin:$PATH
ENV LD_LIBRARY_PATH=/opt/geant4-install/lib:$LD_LIBRARY_PATH

# Optionally build Celeritas (CPU-only) for EM track offload.
# Enable with: docker build --build-arg WITH_CELERITAS=ON .
# Then configure g4sim with -DWITH_CELERITAS=ON
ARG WITH_CELERITAS=OFF
ENV CELERITAS_DIR=/opt/celeritas-install
RUN if [ "$WITH_CELERITAS" = "ON" ]; then \
      apt-get update && apt-get install -y nlohmann-json3-dev && \
      rm -rf /var/lib/apt/lists/* && \
      git clone --depth 1 --branch v0.6.3 https://github.com/celeritas-project/celeritas.git && \
      cmake -S celeritas -B celeritas-build \
        -DCMAKE_BUILD_TYPE=Release \
        -DCELERITAS_USE_Geant4=ON \
        -DCELERITAS_USE_CUDA=OFF \
        -DCELERITAS_USE_HIP=OFF \
        -DCELERITAS_USE_ROOT=OFF \
        -DCELERITAS_USE_VecGeom=OFF \
        -DCELERITAS_USE_MPI=OFF \
        -DCELERITAS_BUILD_TESTS=OFF \
        -DCMAKE_PREFIX_PATH=/opt/geant4-install \
        -DCMAKE_INSTALL_PREFIX=${CELERITAS_DIR} && \
      cmake --build celeritas-build -j4 && \
      cmake --install celeritas-build && \
      rm -rf celeritas celeritas-build ; \
    fi
ENV LD_LIBRARY_PATH=${CELERITAS_DIR}/lib:$LD_LIBRARY_PATH
ENV CMAKE_PREFIX_PATH=${CELERITAS_DIR}:$CMAKE_PREFIX_PATH

WORKDIR /workspace

