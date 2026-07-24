# The neutrino slice at a muon collider, in MAIA

Example configs modeling **arXiv:2412.14115** ("The Neutrino Slice at Muon
Colliders"): muons decaying in the collider ring's final arcs and IP straight
(~30–100 m upstream) send an intense, ribbon-shaped neutrino flux through the
detector, confined to the plane of the ring. At √s = 10 TeV that's O(10¹¹)
neutrino interactions per year in the detector volume — mostly not in the
sensitive elements but in the machine-detector interface: **~79% in the
tungsten shielding nozzles**, 13% in the muon system, 7% in the HCal.

The target here is the real thing: `gdml/MAIA_v0.gdml`, the MAIA detector
concept export, whose tungsten nozzles span z = 6–595 cm with outer radius
growing to 43 cm.

| Config | What it is |
|---|---|
| `nu_slice_numu.yaml` | νμ from the μ⁻ beam, Eμ = 5 TeV, vertices painted in the +z nozzle |
| `nu_slice_nuebar.yaml` | the ν̄e companion (one per μ⁻ decay), softer spectrum |
| `nu_slice_numubar_muplus.yaml` | ν̄μ from the counter-propagating μ⁺ beam (−z nozzle) |
| `nu_slice_numu_3tev.yaml` | the √s = 3 TeV collider stage (Eμ = 1.5 TeV, wider fan) |
| `nu_slice_spectrum_only.yaml` | fixed vertex, native gevgen spectral flux — for large-N spectrum studies |

## The physics inputs

- **Energy spectra** are exact: the `mudecay_numu` / `mudecay_nue` energy modes
  sample the angle-integrated lab spectrum of neutrinos from in-flight muon
  decay (unpolarized), `dN/dy = 5/3 − 3y² + 4/3y³` (νμ/ν̄μ, ⟨E⟩ = 0.35 Eμ) and
  `2 − 6y² + 4y³` (νe/ν̄e, ⟨E⟩ = 0.30 Eμ), y = E/Eμ. With phase-space painting
  the host samples them into the per-event beam file; without it the genie
  backend hands gevgen the exact functional flux.
- **Slice geometry** is an explicit approximation (until geometry-aware vertex
  sampling lands): vertices are painted uniformly along the nozzle, mm-thin
  vertically (θν ~ 1/γμ over the 30–100 m baseline), with ring-plane crossing
  angles of the size the paper quotes (0.1°–2.5° at 10 TeV, 0.6°–6° at 3 TeV).
  Interaction *rates per component* are not reproduced — you choose where to
  aim; `genie.target` picks the struck nucleus (W-184 for the nozzles; switch
  to `1000260560` for iron/yoke studies).

## Honest caveats

- **First run is slow**: `cross_sections: auto` generates GENIE splines up to
  Eμ on demand (`gmkspl … -e 5000`) and caches them in the run directory —
  hours the first time for 5 TeV on tungsten, instant afterwards.
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
