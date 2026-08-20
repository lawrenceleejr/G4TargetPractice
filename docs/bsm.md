# BSM projectiles: the `decay` and `external` backends

Fly a long-lived BSM particle — an HNL, dark photon, ALP, dark scalar — through
a GDML detector and watch it decay. **This framework generates none of the
decay physics itself**; it orchestrates established tools, two ways:

1. **`generator: decay` — Geant4 does everything.** The framework renders
   `/bsm/define` + `/bsm/channel` macro commands that hand the particle
   definition to Geant4 (`G4ParticleDefinition` + `G4DecayTable`); Geant4's
   own `G4Decay` process decays it in flight (exponential, time-dilated) with
   daughters from its `G4PhaseSpaceDecayChannel`, and transports everything
   through the detector in the same run. One stage, one engine.
2. **`generator: external` — a real generator does the decay.** Produce the
   events with Pythia8, MadGraph, or anything that writes HepMC3 ASCII —
   proper matrix elements, polarization, form factors — and the framework
   converts them to the common schema and (optionally) transports the final
   state through the detector with Geant4.

## Geant4-native: `generator: decay`

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
  name: N1                     # Geant4 particle name (cosmetic)
  ctau: "1 km"                 # TRUE proper decay length (alt: lifetime)
  ctau_sample: "10 cm"         # generation ctau -> eventWeight reweights back
  charge: 0                    # units of e (default 0)
  channels:
    - {to: [13, 211], br: 0.6}        # N -> mu- pi+
    - {to: [14, 13, -13], br: 0.4}    # N -> nu mu- mu+
run: {events: 200, seed: 1}
```

Runnable example: `examples/maia/hnl_decay.yaml`. Any beam spec works
(spectra, distributions, Twiss — sampled to a beam file exactly as for the
other backends), and the run needs only the standard Geant4 image.

### Lifetime importance sampling (`ctau_sample`)

Realistic couplings give lab decay lengths of km; almost nothing would decay
inside a meters-scale detector. The standard LLP trick: **generate** with a
`ctau_sample` chosen so decays land in the detector (lab length =
βγ·ctau_sample; pick it ≈ the source–detector distance scale), then reweight
each event analytically to the **true** `ctau`. After the run the framework
adds, from the branches Geant4 recorded (flight length s = |`primaryEnd` −
`primaryStart`|, βγ from the gun momentum):

- `decayT` — the flight time in ns;
- `eventWeight` — `(λ_g/λ_t)·exp(s/λ_g − s/λ_t)` for events that decayed,
  `exp(s/λ_g − s/λ_t)` for events whose parent left the world undecayed
  (censored survival ratio), with λ = βγ·cτ per event.

This is arithmetic on Geant4's output, not generation. Weight every histogram
by `eventWeight`; `gdmltp validate` checks the branch is finite and positive.
The custom particle is neutral-by-default with only decay + transportation
attached, so its track ends at exactly one of: the decay or the world edge.

### What Geant4 gives you (and doesn't)

Decay position/time (exponential with time dilation), daughter kinematics
(phase space, 2–4 bodies, exact conservation), full detector response,
displaced-vertex display — all from the engine. **Not modeled**: decay matrix
elements (V−A three-body shapes, form factors) and parent polarization —
Geant4's generic channel is phase space. When those matter, use the external
route below.

## Real-generator decays: `generator: external`

```yaml
generator: external
geometry: {gdml: gdml/MAIA_v0.gdml}
external:
  file: hnl_events.hepmc       # HepMC3 ASCII (Pythia8, MadGraph, ...)
  # Geant4 replays the final states through the GDML detector by default;
  # transport: false keeps the run vertex-level
run: {output: output.root}
```

The converter (the same tolerant pure-Python HepMC3 reader the Achilles
backend uses) takes: primary = the status-4 beam particle, final state =
status-1 particles, the event vertex (displaced vertices supported), HepMC
event weights → `eventWeight`, vertex time → `decayT`. The daughters are then
replayed through the detector in the Geant4 image via the standard hand-off,
timing included; `transport: false` stops at the vertex-level file
(validate/analyze/display/compare all work on either).

E.g. for an HNL with correct V−A decay distributions: define the HNL in
Pythia8 (`id:new`, `id:addChannel` with the appropriate `meMode`), decay your
flux with it, write HepMC3, and hand the file over.

## Which one?

| | `decay` (Geant4) | `external` (Pythia8/MadGraph/...) |
|---|---|---|
| decay kinematics | phase space (2–4 body) | whatever the generator does |
| lifetime/vertex | Geant4 in-flight + `ctau_sample` reweighting | from your file |
| polarization / |M|² | no | yes (generator's) |
| extra installs | none (standard image) | the generator, run by you |
| stages | one | two (conversion, then the Geant4 transport stage) |
