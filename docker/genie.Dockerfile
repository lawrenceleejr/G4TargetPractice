# GENIE backend image for GDMLTargetPractice.
#
# The base image must provide a working GENIE Generator install (gevgen, gntpc
# on PATH; $GENIE set) together with its dependency stack (ROOT, Pythia6,
# LHAPDF, log4cpp, GSL). Building GENIE from source is heavy and version-
# sensitive, so we start FROM a maintained GENIE image and only layer in the
# Python tooling + driver.
#
# Override the base with:  docker build --build-arg GENIE_BASE=<image> ...
# The exact tag is intentionally a build arg (the CI workflow sets it) so the
# maintainer can point at the GENIE build/tune they trust.
ARG GENIE_BASE=ghcr.io/lawrenceleejr/gdmltargetpractice-genie-base:latest
FROM ${GENIE_BASE}

WORKDIR /app

# Python tooling: the gst -> output.root converter and the gdmltp analysis suite
# (pure Python: uproot/awkward/numpy/matplotlib/pyyaml -- no ROOT needed here).
RUN python3 -m pip install --no-cache-dir --upgrade pip setuptools wheel && \
    python3 -m pip install --no-cache-dir uproot awkward numpy matplotlib pyyaml
COPY gdmltp/ /app/pysrc/gdmltp/
COPY g4tp/ /app/pysrc/g4tp/
COPY pyproject.toml README.md /app/pysrc/
RUN python3 -m pip install --no-cache-dir /app/pysrc && \
    python3 -c "import gdmltp; from gdmltp.backends import genie_convert, achilles_convert; print('gdmltp', gdmltp.__version__)"

# GENIE driver (reads genie_job.json, runs gevgen -> gntpc -> genie2root).
COPY genie/ /app/genie/

# Pre-built cross-section splines for the shipped neutrino targets, baked in so
# runs are fast and reproducible. Provide them via the base image or add here,
# and point $GENIE_XSEC_FILE at the XML; the driver falls back to this env var
# when the job's cross_sections is "auto".
#   COPY splines/gxspl-shipped.xml /opt/genie-splines/gxspl.xml
#   ENV GENIE_XSEC_FILE=/opt/genie-splines/gxspl.xml

# Shared argument-shape dispatcher: *.json -> the GENIE driver, else -> gdmltp.
COPY g4sim/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh /app/genie/*.py
ENTRYPOINT ["/app/entrypoint.sh"]
