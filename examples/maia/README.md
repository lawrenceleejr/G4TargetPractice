# The neutrino slice at a muon collider, in MAIA

Example configs modeling **arXiv:2412.14115** ("The Neutrino Slice at Muon
Colliders"): muons decaying in the collider ring's final arcs and IP straight
(~30–100 m upstream) send an intense, ribbon-shaped neutrino flux through the
detector, confined to the plane of the ring. At √s = 10 TeV that's O(10¹¹)
neutrino interactions per year in the detector volume — mostly not in the
sensitive elements but in the machine-detector interface: **~79% in the
tungsten shielding nozzles**, 13% in the muon system, 7% in the HCal.

The target here is the real thing: `gdml/MAIA_v0.gdml`, the MAIA detector
concept export, whose detector body reaches ~±600 cm in each dimension.

**Injection geometry.** Rather than simulating the parent muons, these configs
**inject the neutrinos directly** as a *slice* that comes **from far upstream in
z** (the muon-decay straight sits many meters back) and flies downstream into
MAIA: a **multi-meter-wide ribbon in x** across the negative-x half, **very thin
in y** (x ∈ [−600, 0] cm, y ≈ 0 with a 5 mm spread, launched at z = −25 m).
The `geant4` backend transports the neutrinos from that source plane and the
biased interaction fires inside the detector. The vertex-only `genie`/`achilles`
backends place the interaction *at* the source point (25 m upstream) — the
interaction *kinematics* are unaffected, but to see the interactions **inside**
MAIA use `nu_slice_geant4_biased.yaml` or add `transport: true`. The neutrino
*energy* still follows the exact muon-decay spectrum (the physical origin of the
flux); only the spatial model is the direct-injection slice.

| Config | What it is |
|---|---|
| `nu_slice_numu.yaml` | νμ from the μ⁻ beam, Eμ = 5 TeV, sprayed across the negative-x ZX slice |
| `nu_slice_nuebar.yaml` | the ν̄e companion (one per μ⁻ decay), softer spectrum |
| `nu_slice_numubar_muplus.yaml` | ν̄μ from the counter-propagating μ⁺ beam (travels along −z) |
| `nu_slice_numu_3tev.yaml` | the √s = 3 TeV collider stage (Eμ = 1.5 TeV, wider fan) |
| `nu_slice_spectrum_only.yaml` | single fixed vertex in the slice, native gevgen spectral flux — for large-N spectrum studies |
| `nu_slice_geant4_biased.yaml` | the slice simulated **entirely in Geant4** with 1e10 neutrino biasing (guaranteed interaction + full transport) |
| `nu_slice_numu_hedis.yaml` | the TeV slice with GENIE's **HEDIS** high-energy-DIS tune (needs a HEDIS-provisioned image; see `docs/neutrino.md`) |
| `nu_slice_achilles.yaml` | the same slice through **Achilles** — a ~GeV muon-decay spectrum on ¹²C (Achilles is a GeV-scale theory generator, not TeV DIS); for a GENIE-vs-Achilles comparison on identical geometry |
| `hnl_decay.yaml` | a 1 GeV HNL decaying displaced inside MAIA — decayed **by Geant4** (`decay` backend; see `docs/bsm.md`) |

## The physics inputs

- **Energy spectra** are exact: the `mudecay_numu` / `mudecay_nue` energy modes
  sample the angle-integrated lab spectrum of neutrinos from in-flight muon
  decay (unpolarized), `dN/dy = 5/3 − 3y² + 4/3y³` (νμ/ν̄μ, ⟨E⟩ = 0.35 Eμ) and
  `2 − 6y² + 4y³` (νe/ν̄e, ⟨E⟩ = 0.30 Eμ), y = E/Eμ. With phase-space painting
  the host samples them into the per-event beam file; without it the genie
  backend hands gevgen the exact functional flux.
- **Slice geometry** is a direct-injection approximation (until geometry-aware
  vertex sampling lands): neutrinos launch from a source plane ~25 m upstream,
  spread over multiple meters in x (the negative-x half) and mm-thin in y,
  flying downstream with a ring-plane (x-z) crossing fan of the size the paper
  quotes (0.1°–2.5° at 10 TeV, 0.6°–6° at 3 TeV). Interaction *rates per
  component* are not reproduced — you choose the struck nucleus with
  `genie.target` (W-184 for the tungsten nozzles/shielding, which dominate the
  rate; switch to `1000260560` for iron/yoke studies).

## Honest caveats

- **First run is slow**: `cross_sections: auto` generates GENIE splines up to
  Eμ on demand (`gmkspl … -e 5000`) and caches them in the run directory —
  hours the first time for 5 TeV on tungsten, instant afterwards. **The HEDIS
  image now bakes the νμ-on-W-184 spline (to 5 TeV)**, so
  `nu_slice_numu_hedis.yaml` skips that wait entirely — verified by running
  `gevgen` off the baked file. Other probe/target/energy combinations still
  build on demand.
- **Achilles ≠ high energy**: `nu_slice_achilles.yaml` deliberately drops to a
  5 GeV muon source and a ¹²C target — Achilles models the ~GeV regime, not the
  TeV DIS the muon-collider slice actually lives in. It shares the *geometry*,
  not the energy scale, of the GENIE jobs.
- **Per-event replay is O(N)**: painted configs run one `gevgen` per event.
  Keep `run.events` modest; use `nu_slice_spectrum_only.yaml` for statistics.
- **TeV-scale GENIE**: the standard `G18_10a_00_000` tune extrapolates its DIS
  model above ~1 TeV. For precision TeV cross sections consider GENIE's HEDIS
  tunes via `genie.tune`.

## Workflow

```bash
gdmltp run --config examples/maia/nu_slice_numu.yaml   -o slice_numu
gdmltp run --config examples/maia/nu_slice_nuebar.yaml -o slice_nuebar

gdmltp validate slice_numu/output.root                 # schema + physics checks
gdmltp compare  slice_numu/output.root slice_nuebar/output.root \
                --labels numu,nuebar -o slice_cmp      # Q2/W/x/y overlays

# see the events inside MAIA (momentum rays for the vertex-level final state)
gdmltp display slice_numu/output.root --gdml gdml/MAIA_v0.gdml --events 0:20

# full detector response: add `transport: true` to the genie block and rerun --
# final-state particles are transported through MAIA by Geant4 and the file
# gains step_*/totalEdep on top of the GENIE interaction record.
```
