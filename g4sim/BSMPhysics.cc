#include "BSMPhysics.hh"

#include "G4ParticleDefinition.hh"
#include "G4ParticleTable.hh"
#include "G4DecayTable.hh"
#include "G4PhaseSpaceDecayChannel.hh"
#include "G4UIdirectory.hh"
#include "G4UIcmdWithAString.hh"
#include "G4SystemOfUnits.hh"
#include "CLHEP/Units/PhysicalConstants.h"

#include <sstream>

// --------------------------------------------------------------------------- //
// Registry
// --------------------------------------------------------------------------- //
std::vector<BSMSpec>& BSMPhysics::Registry()
{
    static std::vector<BSMSpec> registry;
    return registry;
}

// Physics type 0 is special-cased by G4VModularPhysicsList::RegisterPhysics:
// it bypasses the "same type already registered -> skip this one" dedup and is
// ALWAYS added. With the default type this constructor collided with another
// (G4NeutrinoPhysics) and was silently dropped, so ConstructParticle never ran
// and the custom particle was never created.
BSMPhysics::BSMPhysics() : G4VPhysicsConstructor("BSMPhysics", 0) {}

// --------------------------------------------------------------------------- //
// Create the G4ParticleDefinition for one spec (idempotent).
//
// This is driven from the /bsm/define messenger command (PreInit) rather than
// waiting for ConstructParticle(): in this build the physics list's
// ConstructParticle() fires BEFORE the macro's /bsm/define runs (the registry
// is still empty then -- the "defining 0 custom particle(s)" symptom), so
// deferring particle creation to it never created the particle and
// /gun/particlePDG aborted with "No particle for PDG id ...". Defining the
// particle the moment the user declares it makes it exist regardless of when
// physics construction happens. The particle self-registers in G4ParticleTable
// and, being unstable (not short-lived), is picked up by G4DecayPhysics'
// G4Decay process at /run/initialize.
static void EnsureParticle(BSMSpec& spec)
{
    auto* table = G4ParticleTable::GetParticleTable();
    if (spec.def) return;
    if (auto* existing = table->FindParticle(spec.pdg)) {  // e.g. re-init
        spec.def = existing;
        return;
    }
    const G4double tau = spec.ctau / CLHEP::c_light;   // proper lifetime = ctau/c
    spec.def = new G4ParticleDefinition(
        spec.name, spec.mass, 0.0, spec.charge * eplus,
        0, 0, 0,             // 2*spin, parity, C-conjugation (unpolarized use)
        0, 0, 0,             // 2*isospin, 2*I3, G-parity
        "custom", 0, 0, spec.pdg,
        false,               // NOT stable: G4Decay picks it up
        tau, nullptr, false);
    G4cout << "BSMPhysics: defined " << spec.name << " (PDG " << spec.pdg
           << ", m = " << spec.mass / MeV << " MeV, ctau = "
           << spec.ctau / mm << " mm)" << G4endl;
}

// Build and attach the decay table for one spec. Runs from ConstructProcess()
// (at /run/initialize), by which point every standard constructor has run its
// ConstructParticle() so the daughter PDG ids resolve to real particles. Set
// before /run/beamOn, so G4Decay uses it at tracking time.
static void EnsureDecayTable(BSMSpec& spec)
{
    if (spec.decayBuilt || spec.channels.empty() || !spec.def) return;
    auto* table = G4ParticleTable::GetParticleTable();
    auto* decays = new G4DecayTable();
    for (const auto& ch : spec.channels) {
        std::vector<G4String> names;
        for (G4int pdg : ch.daughters) {
            auto* d = table->FindParticle(pdg);
            if (!d) {
                G4Exception("BSMPhysics::ConstructProcess", "BSMDaughter",
                            FatalException,
                            ("Unknown daughter PDG id: " + std::to_string(pdg)).c_str());
                return;
            }
            names.push_back(d->GetParticleName());
        }
        switch (names.size()) {
            case 2:
                decays->Insert(new G4PhaseSpaceDecayChannel(
                    spec.name, ch.br, 2, names[0], names[1]));
                break;
            case 3:
                decays->Insert(new G4PhaseSpaceDecayChannel(
                    spec.name, ch.br, 3, names[0], names[1], names[2]));
                break;
            case 4:
                decays->Insert(new G4PhaseSpaceDecayChannel(
                    spec.name, ch.br, 4, names[0], names[1], names[2], names[3]));
                break;
            default:
                G4Exception("BSMPhysics::ConstructProcess", "BSMChannel",
                            FatalException,
                            "G4PhaseSpaceDecayChannel supports 2-4 daughters");
        }
    }
    spec.def->SetDecayTable(decays);
    spec.decayBuilt = true;
    G4cout << "BSMPhysics: " << spec.name << " decay table with "
           << spec.channels.size() << " channel(s)" << G4endl;
}

