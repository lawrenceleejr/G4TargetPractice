# G4TargetPractice

A general-purpose Geant4 simulation tool that lets you run particle transport through any detector geometry described in GDML format, driven entirely by a Geant4 macro file. No local Geant4 installation required — just Docker.

## Quick Start with Docker

Pre-built images are available at:
**`ghcr.io/lawrenceleejr/g4targetpractice`**

These images include Geant4 (with GDML and ROOT support) and the compiled `g4sim` executable. They are built, tested, and deployed automatically via GitHub Actions.

### What you need

1. **Docker** (or Podman) installed and running
2. A **GDML file** describing your detector geometry
3. A **Geant4 macro file** (`.mac`) configuring your particle gun and run settings

### Running a simulation

Place your GDML file and macro file in a local directory (e.g. `myrun/`), then run:

```bash
docker run --rm -it --init \
  -v $PWD/myrun/:/run/ \
  -w /run/ \
  ghcr.io/lawrenceleejr/g4targetpractice:main \
  run.mac
```

This mounts your local `myrun/` directory as `/run/` inside the container, sets it as the working directory, and runs the simulation using your `run.mac` macro. Output files (e.g. `output.root`) are written back to your local `myrun/` directory.

### Example macro (`run.mac`)

```
# Load your GDML geometry
/detector/readGDML my_detector.gdml

# Configure the particle gun
/gun/particle e-
/gun/energy 10 GeV
/gun/position 0 0 -50 cm
/gun/direction 0 0 1

# Initialize and run
/run/initialize
/run/printProgress 100
/run/beamOn 1000
```

The `/detector/readGDML` command takes a path relative to the working directory inside the container (i.e. relative to where you mounted your files). Geant4 standard `/gun/` commands are used to configure the particle gun — any particle in the Geant4 particle table is supported. A uniform magnetic field over the whole geometry (e.g. a capture solenoid) can be set after `/run/initialize` with `/detector/setGlobalField 0 0 5 tesla` (a zero vector disables it; with Celeritas-enabled builds set `CELER_DISABLE=1` when using a field).

### Supported particles

Any particle available in the Geant4 particle table can be used, including:
`e-`, `e+`, `gamma`, `proton`, `neutron`, `mu-`, `mu+`, `pi+`, `pi-`, `pi0`, `kaon+`, `nu_mu`, and many more.

### Output

Each run produces an `output.root` file in the working directory containing a ROOT TTree (`tree`) with per-event kinematic and hit information for the primary particle and secondaries.

---

## Repository Structure

```
G4TargetPractice/
├── g4sim/                   # Geant4 simulation source code
│   ├── CMakeLists.txt
│   ├── main.cc
│   ├── DetectorConstruction.cc/hh   # GDML-based geometry loader
│   ├── PrimaryGenerator.cc/hh       # Particle gun with macro control
│   ├── RunAction.cc/hh              # ROOT output file/tree
│   ├── EventAction.cc/hh            # Per-event data collection
│   ├── SteppingAction.cc/hh         # Per-step data collection
│   ├── simple_det.gdml              # Minimal example GDML (kept for reference)
│   └── run_ci.mac                   # Macro used for CI testing
├── gdml/                    # Example GDML geometry files
│   ├── MAIA_v0.gdml         # MAIA detector geometry
│   ├── silicon_slab_1mm.gdml        # 1 mm silicon slab
│   ├── liquid_argon_1m3.gdml        # 1 m³ liquid argon volume
│   ├── water_phantom_30cm.gdml      # Water phantom (medical physics)
│   ├── tissue_phantom_layered.gdml  # Tissue/bone/lung phantom (medical physics)
│   ├── water_phantom_tumor.gdml     # Water phantom with tumor sphere (muon therapy)
│   ├── dt_target_mucf.gdml          # Liquid D-T cell (muon-catalyzed fusion)
│   └── graphite_target.gdml         # Pion/muon production target
├── macros/                  # Example macros (HEP + medical physics), see macros/README.md
├── scans/                   # Parameter-scan scripts (baked into the Docker images)
│   └── mucf_scan.sh         # Muon energy / D:T ratio / density / window scan
├── run/                     # Example user run directory
│   ├── run.mac              # Example macro file
│   └── MAIA_260211.gdml     # Example GDML geometry
├── .github/workflows/
│   ├── build-test-deploy.yml       # CI: build, test, push Docker image
│   └── build-celeritas-deploy.yml  # CI: build, test, push Celeritas-enabled image
├── Dockerfile               # Alternative standalone Dockerfile
├── .gitignore
└── README.md
```

