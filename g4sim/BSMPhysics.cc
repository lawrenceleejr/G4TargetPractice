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

BSMPhysics::BSMPhysics() : G4VPhysicsConstructor("BSMPhysics") {}

void BSMPhysics::ConstructParticle()
{
    // Registered after FTFP_BERT's constructors, so every standard particle
    // already exists here -- daughter PDG ids can be resolved to names.
    auto* table = G4ParticleTable::GetParticleTable();

    for (const auto& spec : BSMPhysics::Registry()) {
        if (table->FindParticle(spec.pdg)) {
            G4Exception("BSMPhysics::ConstructParticle", "BSMDuplicate",
                        FatalException,
                        ("PDG id already exists: " + std::to_string(spec.pdg)).c_str());
        }
        // Proper lifetime tau = ctau / c.
        const G4double tau = spec.ctau / CLHEP::c_light;

        auto* particle = new G4ParticleDefinition(
            spec.name, spec.mass, 0.0, spec.charge * eplus,
            0, 0, 0,             // 2*spin, parity, C-conjugation (unpolarized use)
            0, 0, 0,             // 2*isospin, 2*I3, G-parity
            "custom", 0, 0, spec.pdg,
            false,               // NOT stable: G4Decay picks it up
            tau, nullptr, false);

        if (!spec.channels.empty()) {
            auto* decays = new G4DecayTable();
            for (const auto& ch : spec.channels) {
                std::vector<G4String> names;
                for (G4int pdg : ch.daughters) {
                    auto* d = table->FindParticle(pdg);
                    if (!d) {
                        G4Exception("BSMPhysics::ConstructParticle", "BSMDaughter",
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
                        G4Exception("BSMPhysics::ConstructParticle", "BSMChannel",
                                    FatalException,
                                    "G4PhaseSpaceDecayChannel supports 2-4 daughters");
                }
            }
            particle->SetDecayTable(decays);
        }

        G4cout << "BSMPhysics: defined " << spec.name << " (PDG " << spec.pdg
               << ", m = " << spec.mass / MeV << " MeV, ctau = "
               << spec.ctau / mm << " mm, " << spec.channels.size()
               << " channel(s))" << G4endl;
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
