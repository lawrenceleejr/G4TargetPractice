#include "PrimaryGenerator.hh"
#include "PrimaryGeneratorMessenger.hh"
#include "RunAction.hh"

#include "G4ParticleTable.hh"
#include "G4ParticleDefinition.hh"
#include "G4IonTable.hh"
#include "G4Event.hh"
#include "G4SystemOfUnits.hh"
#include "G4RunManager.hh"
#include "Randomize.hh"
#include "CLHEP/Units/PhysicalConstants.h"

#include "HepMC3/ReaderAscii.h"
#include "HepMC3/GenEvent.h"
#include "HepMC3/GenParticle.h"
#include "HepMC3/GenVertex.h"
#include "HepMC3/Units.h"

#include "TTree.h"

#include <cmath>
#include <cstdlib>
#include <sstream>
#include <fstream>
#include <string>
#include <algorithm>

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
    fAngleSigma        = 0.0;            // perfect pencil beam by default

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
    // In beam-file mode the species comes from the file; report the first entry
    // so RunAction's neutrino auto-mode still resolves for a neutrino beam.
    if (!fBeam.empty()) {
        return fBeam.front().def ? fBeam.front().def->GetPDGEncoding() : 0;
    }
    auto* particle = G4ParticleTable::GetParticleTable()->FindParticle(fParticleName);
    return particle ? particle->GetPDGEncoding() : 0;
}

// Resolve a PDG id to a definition; fall back to the ion table for nuclei
// (ion codes 10LZZZAAAI, PDG > 1e9) which are not pre-instantiated.
G4ParticleDefinition* PrimaryGenerator::ResolveByPDG(G4int pdg) const
{
    auto* table = G4ParticleTable::GetParticleTable();
    if (auto* p = table->FindParticle(pdg)) return p;
    if (std::abs(pdg) > 1000000000) {
        const G4int Z = (std::abs(pdg) / 10000) % 1000;
        const G4int A = (std::abs(pdg) / 10) % 1000;
        return table->GetIonTable()->GetIon(Z, A, 0.0);
    }
    return nullptr;
}

// Resolve a beam-file token: a PDG id (all digits, optional sign) or a name.
G4ParticleDefinition* PrimaryGenerator::ResolveToken(const G4String& token) const
{
    const std::string t(token);
    std::size_t start = (t.size() && (t[0] == '-' || t[0] == '+')) ? 1 : 0;
    bool numeric = t.size() > start &&
                   t.find_first_not_of("0123456789", start) == std::string::npos;
    if (numeric) return ResolveByPDG(std::stoi(t));
    return G4ParticleTable::GetParticleTable()->FindParticle(token);
}

void PrimaryGenerator::SetParticlePDG(G4int pdg)
{
    auto* def = ResolveByPDG(pdg);
    if (!def) {
        G4Exception("PrimaryGenerator::SetParticlePDG", "NoParticle", FatalException,
                    ("No particle for PDG id " + std::to_string(pdg)).c_str());
        return;
    }
    fParticleName = def->GetParticleName();
}

// ---------------------------------------------------------------------------
// Beam-file loader: "<name|pdg>  x y z [mm]  px py pz [MeV/c]" ('#' comments)
// ---------------------------------------------------------------------------
void PrimaryGenerator::LoadBeamFile(const G4String& path)
{
    std::ifstream in(path.c_str());
    if (!in) {
        G4Exception("PrimaryGenerator::LoadBeamFile", "NoBeamFile", FatalException,
                    ("Could not open beam file: " + path).c_str());
        return;
    }
    fBeam.clear();
    std::string line;
    while (std::getline(in, line)) {
        // trim leading whitespace; skip blanks and comments
        std::size_t s = line.find_first_not_of(" \t\r\n");
        if (s == std::string::npos || line[s] == '#') continue;
        std::istringstream iss(line);
        std::string token;
        G4double x, y, z, px, py, pz;
        if (!(iss >> token >> x >> y >> z >> px >> py >> pz)) {
            G4Exception("PrimaryGenerator::LoadBeamFile", "BadBeamLine", JustWarning,
                        ("Malformed beam line ignored: " + line).c_str());
            continue;
        }
        BeamEntry e;
        e.def = ResolveToken(token);
        if (!e.def) {
            G4Exception("PrimaryGenerator::LoadBeamFile", "NoParticle", FatalException,
                        ("Beam-file particle not found: " + token).c_str());
        }
        e.position = G4ThreeVector(x * mm, y * mm, z * mm);
        e.momentum = G4ThreeVector(px * MeV, py * MeV, pz * MeV);
        fBeam.push_back(e);
    }
    G4cout << "PrimaryGenerator: loaded " << fBeam.size()
           << " primaries from beam file " << path << G4endl;
}