---

## Building from Source

If you need to build locally (requires Geant4 ≥ 11 with GDML support and ROOT):

```bash
mkdir build
cd build
cmake ../g4sim/
cmake --build .
```

Then run from the repository root:

```bash
./build/g4sim g4sim/run_ci.mac
```

Or with your own macro:

```bash
./build/g4sim /path/to/your/run.mac
```

## Docker Images

Images are built automatically on every push and are available at:

```
ghcr.io/lawrenceleejr/g4targetpractice:<tag>
```

| Tag | Description |
|-----|-------------|
| `main` | Latest stable build from the `main` branch |
| `latest` | Alias for the default branch |
| `<branch>-<sha>` | Per-commit image |
| `main-celeritas` / `latest-celeritas` | Build with the Celeritas EM offload enabled (CPU-only) |
| `<branch>-celeritas`, `<branch>-<sha>-celeritas` | Per-branch/per-commit Celeritas builds |

The images are based on `ghcr.io/lobis/root-geant4-garfield` which provides a pre-built Geant4 + ROOT environment. The `*-celeritas` tags are produced by a separate workflow (`build-celeritas-deploy.yml`) that additionally builds [Celeritas](https://celeritas-project.github.io/celeritas/) and compiles `g4sim` with `-DWITH_CELERITAS=ON`; see the Celeritas section below.

## Physics

The simulation uses the `FTFP_BERT` reference physics list by default, which covers hadronic and electromagnetic physics appropriate for most HEP detector studies. The physics list can be extended via the macro or by modifying the source.

## Optional: Celeritas EM Offload

[Celeritas](https://celeritas-project.github.io/celeritas/) can take over the transport of electromagnetic tracks (`e-`, `e+`, `gamma`), running them on GPU (or multithreaded on CPU) instead of through the standard Geant4 stepping loop. This can substantially speed up EM-heavy simulations.

Support is a **build-time option**, off by default, so standard builds and the default Docker images are unaffected.

### Pre-built Celeritas image

A CPU-only Celeritas-enabled image is built and pushed automatically with a `-celeritas` tag suffix:

```bash
docker run --rm -it --init \
  -v $PWD/myrun/:/run/ \
  -w /run/ \
  ghcr.io/lawrenceleejr/g4targetpractice:main-celeritas \
  run.mac
```

### Building with Celeritas

Requirements: Celeritas **v0.6 or newer**, built with Geant4 support (`CELERITAS_USE_Geant4=ON`) against the same Geant4 installation used for `g4sim`.

```bash
mkdir build
cd build
cmake ../g4sim/ -DWITH_CELERITAS=ON -DCMAKE_PREFIX_PATH=/path/to/celeritas-install
cmake --build .
```

The standalone `Dockerfile` can also build a (CPU-only) Celeritas alongside Geant4:

```bash
docker build --build-arg WITH_CELERITAS=ON -t g4tp-celeritas .
```

then configure `g4sim` inside that image with `-DWITH_CELERITAS=ON`.

### Enabling/disabling at runtime

When compiled with `WITH_CELERITAS=ON`, the offload is **enabled by default**: all `e-`, `e+`, and `gamma` tracks are handed to Celeritas at the start of tracking. It can be controlled with standard Celeritas environment variables:

| Environment variable | Effect |
|----------------------|--------|
| `CELER_DISABLE=1` | Disable the offload entirely; tracks are transported by Geant4 as usual |
| `CELER_KILL_OFFLOAD=1` | Kill EM tracks instead of transporting them (for performance testing) |

For example, with Docker:

```bash
docker run --rm -it --init -e CELER_DISABLE=1 ...
```

### Caveat: step-level output

`g4sim` fills its ROOT tree from a Geant4 stepping action. Tracks transported by Celeritas do not pass through the Geant4 stepping loop, so **steps and energy deposition from offloaded EM tracks will not appear in the step-level branches of `output.root`**. If you need complete step records for EM particles, run with `CELER_DISABLE=1`.

