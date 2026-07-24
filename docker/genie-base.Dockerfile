# GENIE base image for GDMLTargetPractice, built entirely from source so users
# never compile anything themselves. Provides gevgen/gmkspl/gntpc on PATH with
# the full dependency stack:
#
#   Pythia6 (via GENIE's own ext build script)
#   ROOT (compiled with Pythia6 + MathMore + GDML, batch-only)
#   LHAPDF 6
#   log4cpp / libxml2 / GSL (apt)
#   GENIE Generator (pinned release)
#
# Built by .github/workflows/build-generator-bases.yml (slow: ~2-3 h) and
# published as ghcr.io/<owner>/g4targetpractice-genie-base; the fast per-push
# genie app image (docker/genie.Dockerfile) layers gdmltp + the driver on top.
ARG UBUNTU=ubuntu:22.04
FROM ${UBUNTU}

ARG GENIE_VERSION=R-3_04_02
ARG ROOT_VERSION=6.28.12
ARG LHAPDF_VERSION=6.5.4

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gfortran cmake git wget curl ca-certificates \
    python3 python3-pip python3-dev \
    libgsl-dev libxml2-dev liblog4cpp5-dev \
    libpcre3-dev zlib1g-dev libbz2-dev liblzma-dev libzstd-dev \
    libssl-dev libffi-dev rsync \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt

# --- GENIE source first: its ext scripts build Pythia6 for us --------------
RUN git clone --branch ${GENIE_VERSION} --depth 1 \
      https://github.com/GENIE-MC/Generator.git /opt/genie

# --- Pythia6 (GENIE's canonical recipe) -------------------------------------
RUN mkdir -p /opt/pythia6 && cd /opt/pythia6 && \
    bash /opt/genie/src/scripts/build/ext/build_pythia6.sh 6.4.28 && \
    ls /opt/pythia6/v6_428/lib/libPythia6.so
ENV PYTHIA6=/opt/pythia6/v6_428
ENV PYTHIA6_LIB=/opt/pythia6/v6_428/lib

# --- ROOT with Pythia6 support (batch-only: no graphics, no PyROOT) --------
RUN wget -q https://root.cern/download/root_v${ROOT_VERSION}.source.tar.gz && \
    tar -xzf root_v${ROOT_VERSION}.source.tar.gz && rm root_v${ROOT_VERSION}.source.tar.gz && \
    mkdir root-build && cd root-build && \
    cmake ../root-${ROOT_VERSION} \
      -DCMAKE_BUILD_TYPE=Release \
      -DCMAKE_INSTALL_PREFIX=/opt/root \
      -Dpythia6=ON -DPYTHIA6_LIBRARY=${PYTHIA6_LIB}/libPythia6.so \
      -Dmathmore=ON -Dgdml=ON -Dminuit2=ON \
      -Dbuiltin_gsl=OFF \
      -Dx11=OFF -Dopengl=OFF -Dwebgui=OFF -Droot7=OFF \
      -Dxrootd=OFF -Ddavix=OFF -Dtmva=OFF -Droofit=OFF \
      -Dpyroot=OFF -Dpython=OFF \
      -Dfitsio=OFF -Dmysql=OFF -Dpgsql=OFF -Dsqlite=OFF -Ddcache=OFF \
      -Dimt=ON && \
    cmake --build . -j"$(nproc)" && cmake --install . && \
    cd /opt && rm -rf root-build root-${ROOT_VERSION}
ENV ROOTSYS=/opt/root
ENV PATH=${ROOTSYS}/bin:${PATH}
ENV LD_LIBRARY_PATH=${ROOTSYS}/lib:${PYTHIA6_LIB}

# --- LHAPDF 6 ----------------------------------------------------------------
RUN wget -q https://lhapdf.hepforge.org/downloads/?f=LHAPDF-${LHAPDF_VERSION}.tar.gz \
      -O LHAPDF-${LHAPDF_VERSION}.tar.gz && \
    tar -xzf LHAPDF-${LHAPDF_VERSION}.tar.gz && rm LHAPDF-${LHAPDF_VERSION}.tar.gz && \
    cd LHAPDF-${LHAPDF_VERSION} && \
    ./configure --prefix=/opt/lhapdf --disable-python && \
    make -j"$(nproc)" && make install && \
    cd /opt && rm -rf LHAPDF-${LHAPDF_VERSION}