// ---------------------------------------------------------------------------
// Hand-off event-file loader:
//   E <nParticles> <vx> <vy> <vz>        [mm]
//   <name|pdg> <px> <py> <pz>            [MeV/c]  x nParticles
// ---------------------------------------------------------------------------
void PrimaryGenerator::LoadEventFile(const G4String& path)
{
    // Read the generator->Geant4 hand-off as HepMC3 (the standard interchange),
    // via the official HepMC3 library -- no bespoke parser. Each event's
    // status-1 particles are fired from the production vertex at its time.
    HepMC3::ReaderAscii reader(path.c_str());
    if (reader.failed()) {
        G4Exception("PrimaryGenerator::LoadEventFile", "NoEventFile", FatalException,
                    ("Could not open HepMC3 file: " + path).c_str());
        return;
    }
    fEvents.clear();
    while (true) {
        HepMC3::GenEvent evt(HepMC3::Units::MEV, HepMC3::Units::MM);
        reader.read_event(evt);
        if (reader.failed()) break;
        evt.set_units(HepMC3::Units::MEV, HepMC3::Units::MM);  // normalize to ours

        HandoffEvent h;
        // Fallback for a particle with no production vertex of its own: the
        // event's first vertex, else the origin.
        G4ThreeVector fallbackPos(0, 0, 0);
        G4double fallbackTime = 0.0;
        const auto& verts = evt.vertices();
        if (!verts.empty()) {
            const auto pos = verts.front()->position();
            fallbackPos = G4ThreeVector(pos.x() * mm, pos.y() * mm, pos.z() * mm);
            // HepMC stores the position time as a length (c*t); recover ns.
            fallbackTime = (pos.t() * mm) / CLHEP::c_light;
        }
        for (const auto& p : evt.particles()) {
            if (p->status() != 1) continue;      // final state only
            auto* def = ResolveByPDG(p->pid());
            if (!def) {
                G4Exception("PrimaryGenerator::LoadEventFile", "NoParticle",
                            FatalException,
                            ("HepMC particle PDG not found: "
                             + std::to_string(p->pid())).c_str());
            }
            const auto m = p->momentum();
            HandoffParticle hp;
            hp.def = def;
            hp.momentum = G4ThreeVector(m.px() * MeV, m.py() * MeV, m.pz() * MeV);
            // EACH particle starts from its OWN production vertex: a generator
            // hand-off shares one, an exit/scoring-plane file does not.
            hp.position = fallbackPos;
            hp.time = fallbackTime;
            if (auto prod = p->production_vertex()) {
                const auto pos = prod->position();
                hp.position = G4ThreeVector(pos.x() * mm, pos.y() * mm, pos.z() * mm);
                hp.time = (pos.t() * mm) / CLHEP::c_light;
            }
            h.particles.push_back(hp);
        }
        fEvents.push_back(std::move(h));
    }
    G4cout << "PrimaryGenerator: loaded " << fEvents.size()
           << " HepMC3 hand-off event(s) from " << path << G4endl;
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

namespace {

/// A Standard-Model neutrino fired by the GUN (not a hand-off replay) means the
/// user is asking GEANT4 to do neutrino INTERACTION physics, which it barely
/// does: the cross sections need ~1e12 biasing to interact at all and the final
/// states are not event-generator quality. Say so unmissably, once per run --
/// the Python front-end prints the same advice, but a raw
/// `docker run <image> my.mac` never goes through it. Mute: GDMLTP_NO_WARNINGS=1.
bool IsSMNeutrino(const G4ParticleDefinition* def)
{
    if (!def) return false;
    const G4int pdg = std::abs(def->GetPDGEncoding());
    return pdg == 12 || pdg == 14 || pdg == 16;
}

void WarnNeutrinoOnGeant4(const std::string& name)
{
    const char* mute = std::getenv("GDMLTP_NO_WARNINGS");
    if (mute) {
        const std::string m(mute);
        if (!m.empty() && m != "0" && m != "false") return;
    }
    const std::string bar(78, '!');
    G4cout << bar << G4endl
      << "!! NEUTRINO BEAM (" << name << ") ON THE BARE GEANT4 BACKEND" << G4endl
      << bar << G4endl
      << "!! You are firing " << name << " with GEANT4'S OWN neutrino interactions."
      << G4endl
      << "!! Geant4 is a TRANSPORT engine: its neutrino cross sections are so tiny"  << G4endl
      << "!! that they must be biased by ~1e12 to interact at all, and the final"    << G4endl
      << "!! states are not event-generator quality -- no nuclear initial state, no" << G4endl
      << "!! tuned resonance/DIS models, no intranuclear cascade. Treat interaction" << G4endl
      << "!! physics from this run as a transport artefact, not as neutrino physics."<< G4endl
      << "!!"                                                                        << G4endl
      << "!! USE A NEUTRINO EVENT GENERATOR INSTEAD -- it still ends in Geant4:"      << G4endl
      << "!!     gdmltp run --config examples/nu_argon.yaml -o out     (GENIE)"      << G4endl
      << "!! the generator makes the interaction, Geant4 propagates the final state" << G4endl
      << "!! through this same geometry, and one output.root carries both records."  << G4endl
      << "!!"                                                                        << G4endl
      << "!! Continuing with Geant4. Mute with GDMLTP_NO_WARNINGS=1."                << G4endl
      << bar << G4endl;
}

}  // namespace

// ---------------------------------------------------------------------------
// GeneratePrimaries
// ---------------------------------------------------------------------------
void PrimaryGenerator::GeneratePrimaries(G4Event* event)
{
    // --- Hand-off replay: all final-state particles of one generator event ---
    if (!fEvents.empty()) {
        const std::size_t i = static_cast<std::size_t>(event->GetEventID());
        if (i >= fEvents.size()) {
            G4Exception("PrimaryGenerator", "EventsExhausted", JustWarning,
                        "More events requested than event-file entries; reusing the last.");
        }
        const HandoffEvent& evt = fEvents[std::min(i, fEvents.size() - 1)];
        for (const auto& hp : evt.particles) {
            fParticleGun->SetParticleDefinition(hp.def);
            fParticleGun->SetParticleMomentum(hp.momentum);
            fParticleGun->SetParticlePosition(hp.position);
            fParticleGun->SetParticleTime(hp.time);   // interaction/crossing time
            fParticleGun->GeneratePrimaryVertex(event);
        }
        return;
    }

    // --- Beam-file replay: one host-sampled primary per event ---
    if (!fBeam.empty()) {
        const std::size_t i = static_cast<std::size_t>(event->GetEventID());
        if (i >= fBeam.size()) {
            G4Exception("PrimaryGenerator", "BeamExhausted", JustWarning,
                        "More events requested than beam-file entries; reusing the last.");
        }
        const BeamEntry& e = fBeam[std::min(i, fBeam.size() - 1)];
        fParticleGun->SetParticleDefinition(e.def);
        fParticleGun->SetParticlePosition(e.position);
        fParticleGun->SetParticleMomentum(e.momentum);  // sets direction + energy
        fParticleGun->GeneratePrimaryVertex(event);
        return;
    }

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

    // Warn once per run, here rather than at /gun/particle time, so it reflects
    // the beam that actually fires (the macro may set the gun several times) and
    // never fires for a hand-off/beam-file replay -- both return above.
    if (!fWarnedNeutrinoBeam && IsSMNeutrino(particle)) {
        fWarnedNeutrinoBeam = true;
        WarnNeutrinoOnGeant4(particle->GetParticleName());
    }

    // --- Direction ---
    G4ThreeVector dir;
    if (fUseFixedDirection) {
        dir = fDirection;
        if (fAngleSigma > 0.0) {
            // Smear about the nominal direction to model an angularly divergent
            // beam: draw a polar angle theta ~ Gauss(0, fAngleSigma) and a
            // uniform azimuth phi, build that vector about +z, then rotate the
            // whole cone so its axis points along fDirection. The opening angle
            // |theta| is folded-normal with sigma = fAngleSigma.
            const G4double theta = CLHEP::RandGauss::shoot(0.0, fAngleSigma);
            const G4double phi   = CLHEP::twopi * G4UniformRand();
            G4ThreeVector smeared(std::sin(theta) * std::cos(phi),
                                  std::sin(theta) * std::sin(phi),
                                  std::cos(theta));
            smeared.rotateUz(fDirection);   // map local +z axis onto fDirection
            dir = smeared.unit();
        }
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
