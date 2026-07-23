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

# Build the g4sim engine
COPY g4sim/ /app/g4sim/
RUN mkdir -p /app/build && cd /app/build && cmake /app/g4sim/ && cmake --build .

# Parameter-scan helper scripts (run with --entrypoint bash)
COPY scans/ /app/scans/
RUN if [ -f /usr/lib/x86_64-linux-gnu/libQt5Core.so.5 ]; then strip --remove-section=.note.ABI-tag /usr/lib/x86_64-linux-gnu/libQt5Core.so.5; fi
RUN if [ -f /lib/x86_64-linux-gnu/libQt6Core.so.6 ]; then strip --remove-section=.note.ABI-tag /lib/x86_64-linux-gnu/libQt6Core.so.6; fi

# gdmltp tooling: config frontend + analysis + event display (pure Python, no ROOT).
# Both the gdmltp package and the deprecated g4tp shim are installed.
RUN python3 -m pip install --no-cache-dir uproot awkward numpy matplotlib pyyaml \
    || pip3 install --no-cache-dir uproot awkward numpy matplotlib pyyaml
COPY gdmltp/ /app/pysrc/gdmltp/
COPY g4tp/ /app/pysrc/g4tp/
COPY pyproject.toml README.md /app/pysrc/
RUN python3 -m pip install --no-cache-dir /app/pysrc || pip3 install --no-cache-dir /app/pysrc

COPY g4sim/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Dispatcher entrypoint: *.mac -> g4sim, *.json -> genie driver, else -> gdmltp
ENTRYPOINT ["/app/entrypoint.sh"]
