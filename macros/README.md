# Macro Files

This directory contains example Geant4 macro files that demonstrate how to
shoot beams of different particles at the simple detector geometries included
in the repository.

## Available GDML geometries

| File | Description |
|---|---|
| `gdml/silicon_slab_1mm.gdml` | 10×10 cm silicon slab, 1 mm thick, in a 10 cm air box |
| `gdml/liquid_argon_1m3.gdml` | 1 m³ liquid-argon cube in a 2 m³ air box |
| `gdml/water_phantom_30cm.gdml` | 30×30 cm water tank, 40 cm deep, entrance face at z = 0 |
| `gdml/tissue_phantom_layered.gdml` | Layered soft-tissue/bone/lung phantom (chest-wall analogue), entrance face at z = 0 |
| `gdml/water_phantom_tumor.gdml` | Water tank as above with a r = 1.5 cm soft-tissue tumor sphere at 10 cm depth |
| `gdml/dt_target_mucf.gdml` | Liquid D–T cell (0.18 g/cm³, 50:50, 20 K) in a 2 mm steel vessel, in vacuum; entrance face at z = 0 |
| `gdml/graphite_target.gdml` | 10×10×60 cm graphite pion-production target in vacuum, entrance face at z = 0 |
| `gdml/muon_capture_channel.gdml` | 2×2×30 cm graphite rod + 5 m vacuum decay channel + monitor plane (use with `/detector/setGlobalField`) |

## Macro overview

### Electron beams on the silicon slab

| Macro | Particle | Energy distribution |
|---|---|---|
| `electrons_silicon_mono.mac` | `e-` | Monoenergetic – 1 GeV |
| `electrons_silicon_gauss.mac` | `e-` | Gaussian – mean 1 GeV, σ = 200 MeV |
| `electrons_silicon_exp.mac` | `e-` | Exponential – E₀ = 1 GeV, sampled 100 MeV–5 GeV |
| `electrons_silicon_arb.mac` | `e-` | Arbitrary histogram (user-defined weights) |

### Neutrino beams on the liquid-argon target

| Macro | Particle | Energy distribution |
|---|---|---|
| `neutrinos_lar_mono.mac` | `nu_mu` | Monoenergetic – 2 GeV |
| `neutrinos_lar_gauss.mac` | `nu_mu` | Gaussian – mean 3 GeV, σ = 500 MeV |
| `neutrinos_lar_exp.mac` | `nu_mu` | Exponential – E₀ = 2 GeV, sampled 200 MeV–20 GeV |
| `neutrinos_lar_arb.mac` | `nu_mu` | Arbitrary histogram (accelerator-flux-like weights) |
| `electron_neutrinos_lar_mono.mac` | `nu_e` | Monoenergetic – 1 GeV |

### Medical physics examples

These macros shoot therapy-like beams at the water and layered-tissue
phantoms. Both phantoms have their entrance face at z = 0, so depth in the
phantom equals z and a depth-dose curve can be made directly from the
step-level branches of `output.root` (positions are in mm, energy deposits
in MeV), e.g. in ROOT:

```cpp
tree->Draw("step_z>>h(200,0,400)", "step_edep");
```

| Macro | Particle | Beam | Physics illustrated |
|---|---|---|---|
| `protons_water_bragg.mac` | `proton` | 150 MeV mono | Pristine Bragg peak at ~15.6 cm depth |
| `protons_water_sobp.mac` | `proton` | 110–150 MeV weighted bins | Crude spread-out Bragg peak (range modulation) |
| `electrons_water_20MeV.mac` | `e-` | 20 MeV mono | Electron build-up and ~10 cm practical range |
| `photons_water_6MV.mac` | `gamma` | exp spectrum, E₀ = 2 MeV, 0.25–6 MeV | 6 MV-like depth dose with ~1.5 cm build-up |
| `photons_water_co60.mac` | `gamma` | 1.17 + 1.33 MeV lines | Co-60 teletherapy beam |
| `photons_tissue_6MV.mac` | `gamma` | exp spectrum, E₀ = 2 MeV, 0.25–6 MeV | Heterogeneity effects in bone and lung |

All beams are pencil beams along +z starting at z = -20 cm. Note that if
you run with a Celeritas-enabled build (see the main README), offloaded
`e-`/`e+`/`gamma` tracks do not appear in the step-level output — for dose
studies use the standard image or set `CELER_DISABLE=1`.

### Muon-therapy studies with a tumor target

Muon-based therapy is an exploratory research topic: like protons, muons
have a Bragg peak, but a stopped `mu-` undergoes nuclear capture
(`muMinusCaptureAtRest`), releasing neutrons, gammas and nuclear fragments
that deposit extra dose at the end of range, while a stopped `mu+` decays
to a Michel positron (a proposed handle for in-vivo range verification).
These macros target `gdml/water_phantom_tumor.gdml`, where a 48 MeV muon
(or 117 MeV proton) stops at ~10 cm depth, inside the tumor sphere.

