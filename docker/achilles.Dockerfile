# Achilles backend image for GDMLTargetPractice.
#
# The base image must provide a working Achilles install (the `achilles` binary
# on PATH with its data files) plus its deps (HepMC3, fmt, yaml-cpp). The
# Achilles repository ships a Dockerfile; build/pin a base from it (or point at
# a published image) via:  docker build --build-arg ACHILLES_BASE=<image> ...
ARG ACHILLES_BASE=ghcr.io/achillesgen/achilles:main
FROM ${ACHILLES_BASE}

WORKDIR /app

# Python tooling: the NuHepMC -> output.root converter and the gdmltp analysis
# suite (pure Python: uproot/awkward/numpy/matplotlib/pyyaml -- no HepMC3 needed).
RUN python3 -m pip install --no-cache-dir uproot awkward numpy matplotlib pyyaml \
    || pip3 install --no-cache-dir uproot awkward numpy matplotlib pyyaml
COPY gdmltp/ /app/pysrc/gdmltp/
COPY g4tp/ /app/pysrc/g4tp/
COPY pyproject.toml README.md /app/pysrc/
RUN python3 -m pip install --no-cache-dir /app/pysrc \
    || pip3 install --no-cache-dir /app/pysrc

# Achilles driver (reads achilles_job.json, renders the run card, runs achilles,
# converts NuHepMC -> output.root).
COPY achilles/ /app/achilles/

# Shared argument-shape dispatcher: *.json -> the resident driver, else -> gdmltp.
COPY g4sim/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh /app/achilles/*.py
ENTRYPOINT ["/app/entrypoint.sh"]
