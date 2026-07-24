#ifndef BSMPhysics_h
#define BSMPhysics_h 1

#include "G4VPhysicsConstructor.hh"
#include "G4UImessenger.hh"
#include "globals.hh"

#include <memory>
#include <vector>

class G4UIcmdWithAString;

/// One user-defined long-lived particle, filled by /bsm/* macro commands
/// (PreInit) and turned into a real G4ParticleDefinition + G4DecayTable by
/// BSMPhysics::ConstructParticle() during /run/initialize. Geant4's own
/// G4Decay process then does the in-flight decay (exponential with time
/// dilation) and its G4PhaseSpaceDecayChannel generates the daughters -- this
/// framework defines the particle, Geant4 does the physics.
struct BSMSpec {
    G4String name;
    G4int    pdg    = 0;
    G4double mass   = 0.0;   ///< G4 internal (set from MeV)
    G4double charge = 0.0;   ///< units of e
    G4double ctau   = 0.0;   ///< G4 internal length (set from mm)
    struct Channel {
        G4double br;
        std::vector<G4int> daughters;   ///< PDG ids, resolved at construction
    };
    std::vector<Channel> channels;
};

class BSMPhysics : public G4VPhysicsConstructor {
public:
    BSMPhysics();
    ~BSMPhysics() override = default;

    void ConstructParticle() override;
    void ConstructProcess() override {}

    /// Registry shared with the messenger (commands run before initialize).
    static std::vector<BSMSpec>& Registry();
};

/// Macro commands (PreInit only):
///   /bsm/define <name> <pdg> <mass_MeV> <charge> <ctau_mm>
///   /bsm/channel <br> <pdg1> <pdg2> [pdg3] [pdg4]   (applies to the last define)
class BSMMessenger : public G4UImessenger {
public:
    BSMMessenger();
    ~BSMMessenger() override;
    void SetNewValue(G4UIcommand* command, G4String newValue) override;

private:
    G4UIdirectory*      fDir;
    G4UIcmdWithAString* fDefineCmd;
    G4UIcmdWithAString* fChannelCmd;
};

#endif