void BSMPhysics::ConstructParticle()
{
    // Safety net: create any spec not yet materialized by /bsm/define (e.g. if
    // this runs after the macro). Normally the messenger has already done it.
    G4cout << "BSMPhysics::ConstructParticle: " << BSMPhysics::Registry().size()
           << " custom particle(s) registered." << G4endl;
    for (auto& spec : BSMPhysics::Registry()) EnsureParticle(spec);
}

void BSMPhysics::ConstructProcess()
{
    // Standard particles exist now -> resolve daughters and attach decay tables.
    for (auto& spec : BSMPhysics::Registry()) {
        EnsureParticle(spec);       // in case ConstructParticle ran while empty
        EnsureDecayTable(spec);
    }
}

// --------------------------------------------------------------------------- //
// Messenger
// --------------------------------------------------------------------------- //
BSMMessenger::BSMMessenger()
{
    fDir = new G4UIdirectory("/bsm/");
    fDir->SetGuidance("Define long-lived BSM particles (before /run/initialize).");

    fDefineCmd = new G4UIcmdWithAString("/bsm/define", this);
    fDefineCmd->SetGuidance("Define a particle: <name> <pdg> <mass_MeV> <charge> <ctau_mm>");
    fDefineCmd->AvailableForStates(G4State_PreInit);

    fChannelCmd = new G4UIcmdWithAString("/bsm/channel", this);
    fChannelCmd->SetGuidance("Add a decay channel to the last-defined particle: "
                             "<br> <pdg1> <pdg2> [pdg3] [pdg4]");
    fChannelCmd->AvailableForStates(G4State_PreInit);
}

BSMMessenger::~BSMMessenger()
{
    delete fDefineCmd;
    delete fChannelCmd;
    delete fDir;
}

void BSMMessenger::SetNewValue(G4UIcommand* command, G4String newValue)
{
    std::istringstream iss(newValue);
    if (command == fDefineCmd) {
        BSMSpec spec;
        G4double massMeV = 0.0, ctauMm = 0.0;
        if (!(iss >> spec.name >> spec.pdg >> massMeV >> spec.charge >> ctauMm)
            || spec.pdg == 0 || massMeV <= 0.0 || ctauMm <= 0.0) {
            G4Exception("BSMMessenger", "BSMDefine", FatalException,
                        ("Malformed /bsm/define (need: name pdg mass_MeV charge "
                         "ctau_mm): " + newValue).c_str());
            return;
        }
        spec.mass = massMeV * MeV;
        spec.ctau = ctauMm * mm;
        BSMPhysics::Registry().push_back(spec);
        // Materialize the particle now (PreInit) so it exists no matter when
        // the physics list's ConstructParticle() fires; decay table is built
        // later in BSMPhysics::ConstructProcess() when daughters exist.
        EnsureParticle(BSMPhysics::Registry().back());
    } else if (command == fChannelCmd) {
        if (BSMPhysics::Registry().empty()) {
            G4Exception("BSMMessenger", "BSMChannelOrder", FatalException,
                        "/bsm/channel before any /bsm/define");
            return;
        }
        BSMSpec::Channel ch;
        if (!(iss >> ch.br) || ch.br <= 0.0) {
            G4Exception("BSMMessenger", "BSMChannelBR", FatalException,
                        ("Malformed /bsm/channel (need: br pdg pdg ...): "
                         + newValue).c_str());
            return;
        }
        G4int pdg;
        while (iss >> pdg) ch.daughters.push_back(pdg);
        if (ch.daughters.size() < 2 || ch.daughters.size() > 4) {
            G4Exception("BSMMessenger", "BSMChannelN", FatalException,
                        "/bsm/channel needs 2-4 daughter PDG ids");
            return;
        }
        BSMPhysics::Registry().back().channels.push_back(ch);
    }
}
