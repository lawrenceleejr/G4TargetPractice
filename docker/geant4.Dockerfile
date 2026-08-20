# Standard (transport) Geant4 image for GDMLTargetPractice.
# Previously defined as a heredoc inside build-test-deploy.yml; now a checked-in
# file so it can be built and reviewed directly.
ARG BASE=ghcr.io/lawrenceleejr/root-geant4-garfield:cpp17_root-v6-26-10_geant4-v11.4.1_garfield-e0a9f171
FROM ${BASE}

WORKDIR /app

# Qt6 runtime libraries required by the Geant4 visualization drivers
RUN apt-get update && apt-get install -y --no-install-recommends \
    libqt6core6 libqt6gui6 libqt6widgets6 libqt6opengl6 \
    && rm -rf /var/lib/apt/lists/*

# HepMC3: the standard generator->Geant4 interchange the hand-off reads. Built
# from source (pinned) so g4sim links the real library rather than parsing a
# bespoke format. Header + ASCII reader only; no ROOT/Python components needed.
ARG HEPMC3_VERSION=3.3.0
RUN apt-get update && apt-get install -y --no-install-recommends cmake g++ make wget ca-certificates && \
    wget -q --tries=5 --retry-connrefused --waitretry=20 --timeout=30 \
        --retry-on-http-error=429,500,502,503,504 \
        https://gitlab.cern.ch/hepmc/HepMC3/-/archive/${HEPMC3_VERSION}/HepMC3-${HEPMC3_VERSION}.tar.gz && \
    tar xzf HepMC3-${HEPMC3_VERSION}.tar.gz && \
    cmake -S HepMC3-${HEPMC3_VERSION} -B hepmc3-build \
        -DCMAKE_INSTALL_PREFIX=/usr/local \
        -DHEPMC3_ENABLE_PYTHON=OFF -DHEPMC3_ENABLE_ROOTIO=OFF \
        -DHEPMC3_ENABLE_TEST=OFF -DHEPMC3_BUILD_EXAMPLES=OFF && \
    cmake --build hepmc3-build --target install -j"$(nproc)" && \
    ldconfig && \
    rm -rf HepMC3-${HEPMC3_VERSION}* hepmc3-build /var/lib/apt/lists/*

# Build the g4sim engine
COPY g4sim/ /app/g4sim/
RUN mkdir -p /app/build && cd /app/build && cmake /app/g4sim/ && cmake --build .

# Parameter-scan helper scripts (run with --entrypoint bash)
COPY scans/ /app/scans/
RUN if [ -f /usr/lib/x86_64-linux-gnu/libQt5Core.so.5 ]; then strip --remove-section=.note.ABI-tag /usr/lib/x86_64-linux-gnu/libQt5Core.so.5; fi
RUN if [ -f /lib/x86_64-linux-gnu/libQt6Core.so.6 ]; then strip --remove-section=.note.ABI-tag /lib/x86_64-linux-gnu/libQt6Core.so.6; fi

# gdmltp tooling: config frontend + analysis + event display (pure Python, no ROOT).
# The [geometry] extra pulls in pyg4ometry so the in-image display uses the
# standard GDML reader (accurate solids + mesh bounding boxes). Both the gdmltp
# package and the deprecated g4tp shim are installed.
RUN python3 -m pip install --no-cache-dir --upgrade pip setuptools wheel && \
    python3 -m pip install --no-cache-dir uproot awkward numpy matplotlib pyyaml
COPY gdmltp/ /app/pysrc/gdmltp/
COPY g4tp/ /app/pysrc/g4tp/
COPY pyproject.toml README.md /app/pysrc/
RUN python3 -m pip install --no-cache-dir "/app/pysrc[geometry]" && \
    python3 -c "import gdmltp, pyg4ometry, pyhepmc; from gdmltp import handoff; from gdmltp.backends import genie_convert, achilles_convert; print('gdmltp', gdmltp.__version__, 'pyhepmc', pyhepmc.__version__)"

COPY g4sim/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Dispatcher entrypoint: *.mac -> g4sim, *.json -> genie driver, else -> gdmltp
ENTRYPOINT ["/app/entrypoint.sh"]
