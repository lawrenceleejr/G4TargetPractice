#ifndef PRIMARYGENERATOR_H
#define PRIMARYGENERATOR_H

#include "G4VUserPrimaryGeneratorAction.hh"
#include "G4ParticleGun.hh"
#include "G4ThreeVector.hh"
#include "RunAction.hh"

#include <utility>
#include <vector>

class PrimaryGeneratorMessenger;

/// Supported energy-sampling modes.
enum class EnergyMode {
    kMono,  ///< Fixed (monoenergetic) beam – use /gun/energy
    kGauss, ///< Gaussian spread        – use /gun/energy (mean) + /gun/gaussSigma
    kExp,   ///< Exponential spectrum   – use /gun/energy (E0)  + /gun/energyMin/Max
    kArb    ///< Arbitrary histogram    – defined with /gun/addEnergyBin
};

class PrimaryGenerator : public G4VUserPrimaryGeneratorAction {
public:
    PrimaryGenerator(RunAction* runAction);
    ~PrimaryGenerator() override;

    void GeneratePrimaries(G4Event* event) override;

    // Setters used by messenger
    void SetParticleName(const G4String& name) { fParticleName = name; }
    void SetEnergy(G4double energy)             { fEnergy = energy; }
    void SetPosition(const G4ThreeVector& pos)  { fPosition = pos; }

    /// Fix the beam direction; pass (0,0,0) to re-enable isotropic 4π mode.
    void SetDirection(const G4ThreeVector& dir);

    /// Gaussian angular divergence (sigma of the polar angle) about the fixed
    /// direction. 0 (default) = perfect pencil beam. Ignored in isotropic mode.
    void SetAngleSigma(G4double sigma) { fAngleSigma = sigma; }

    void SetEnergyMode(const G4String& mode);
    void SetGaussSigma(G4double sigma) { fGaussSigma = sigma; }
    void SetEnergyMin(G4double emin)   { fEnergyMin  = emin; }
    void SetEnergyMax(G4double emax)   { fEnergyMax  = emax; }

    /// Add a histogram bin for the arbitrary-distribution mode.
    /// @param energy  Representative energy of this bin.
    /// @param weight  Relative probability weight (need not be normalised).
    void AddEnergyBin(G4double energy, G4double weight);
    void ClearEnergyBins() { fEnergyBins.clear(); }

    /// Load a host-sampled beam file: one primary per line,
    ///   <name|pdg>  x y z [mm]  px py pz [MeV/c]
    /// The first token may be a Geant4 name or a PDG id. When loaded,
    /// GeneratePrimaries replays entry i for event i, ignoring the
    /// gun/energy/position/direction sampling above.
    void LoadBeamFile(const G4String& path);

    /// Set the primary particle by PDG id (handles standard particles and ions).
    void SetParticlePDG(G4int pdg);

    /// PDG code of the currently configured primary particle (0 if unknown).
    /// Used by RunAction to auto-enable neutrino-mode output branches.
    G4int GetParticlePDG() const;

private:
    G4double SampleEnergy() const;
    G4double SampleExponential() const;
    G4double SampleArbitrary()   const;

    PrimaryGeneratorMessenger* fMessenger;
    G4ParticleGun*             fParticleGun;

    G4String      fParticleName;
    G4double      fEnergy;
    G4ThreeVector fPosition;
    G4ThreeVector fDirection;
    G4bool        fUseFixedDirection;
    G4double      fAngleSigma;   ///< Gaussian polar-angle spread about fDirection (rad).

    EnergyMode fEnergyMode;
    G4double   fGaussSigma;
    G4double   fEnergyMin;
    G4double   fEnergyMax;

    /// Discrete histogram for kArb mode: (energy, weight) pairs.
    std::vector<std::pair<G4double, G4double>> fEnergyBins;

    /// Resolve a particle by PDG id, falling back to the ion table for nuclei.
    G4ParticleDefinition* ResolveByPDG(G4int pdg) const;
    /// Resolve a beam-file token: a PDG id (numeric) or a Geant4 particle name.
    G4ParticleDefinition* ResolveToken(const G4String& token) const;

    /// One host-sampled primary from a beam file (Geant4 internal units).
    struct BeamEntry {
        G4ParticleDefinition* def = nullptr;   ///< resolved at load time
        G4ThreeVector         position;        ///< mm
        G4ThreeVector         momentum;        ///< MeV/c
    };
    std::vector<BeamEntry> fBeam;   ///< non-empty => beam-file replay mode

    RunAction* fRunAction;
};

#endif