| Macro | Particle | Beam | What it shows |
|---|---|---|---|
| `muons_minus_tumor_mono.mac` | `mu-` | 48 MeV mono | Muon Bragg peak in the tumor + capture dose at end of range |
| `muons_minus_tumor_spread.mac` | `mu-` | 44–50 MeV weighted bins | Spread-out stopping region covering the whole tumor |
| `muons_plus_tumor_mono.mac` | `mu+` | 48 MeV mono | Decay (no capture) end-of-range; isolates the mu- capture contribution |
| `protons_tumor_mono.mac` | `proton` | 117 MeV mono | Same-range proton baseline for comparison |

The tumor sphere is centred on the beam axis at z = 100 mm with r = 15 mm,
so the energy deposited inside the tumor can be selected directly from the
step-level branches, e.g. total tumor energy deposit per event:

```cpp
tree->Draw("Sum$(step_edep*(sqrt(step_x*step_x+step_y*step_y+(step_z-100)*(step_z-100))<15))>>hTumor");
```

The per-step process names (`step_process`) and the per-track creator
process (`trk_creatorProcess`) let you separate capture products
(`muMinusCaptureAtRest`) from decay products (`Decay`) when comparing
`mu-` and `mu+` runs. Beam energies set the stopping depth — scan
`/gun/energy` by a few MeV to sweep the peak through the tumor. Muons are
never offloaded to Celeritas (only `e-`/`e+`/`gamma` are), but their EM
secondaries are, so the step-level caveat above applies to dose totals in
Celeritas builds here too.

### Muon-catalyzed fusion (μCF) chain

