# BSM projectiles: the `decay` backend

Fly a long-lived BSM particle — an HNL, dark photon, ALP, dark scalar,
anything defined by a **mass**, a **proper decay length**, and **decay
channels** — through a GDML detector and watch it decay. The backend samples
the parent's production kinematics with the same beam machinery every other
backend uses (fixed values, distributions, Twiss), decays it in flight on the
host, and writes a **displaced vertex** in the common `output.root` schema.
`analyze`, `validate`, `display`, and `compare` work unchanged, and
`decay.transport: true` pushes the daughters through the detector with Geant4.

```yaml
generator: decay
geometry: {gdml: gdml/MAIA_v0.gdml}

beam:
  pdg: 9900014                 # your particle's id -- any integer
  mass: "1.0 GeV"              # required for ids outside the SM mass table
  energy: {mode: mono, value: "500 GeV"}
  position: "0 0 -50 m"
  direction: "0 0 1"

decay:
  ctau: "1 m"                  # proper decay length (alt: lifetime: "3.34 ns")
  channels:
    - {to: [13, 211], br: 0.6}                  # N -> mu- pi+
    - {to: [14, 13, -13], br: 0.4, model: vA}    # N -> nu mu- mu+
  fiducial: {z: ["-2.5 m", "2.5 m"]}             # force decay in the detector
  transport: true                                # Geant4 detector response

run: {events: 500, seed: 1}
```

Runnable example: `examples/maia/hnl_decay.yaml`.

## What the physics engine does

- **Flight & decay point.** The lab decay length is λ = βγ·cτ = (|p|/M)·cτ per
  event. Without a fiducial window the flight length is exponential and every
  event has weight 1. With `decay.fiducial` (a `z` range, a `path`-length
  range, or both) the decay is **forced** into the window by sampling the
  truncated exponential, and the true occupation probability
  `exp(−s₀/λ) − exp(−s₁/λ)` is recorded per event in the **`eventWeight`**
  branch — so a cτ = 500 m particle can be studied with every event decaying
  inside a 5 m detector while rates stay honest. Weight anything you histogram
  by `eventWeight` when converting to expected yields.
- **Decay time.** `decayT` [ns] = flight length / βc is stored per event and
  carried into the Geant4 hand-off (the primaries are stamped with it), so
  daughter timing in the transported file is physical.
- **Daughter kinematics.** Two-body channels are exact (isotropic for an
  unpolarized parent). N-body channels use the Raubold–Lynch (GENBOD)
  phase-space algorithm with accept–reject unweighting — momentum conservation
  and mass shells are exact by construction. Three-body channels may request
  `model: vA`, the V−A matrix element for an unpolarized parent:
  |M|² ∝ (p_parent·p₂)(p₁·p₃) with the daughters listed `[1, 2, 3]`. The
  convention is the muon-decay pairing — for μ⁻ → [e⁻, ν̄ₑ, νμ] it reproduces
  the Michel spectrum exactly (this is a unit test).
- **Branching ratios** are normalized across the listed channels; each event
  picks a channel by BR and the daughters land in `trk_*` (momenta in
  `trk_px/py/pz`, creator process `"Decay"`), with the production point in
  `primaryStart*` and the decay vertex in `primaryEnd*`.

## Honest limitations

- **Parent polarization is not modeled** — rest-frame distributions are
  isotropic (two-body) or V−A/phase-space (three-body) for an *unpolarized*
  parent. HNLs from W/meson decays are generally polarized; the induced
  daughter anisotropies are not captured.
- `model: vA` is one fixed pairing; channels with different Lorentz structure
  (e.g. N → νπ⁰ is two-body and fine, but ρ-mediated or form-factor channels)
  reduce to phase space unless the vA pairing happens to match.
- **Production is up to you**: the backend takes the parent's flux as given
  (energy spectrum, position, direction — anything the beam schema can say).
  Deriving the flux from couplings, or producing the parent inside the
  detector's own interactions, is on the roadmap.
- Majorana vs Dirac is expressed only through the channel list you write
  (add the charge-conjugate channels for a Majorana HNL).

## Weighted analysis

`gdmltp validate` checks `eventWeight ∈ (0, 1]` and `decayT ≥ 0` whenever the
branches are present. Expected event yields are `Σ eventWeight × (flux
normalization)`, not the raw event count — the file deliberately oversamples
the fiducial region.

## Detector response

With `transport: true` the run has two stages: host generation, then the
daughters replayed through the GDML in the Geant4 image via the same hand-off
GENIE/Achilles use (`/gun/eventFile`, one multi-particle vertex per event, at
the decay time). The merged file keeps the parent as the primary
(`primaryPDG` = your id), the decay vertex in `primaryEnd*`, `eventWeight`,
`decayT`, and gains the full `step_*`/`totalEdep` transport record.
