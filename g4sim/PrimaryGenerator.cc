#include "PrimaryGenerator.hh"
#include "PrimaryGeneratorMessenger.hh"
#include "RunAction.hh"

#include "G4ParticleTable.hh"
#include "G4Event.hh"
#include "G4SystemOfUnits.hh"
#include "G4RunManager.hh"
#include "Randomize.hh"
#include "CLHEP/Units/PhysicalConstants.h"

#include "TTree.h"

#include <cmath>
#include <sstream>

/*
 * Supported particle names (examples):
 *   e-  e+  gamma  proton  neutron
 *   pi+ pi- pi0  mu- mu+  kaon+
 *   nu_e  nu_mu  nu_tau  (and anti variants)
 */

PrimaryGenerator::PrimaryGenerator(RunAction* runAction)
    : fRunAction(runAction)
{
    fMessenger = new PrimaryGeneratorMessenger(this);
    fParticleGun = new G4ParticleGun(1);

    // Defaults
    fParticleName      = "nu_mu";
    fEnergy            = 1.0 * CLHEP::GeV;
    fPosition          = G4ThreeVector(0, 0, 0);
    fDirection         = G4ThreeVector(0, 0, 1);
    fUseFixedDirection = false;          // isotropic 4π by default

    fEnergyMode = EnergyMode::kMono;
    fGaussSigma = 0.1 * CLHEP::GeV;
    fEnergyMin  = 0.1 * CLHEP::GeV;
    fEnergyMax  = 10.0 * CLHEP::GeV;

    auto* particle = G4ParticleTable::GetParticleTable()->FindParticle(fParticleName);
    fParticleGun->SetParticleDefinition(particle);
    fParticleGun->SetParticleEnergy(fEnergy);
    fParticleGun->SetParticlePosition(fPosition);
}

PrimaryGenerator::~PrimaryGenerator()
{
    delete fParticleGun;
    delete fMessenger;
}

// ---------------------------------------------------------------------------
// Direction setter
// ---------------------------------------------------------------------------
void PrimaryGenerator::SetDirection(const G4ThreeVector& dir)
{
    if (dir.mag2() < 1e-30) {
        fUseFixedDirection = false;   // zero vector → back to isotropic
    } else {
        fDirection         = dir.unit();
        fUseFixedDirection = true;
    }
}

// ---------------------------------------------------------------------------
// Energy-mode setter
// ---------------------------------------------------------------------------
void PrimaryGenerator::SetEnergyMode(const G4String& mode)
{
    if      (mode == "mono")  fEnergyMode = EnergyMode::kMono;
    else if (mode == "gauss") fEnergyMode = EnergyMode::kGauss;
    else if (mode == "exp")   fEnergyMode = EnergyMode::kExp;
    else if (mode == "arb")   fEnergyMode = EnergyMode::kArb;
    else {
        G4Exception("PrimaryGenerator", "BadEnergyMode", JustWarning,
                    ("Unknown energy mode '" + mode +
                     "'. Use mono|gauss|exp|arb. Falling back to mono.").c_str());
        fEnergyMode = EnergyMode::kMono;
    }
}

// ---------------------------------------------------------------------------
// Arbitrary-histogram bin management
// ---------------------------------------------------------------------------
void PrimaryGenerator::AddEnergyBin(G4double energy, G4double weight)
{
    if (weight <= 0.0) {
        G4Exception("PrimaryGenerator", "BadBinWeight", JustWarning,
                    "Bin weight must be positive; bin ignored.");
        return;
    }
    fEnergyBins.push_back({energy, weight});
}

// ---------------------------------------------------------------------------
// Private helpers: energy sampling
// ---------------------------------------------------------------------------

G4double PrimaryGenerator::SampleExponential() const
{
    // Sample from f(E) ∝ exp(-E/E0), E ∈ [fEnergyMin, fEnergyMax]
    // via inverse-CDF method.
    const G4double E0   = fEnergy;       // characteristic scale
    const G4double Emin = fEnergyMin;
    const G4double Emax = fEnergyMax;

    const G4double a = std::exp(-Emin / E0);
    const G4double b = std::exp(-Emax / E0);
    const G4double u = G4UniformRand();
    return -E0 * std::log(a - u * (a - b));
}

G4double PrimaryGenerator::SampleArbitrary() const
{
    if (fEnergyBins.empty()) {
        G4Exception("PrimaryGenerator", "EmptyHistogram", JustWarning,
                    "No bins defined for 'arb' mode; returning nominal energy.");
        return fEnergy;
    }

    // Build cumulative weights on the fly
    G4double total = 0.0;
    for (const auto& b : fEnergyBins) total += b.second;

    const G4double r = G4UniformRand() * total;
    G4double cumul = 0.0;
    for (const auto& b : fEnergyBins) {
        cumul += b.second;
        if (r <= cumul) return b.first;
    }
    return fEnergyBins.back().first;
}

G4int PrimaryGenerator::GetParticlePDG() const
{
    auto* particle = G4ParticleTable::GetParticleTable()->FindParticle(fParticleName);
    return particle ? particle->GetPDGEncoding() : 0;
}

G4double PrimaryGenerator::SampleEnergy() const
{
    switch (fEnergyMode) {
        case EnergyMode::kMono:
            return fEnergy;

        case EnergyMode::kGauss: {
            G4double E;
            // Reject non-positive energies to avoid unphysical values
            do { E = CLHEP::RandGauss::shoot(fEnergy, fGaussSigma); } while (E <= 0.0);
            return E;
        }

        case EnergyMode::kExp:
            return SampleExponential();

        case EnergyMode::kArb:
            return SampleArbitrary();
    }
    return fEnergy; // unreachable
}

// ---------------------------------------------------------------------------
// GeneratePrimaries
// ---------------------------------------------------------------------------
void PrimaryGenerator::GeneratePrimaries(G4Event* event)
{
    // --- Particle ---
    if (fParticleName.empty()) {
        G4Exception("PrimaryGenerator", "NoParticle", FatalException,
                    "Particle name not set.");
    }
    auto* particle = G4ParticleTable::GetParticleTable()->FindParticle(fParticleName);
    if (!particle) {
        G4Exception("PrimaryGenerator", "NoParticle", FatalException,
                    ("Particle not found: " + fParticleName).c_str());
    }

    // --- Direction ---
    G4ThreeVector dir;
    if (fUseFixedDirection) {
        dir = fDirection;
    } else {
        // Isotropic 4π
        const G4double costh = 2.0 * G4UniformRand() - 1.0;
        const G4double sinth = std::sqrt(1.0 - costh * costh);
        const G4double phi   = CLHEP::twopi * G4UniformRand();
        dir = G4ThreeVector(sinth * std::cos(phi), sinth * std::sin(phi), costh);
    }

    // --- Energy ---
    const G4double E = SampleEnergy();

    // --- Fire ---
    fParticleGun->SetParticleDefinition(particle);
    fParticleGun->SetParticleEnergy(E);
    fParticleGun->SetParticlePosition(fPosition);
    fParticleGun->SetParticleMomentumDirection(dir);
    fParticleGun->GeneratePrimaryVertex(event);

    G4cout << "Primary: "
           << fParticleGun->GetParticleDefinition()->GetParticleName()
           << "  E=" << fParticleGun->GetParticleEnergy() / GeV << " GeV"
           << "  pos=" << fParticleGun->GetParticlePosition()
           << "  dir=" << fParticleGun->GetParticleMomentumDirection()
           << G4endl;
}
