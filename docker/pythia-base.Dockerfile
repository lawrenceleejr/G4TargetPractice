# Pythia 8 + HepMC3 base image for GDMLTargetPractice.
#
# Built by .github/workflows/build-generator-bases.yml. Unlike the GENIE base
# (ROOT + Pythia6 + LHAPDF + GENIE, ~2-3 h) this is a cheap build: Pythia 8 and
# HepMC3 are self-contained C++ with no heavy dependencies, so it compiles in
# minutes. That is a large part of the appeal of the pythia backend -- TeV-scale
# DIS with no cross-section splines to precompute.
FROM ubuntu:22.04

ARG PYTHIA_VERSION=8315
ARG HEPMC3_VERSION=3.2.6
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential gfortran cmake git wget curl ca-certificates \
      python3 python3-pip python3-dev rsync zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt

# --- HepMC3 (the generator -> Geant4 interchange format) ----------------------
ENV HEPMC3_DIR=/opt/hepmc3
RUN wget -q --tries=5 --retry-connrefused --waitretry=20 --timeout=60 \
      "https://hepmc.web.cern.ch/hepmc/releases/HepMC3-${HEPMC3_VERSION}.tar.gz" \
      -O hepmc3.tar.gz && \
    tar -xzf hepmc3.tar.gz && rm hepmc3.tar.gz && \
    cmake -S "HepMC3-${HEPMC3_VERSION}" -B hepmc3-build \
      -DCMAKE_INSTALL_PREFIX=${HEPMC3_DIR} \
      -DHEPMC3_ENABLE_ROOTIO=OFF -DHEPMC3_ENABLE_PYTHON=OFF \
      -DHEPMC3_BUILD_STATIC_LIBS=OFF -DHEPMC3_ENABLE_TEST=OFF \
      -DCMAKE_BUILD_TYPE=Release && \
    cmake --build hepmc3-build -j"$(nproc)" && cmake --install hepmc3-build && \
    rm -rf hepmc3-build "HepMC3-${HEPMC3_VERSION}"
ENV PATH=${HEPMC3_DIR}/bin:${PATH}
ENV LD_LIBRARY_PATH=${HEPMC3_DIR}/lib:${HEPMC3_DIR}/lib64:${LD_LIBRARY_PATH}

# --- Pythia 8 (configured against HepMC3 so Pythia8Plugins/HepMC3.h works) ---
ENV PYTHIA8_DIR=/opt/pythia8
# NB: the download path is /releases/pythia83/ (it 302-redirects, so wget must
# follow) -- /download/pythia83/ is a 404.
RUN wget -q --tries=5 --retry-connrefused --waitretry=20 --timeout=60 \
      --max-redirect=5 \
      "https://pythia.org/releases/pythia83/pythia${PYTHIA_VERSION}.tgz" \
      -O pythia.tgz && \
    tar -xzf pythia.tgz && rm pythia.tgz && \
    cd "pythia${PYTHIA_VERSION}" && \
    ./configure --prefix=${PYTHIA8_DIR} \
      --with-hepmc3=${HEPMC3_DIR} \
      --with-gzip && \
    make -j"$(nproc)" && make install && \
    cd /opt && rm -rf "pythia${PYTHIA_VERSION}"
ENV PATH=${PYTHIA8_DIR}/bin:${PATH}
ENV LD_LIBRARY_PATH=${PYTHIA8_DIR}/lib:${LD_LIBRARY_PATH}
# Pythia needs its data tables (particle data, PDF grids) at run time.
ENV PYTHIA8DATA=${PYTHIA8_DIR}/share/Pythia8/xmldoc

# Sanity: the toolchain must resolve and Pythia must find its data.
RUN test -f ${PYTHIA8DATA}/ParticleData.xml && \
    test -f ${PYTHIA8_DIR}/include/Pythia8Plugins/HepMC3.h && \
    ls ${PYTHIA8_DIR}/lib && ls ${HEPMC3_DIR}/lib*

WORKDIR /work
