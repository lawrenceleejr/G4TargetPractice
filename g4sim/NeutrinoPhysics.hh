#ifndef NeutrinoPhysics_h
#define NeutrinoPhysics_h 1

#include "G4VPhysicsConstructor.hh"
#include "globals.hh"

/// Geant4's built-in neutrino interactions, with EVERY biasing term Geant4
/// actually implements exposed as an independent knob.
///
/// Why not G4NeutrinoPhysics? That constructor hard-wires most of the biasing
/// surface: it offers one nucleus factor shared by all three flavours, gates it
/// behind NuETotXscActivated (which simultaneously collapses the nu-electron
/// CC/NC pair into a single max(cc,nc) factor), never touches the cross-section
/// data sets' own biasing factors at all, and gives no access to the per-process
/// low-energy thresholds. This class builds the same processes, models and cross
/// sections as G4NeutrinoPhysics -- so the PHYSICS is unchanged -- and then lets
/// each term be set on its own.
///
/// THE FOUR DISTINCT BIASING TERMS (verified against the Geant4 11.4 sources;
/// they are genuinely different, not aliases):
///
///   mfpBias   G4*Process::SetBiasingFactor(bf). Multiplies the total cross
///             section inside GetMeanFreePath, and ONLY when the pre-step
///             point's G4Region name equals the process's envelope name, and
///             ONLY for bf > 1. This is the "guarantee an interaction here"
///             knob: it changes where/how often the process fires, not the
///             tabulated cross section.
///
///   cc/ncBias G4*Process::SetBiasingFactors(cc, nc). Two effects:
///             (a) the process's own factor becomes max(cc, nc);
///             (b) if either is > 1, PostStepDoIt spreads the interaction
///                 vertex UNIFORMLY along the neutrino's chord through the
///                 current volume instead of putting it at the step end --
///                 which is what you want for a thick target under heavy bias.
///             For the nu-ELECTRON family the pair additionally reaches the
///             separate CC and NC cross-section data sets, so it really does
///             reweight the CC/NC mix. For the nu-NUCLEUS families there is no
///             CC/NC-split data set: the CC fraction comes from the physics
///             (G4*NeutrinoNucleusTotXsc::GetCcTotRatio()) and cc/nc only act
///             through (a) and (b). Geant4 has no CC/NC nucleus reweighting.
///
///   xsecBias  G4*NeutrinoNucleusTotXsc / G4NeutrinoElectronTotXsc::
///             SetBiasingFactor(bf). Scales the tabulated total cross section
///             itself (`totXsc *= fBiasingFactor`), everywhere, in every region.
///             G4NeutrinoPhysics never calls this.
///
///   xsecCc/NcBias  G4NeutrinoElectronTotXsc::SetBiasingFactors(cc, nc), which
///             reaches the SEPARATE CC and NC cross-section objects -- the only
///             term in Geant4 that genuinely changes a CC/NC ratio. Electron
///             family only; the nucleus data sets have no CC/NC split.
///
/// DANGER, on the two xsec terms for the ELECTRON family: G4NeutrinoElectronTotXsc
/// is the only one of the four data sets that implements no isotope-level cross
/// section (no GetIsoCrossSection / IsIsoApplicable). Bias it hard enough that the
/// nu+e- process actually interacts and Geant4 aborts inside
/// G4CrossSectionDataStore::GetIsoCrossSection ("No isotope cross section found
/// for nu_mu off target Element Ar Z= 18 A= 36 from G4_lAr") -- verified by
/// running it. That is an upstream defect in a data set we do not own, so these
/// knobs stay available but warn loudly, and nothing sets them implicitly. The
/// mean-free-path route (mfpBias, or cc/ncBias, which only touch the process)
/// biases nu+e- safely.
///
///   lowestEnergy  G4*Process::SetLowestEnergy(E). Below it the process does
///             nothing. Default 1 keV for the interaction processes.
///
/// Oscillation (G4NuVacOscProcess) has its own two knobs: distanceBias
/// (SetBiasingFactor -- silently ignored unless > 1) and lowestEnergy. Note
/// that G4NeutrinoPhysics enables this process by DEFAULT and no
/// /physics_lists/nu/ command can switch it off.
///
/// All knobs are read in ConstructProcess(), i.e. at /run/initialize, so they
/// must be set before it (the messenger's commands are PreInit-only).
class NeutrinoPhysics : public G4VPhysicsConstructor {
public:
    /// One process family's biasing terms. `region` is a **G4Region** name --
    /// the process is inert outside it. "DefaultRegionForTheWorld" is the
    /// region Geant4 gives every volume that joins no other region.
    struct Knobs {
        G4bool   enable = true;
        G4String region = "DefaultRegionForTheWorld";
        G4double mfpBias = 1.0;
        G4double ccBias = 1.0;
        G4double ncBias = 1.0;
        G4double xsecBias = 1.0;
        // electron family only: the CC/NC-splitting cross-section term
        G4double xsecCcBias = 1.0;
        G4double xsecNcBias = 1.0;
        G4double lowestEnergy = -1.0;   // < 0 = leave Geant4's default
    };

    /// The four interaction families are separate process objects in Geant4, so
    /// each carries its own independent set of factors.
    enum Family { kElectron = 0, kNucleusE, kNucleusMu, kNucleusTau, kNFamilies };

    explicit NeutrinoPhysics(G4int ver = 1);
    ~NeutrinoPhysics() override = default;

    void ConstructParticle() override;
    void ConstructProcess() override;

    Knobs& Get(Family f) { return fKnobs[f]; }
    Knobs& Oscillation() { return fOsc; }

    /// Human-readable dump of every resolved knob (used by /gdmltp/nu/list and
    /// printed once at ConstructProcess so a run's log records what was set).
    void Print() const;

    static const char* FamilyName(Family f);

private:
    Knobs fKnobs[kNFamilies];
    // Oscillation reuses Knobs but only enable/region/mfpBias(=distance bias)
    // and lowestEnergy are meaningful; cc/nc/xsec have no counterpart.
    Knobs fOsc;
    G4int fVerbose;
};

#endif