ENV LHAPDF_DIR=/opt/lhapdf
ENV LD_LIBRARY_PATH=${LHAPDF_DIR}/lib:${LD_LIBRARY_PATH}
# lhapdf-config on PATH: APFEL's configure and `lhapdf install` both need it
# (APFEL aborts "LHAPDF cannot be found!" otherwise).
ENV PATH=${LHAPDF_DIR}/bin:${PATH}

# --- APFEL (OPTIONAL: only for HEDIS high-energy-DIS tunes) -------------------
# ENABLE_HEDIS=0 (default) builds nothing here and leaves the GENIE configure
# below byte-for-byte unchanged, so the proven default image is unaffected.
# ENABLE_HEDIS=1 additionally builds APFEL (needed for the NLO structure
# functions of the GHE19 tunes) -- see the multi-TeV neutrino examples.
ARG ENABLE_HEDIS=0
ARG APFEL_VERSION=3.0.6
RUN if [ "$ENABLE_HEDIS" = "1" ]; then \
      wget -q https://github.com/scarrazza/apfel/archive/refs/tags/${APFEL_VERSION}.tar.gz \
        -O apfel.tar.gz && tar -xzf apfel.tar.gz && rm apfel.tar.gz && \
      cd apfel-${APFEL_VERSION} && ./configure --prefix=/opt/apfel && \
      make -j"$(nproc)" && make install && cd /opt && rm -rf apfel-${APFEL_VERSION} ; \
    fi
ENV APFEL_DIR=/opt/apfel
ENV LD_LIBRARY_PATH=${APFEL_DIR}/lib:${LD_LIBRARY_PATH}
ENV PATH=${APFEL_DIR}/bin:${PATH}

# --- GENIE Generator ----------------------------------------------------------
# In-place build (the GENIE convention: $GENIE holds source, bin/ and lib/).
# The default G18 tunes use GENIE's native GRV98LO, so no external PDF data
# files are required at run time. With ENABLE_HEDIS=1, --enable-apfel is added
# so the high-energy-DIS (GHE19/HEDIS) tunes are available too.
ENV GENIE=/opt/genie
RUN cd ${GENIE} && \
    HEDIS_CFG="" && \
    if [ "$ENABLE_HEDIS" = "1" ]; then \
      HEDIS_CFG="--enable-apfel --with-apfel-inc=${APFEL_DIR}/include --with-apfel-lib=${APFEL_DIR}/lib" ; \
    fi && \
    ./configure \
      --enable-lhapdf6 \
      --with-lhapdf6-inc=${LHAPDF_DIR}/include \
      --with-lhapdf6-lib=${LHAPDF_DIR}/lib \
      --with-pythia6-lib=${PYTHIA6_LIB} \
      --with-log4cpp-inc=/usr/include \
      --with-log4cpp-lib=/usr/lib/x86_64-linux-gnu \
      --with-libxml2-inc=/usr/include/libxml2 \
      --with-libxml2-lib=/usr/lib/x86_64-linux-gnu \
      --enable-flux-drivers --enable-geom-drivers \
      --disable-profiler --disable-validation-tools --disable-doxygen-doc \
      ${HEDIS_CFG} && \
    make -j"$(nproc)" && \
    find ${GENIE} -name '*.o' -delete
ENV PATH=${GENIE}/bin:${PATH}
ENV LD_LIBRARY_PATH=${GENIE}/lib:${LD_LIBRARY_PATH}

# --- HEDIS inputs (OPTIONAL) -------------------------------------------------
# Bake in the LHAPDF grid + structure-function tables for the reference HEDIS
# tune so a HEDIS run needs no manual setup. Only runs when ENABLE_HEDIS=1.
ARG HEDIS_TUNE=GHE19_00a_00_000
ARG HEDIS_PDF=NNPDF31sx_nlo_as_0118_LHCb_nf_6
RUN if [ "$ENABLE_HEDIS" = "1" ]; then \
      lhapdf install ${HEDIS_PDF} && \
      gmkhedissf --tune ${HEDIS_TUNE} ; \
    fi
# Runtime marker: the gdmltp genie driver checks this before running gmkhedissf
# so a HEDIS tune on a non-HEDIS image fails with a clear message, not SIGABRT.
ENV GDMLTP_HEDIS=${ENABLE_HEDIS}

# Sanity: the generator toolchain must resolve.
RUN gevgen --help >/dev/null 2>&1 || gevgen -h >/dev/null 2>&1 || \
    ldd ${GENIE}/bin/gevgen

WORKDIR /work