These macros follow the simulation pipeline of the SNS muon-catalyzed
fusion / Volumetric Neutron Source (VNS) concept presented at the
[New Science and Applications at SNS workshop](https://conference.sns.gov/event/559/page/4025-presentations)
(see in particular the talks by A. Lumsdaine on fusion requirements,
A. Knaian on the μCF collaborative proposal, and S. Tognini on muon
production and simulation): GeV protons → pions → muons → a liquid D–T
cell where each stopped `mu-` catalyzes ~10² fusions within its 2.2 μs
lifetime (capture-to-fusion time ~10⁻⁸ s, α-sticking loss ~1% per
cycle), each fusion releasing a 14.1 MeV neutron and a 3.5 MeV alpha.

| Macro | Stage | Beam / source |
|---|---|---|
| `protons_graphite_muonprod.mac` | 1. Production | 1.3 GeV protons on graphite; π±/μ± yields per proton from the per-track table (e.g. `Sum$(trk_pdg==211)`) |
| `protons_capture_channel.mac` | 1b. Capture + decay channel | 1.3 GeV protons on a thin rod inside a 5 T solenoid field; pions spiral down a 5 m decay channel and deliver muons to a monitor plane |
| `muons_dt_mucf_stopping.mac` | 2. Muon stopping | 22 ± 1.5 MeV `mu-` through the steel window, stopping at ~7 cm depth in the D–T |
| `muons_dt_energy_scan.mac` | 2b. Beam design | Comb of 14–34 MeV `mu-` energies in one run; plot `primaryEndZ` vs `primaryE` to map which energies cross the window and stop inside the D–T |
| `neutrons_dt_14MeV.mac` | 3a. Fusion neutrons | isotropic 14.1 MeV neutrons from the stopping region (neutronics/shielding) |
| `alphas_dt_3p5MeV.mac` | 3b. Fusion alphas | isotropic 3.5 MeV alphas from the stopping region (local heating; sticking context) |

**What Geant4 does and does not model.** Stock Geant4 (this
application) covers everything *around* the catalysis cycle: pion/muon
production, muon transport and stopping, the decay/nuclear-capture fate
of stopped muons (`muMinusCaptureAtRest`), and transport of the fusion
products. It does **not** model the μCF cycle itself — muonic-atom
formation, `d-mu → t-mu` transfer, resonant `dt-mu` molecule formation,
in-molecule fusion and α-sticking are low-energy atomic/molecular
physics outside the standard physics lists. The supported workflow here
is parametric: take the stopped-muon distribution from stage 2, apply a
cycle model (e.g. ~10² fusions per stopped muon at liquid-hydrogen
density), and source the products with the stage-3 macros; the absolute
source rate is (n per μ) × (μ per bunch) × (bunches per s). Groups that
need the cycle in-line extend Geant4 with custom at-rest models (the
approach used by Acceleron Fusion), and Celeritas has a native μCF
executor under development (muonic atom → molecule → DD/DT/TT cycle),
which this repository's `WITH_CELERITAS` build option is well placed to
adopt once released.

**Matching the beam to the cell.** For the default geometry (2 mm
stainless window ≈ 1.6 g/cm², D–T rear face at ≈ 5.2 g/cm²) the
acceptance window is roughly **16–31 MeV kinetic energy (≈ 60–90
MeV/c)**: below it muons stop in the window, above it they punch
through the cell. This is decay-channel muon territory — 29.8 MeV/c
"surface" muons (4.1 MeV, and μ⁺ only) would stop in the first
~0.2 mm of steel, so a μ⁻ beam for μCF is necessarily a decay beam.
Run `muons_dt_energy_scan.mac` to map the window precisely for any
edited geometry; the stopping-region length is dominated by the beam
momentum spread (≈ 1.8 cm per MeV at these energies), with muon range
straggling adding ~0.5 cm.

**Understanding the muon production.** Muons are tertiary: protons make
pions in the target, and the muons come from `pi+ -> mu+ nu` (26 ns
lifetime, cτ = 7.8 m, so decay mostly happens in flight along the
channel) while most π⁻ that stop in material are nuclear-captured
instead of decaying. `protons_graphite_muonprod.mac` quantifies the
first step — π±/μ± yields per proton on target by counting tracks in the
per-track table (e.g. `Sum$(trk_pdg==211)`). The capture-channel macro
adds the transport: a uniform solenoid field
(`/detector/setGlobalField 0 0 5 tesla`) confines pions with
p⊥ ≲ 0.3·B·r into helices so they survive to decay, and the monitor
plane 5 m downstream tags the delivered muons. The per-track table
(`trk_*`) already has one row per particle, so selections are direct
(mm/MeV units):

```cpp
// pi+ production spectrum at birth
tree->Draw("trk_startE", "trk_pdg==211");
// muon flux and spectrum at the monitor plane
tree->Draw("step_kinE", "abs(step_pdg)==13 && step_z>5300 && step_z<5310");
// pi -> mu decay vertices along the channel
tree->Draw("trk_startZ", "abs(trk_pdg)==13");
```

Rerun with the field set to zero to measure the capture gain. (In
Celeritas-enabled builds, set `CELER_DISABLE=1` when a field is on —
the offload assumes zero field for e±/γ; muons and pions are
unaffected.)

**Multi-parameter scans.** `scans/mucf_scan.sh` (shipped in the Docker
images at `/app/scans/mucf_scan.sh`) scans beam energy, D:T atomic
ratio, density (relative to liquid-hydrogen atom density) and window
thickness in one go — it generates a D–T cell GDML and a macro per
point, runs `g4sim`, and writes one ROOT file per point plus a
`summary.csv` with the fraction of muons stopped inside the D–T and
the mean stopping depth. On any machine with Docker:

```bash
docker run --rm -v "$PWD":/work -w /work \
  -e ENERGIES="14 16 18 20 22 24 26 28 30 32 34" -e DFRACS="0.3 0.5 0.7" \
  --entrypoint bash ghcr.io/lawrenceleejr/g4targetpractice:main \
  /app/scans/mucf_scan.sh
```

Results land in `./scan_results/`. Other knobs: `PHI` (density),
`WINDOW_MM` (steel wall thickness), `NEVENTS`, `PARTICLE`.

## How to run a macro

From the build directory run the simulation executable with the `-m` flag:

```bash
./g4sim -m /path/to/macros/electrons_silicon_mono.mac
```

The geometry path in each macro is relative to the directory from which the
executable is launched, so run from the repository root or adjust the
`/detector/readGDML` path accordingly.

## Gun commands reference

The following `/gun/` commands are available for configuring the primary
particle source:

| Command | Argument(s) | Description |
|---|---|---|
| `/gun/particle` | name | Particle type (e.g. `e-`, `nu_mu`, `nu_e`) |
| `/gun/energy` | value unit | Nominal energy (mean for `gauss`, E₀ for `exp`) |
| `/gun/position` | x y z unit | Start position of the particle |
| `/gun/direction` | x y z | Beam direction (unit vector). Use `0 0 0` for isotropic 4π. |
| `/gun/energyMode` | `mono`\|`gauss`\|`exp`\|`arb` | Energy sampling mode |
| `/gun/gaussSigma` | value unit | σ for Gaussian mode |
| `/gun/energyMin` | value unit | Lower energy bound for `exp` and `arb` modes |
| `/gun/energyMax` | value unit | Upper energy bound for `exp` mode |
| `/gun/addEnergyBin` | energy unit weight | Add a bin to the arbitrary histogram |
| `/gun/clearEnergyBins` | _(none)_ | Clear all histogram bins |

### Energy modes explained

- **`mono`** – every event fires at exactly `/gun/energy`.
- **`gauss`** – energies are drawn from a Gaussian with mean `/gun/energy` and
  sigma `/gun/gaussSigma`. Non-positive values are rejected and resampled.
- **`exp`** – energies are drawn from an exponential PDF
  *f(E) ∝ exp(−E/E₀)* where *E₀* = `/gun/energy`, sampled in the interval
  [`/gun/energyMin`, `/gun/energyMax`] using the exact inverse-CDF method.
- **`arb`** – a discrete histogram defined by one or more `/gun/addEnergyBin`
  calls. Each bin carries a representative energy and a relative weight; the
  generator picks a bin according to the weights and fires at that energy.

### Adding custom bins for the `arb` mode

```
/gun/clearEnergyBins
/gun/addEnergyBin  500 MeV 1.0
/gun/addEnergyBin    1 GeV 3.0
/gun/addEnergyBin    5 GeV 1.5
```

Weights are normalised automatically; they represent relative probabilities.

## Output ntuple

Each run writes `output.root` containing a TTree `tree` with one entry per
event, organised as three clear collections (positions in mm, energies in
MeV, momenta in MeV/c). Momentum components are stored directly; angles are
derived trivially in analysis (e.g. `atan2(primaryStartPy, primaryStartPx)`).

**Event scalars** (one value per event):

| Branch | Meaning |
|---|---|
| `eventID` | event number |
| `primaryPDG` | PDG code of the primary particle |
| `primaryE` | primary initial kinetic energy |
| `primaryStartX/Y/Z` | primary start position |
| `primaryStartPx/Py/Pz` | primary initial momentum |
| `primaryEndE` | primary final kinetic energy (≈0 ⇒ it stopped) |
| `primaryEndX/Y/Z` | primary end (e.g. Bragg-stop) position |
| `primaryEndPx/Py/Pz` | primary final momentum |
| `totalEdep` | total energy deposited in the event |
| `nSteps` | number of recorded steps |
| `nTracks` | number of tracks |

**Per-track vectors `trk_*`** (one entry per track — primaries and
secondaries; a track's start position is its production vertex, and
`trk_parentID` links the decay/interaction tree):

| Branch | Meaning |
|---|---|
| `trk_id`, `trk_parentID`, `trk_pdg` | track id, parent id, PDG code |
| `trk_startX/Y/Z`, `trk_startE` | production vertex position and kinetic energy |
| `trk_endX/Y/Z`, `trk_endE` | end position and final kinetic energy |
| `trk_creatorProcess` | process that created the track (`Primary` for primaries) |
| `trk_edep`, `trk_length` | summed energy deposit and path length over the track |

The track table replaces fixed per-particle counters — count by PDG, e.g.
`tree->Draw("Sum$(trk_pdg==13)")` for μ⁻ per event.

**Per-step vectors `step_*`** (one entry per step of every track; the
pre-step position is where the step's energy deposit is registered):

| Branch | Meaning |
|---|---|
| `step_trackID`, `step_pdg` | owning track id and PDG code |
| `step_x/y/z` | pre-step position |
| `step_kinE` | pre-step kinetic energy |
| `step_edep`, `step_length`, `step_time` | energy deposit, step length, global time |
| `step_process` | process limiting the step |

## Neutrino mode

When the primary is a neutrino the ntuple additionally emits a clean
`nu_*` block identifying and categorising the interaction. It is controlled
by `/analysis/neutrinoMode` (issue before `/run/beamOn`):

| Value | Effect |
|---|---|
| `auto` (default) | enable `nu_*` when the primary is a neutrino (`nu_e/nu_mu/nu_tau`) |
| `on` | always emit `nu_*` |
| `off` | never emit `nu_*` |

`nu_*` branches: `nu_isCC`, `nu_isNC` (charged- vs neutral-current, from the
outgoing lepton), `nu_interactionProcess` (the Geant4 process that caused the
interaction — the categorization), `nu_vertexX/Y/Z/T` (interaction vertex),
`nu_targetZ`/`nu_targetA` (struck nucleus), `nu_outLeptonPDG/E/Px/Py/Pz`
(outgoing lepton), and the derived kinematics `nu_Q2`, `nu_W`, `nu_x`
(Bjorken x), `nu_y`, `nu_q0`. The neutrino macros (`neutrinos_lar_*.mac`,
`electron_neutrinos_lar_mono.mac`) enable it explicitly. Example analysis:

```cpp
// charged-current fraction
tree->Draw("nu_isCC");
// which process caused each interaction
tree->Draw("nu_interactionProcess");
// Q^2 of charged-current events
tree->Draw("nu_Q2", "nu_isCC");
```
