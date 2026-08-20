# Pythia 8 backend image for GDMLTargetPractice.
#
# The base image provides Pythia 8 (built against HepMC3) and HepMC3 itself;
# this layer adds the gdmltp python package, the pythia driver, and compiles the
# small pythia_gen generator (Pythia8 -> HepMC3 ASCII).
ARG PYTHIA_BASE=ghcr.io/lawrenceleejr/gdmltargetpractice-pythia-base:latest
FROM ${PYTHIA_BASE}

WORKDIR /app

# Python tooling: the HepMC3 -> output.root converter and the gdmltp analysis
# suite. pyhepmc gives the converter the official HepMC3 reader.
RUN python3 -m pip install --no-cache-dir --upgrade pip setuptools wheel && \
    python3 -m pip install --no-cache-dir uproot awkward numpy matplotlib pyyaml pyhepmc
COPY gdmltp/ /app/pysrc/gdmltp/
COPY g4tp/ /app/pysrc/g4tp/
COPY pyproject.toml README.md /app/pysrc/
RUN python3 -m pip install --no-cache-dir /app/pysrc && \
    python3 -c "import gdmltp; from gdmltp.backends import achilles_convert, pythia; print('gdmltp', gdmltp.__version__)"

# Pythia driver + the generator binary it shells out to.
COPY pythia/ /app/pythia/
RUN g++ -O2 -std=c++17 -o /usr/local/bin/pythia_gen /app/pythia/pythia_gen.cc \
      -I${PYTHIA8_DIR}/include -I${HEPMC3_DIR}/include \
      -L${PYTHIA8_DIR}/lib -lpythia8 \
      -L${HEPMC3_DIR}/lib -L${HEPMC3_DIR}/lib64 -lHepMC3 \
      -Wl,-rpath,${PYTHIA8_DIR}/lib -Wl,-rpath,${HEPMC3_DIR}/lib -Wl,-rpath,${HEPMC3_DIR}/lib64 && \
    pythia_gen 2>&1 | grep -q usage && echo "pythia_gen built" && \
    ! ldd /usr/local/bin/pythia_gen | grep "not found"

# Shared argument-shape dispatcher: *.json -> the resident driver, else -> gdmltp.
COPY g4sim/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh /app/pythia/*.py
ENTRYPOINT ["/app/entrypoint.sh"]
