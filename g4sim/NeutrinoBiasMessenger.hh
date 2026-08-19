#ifndef NeutrinoBiasMessenger_h
#define NeutrinoBiasMessenger_h 1

#include "G4UImessenger.hh"
#include "globals.hh"

class G4UIdirectory;
class G4UIcommand;
class G4NeutrinoPhysics;

/// Enables and scales Geant4's built-in neutrino interactions by setting the
/// bias factors directly on the registered G4NeutrinoPhysics instance -- NOT
/// via /physics_lists/em/Nu* UI commands (not registered in every build; an
/// unknown command aborts the batch regardless of /control/suppressAbortion)
/// and NOT via G4EmParameters (which has no neutrino methods). The bias values
/// are plain members of G4NeutrinoPhysics, read in its ConstructProcess() at
/// /run/initialize, so they must be set on the exact registered instance
/// before initialization. Command (PreInit only):
///
///   /gdmltp/neutrinoBias <ccBias> <ncBias> <nucleusBias> <detectorRegion>
///
/// Note (fork behavior): with the total-xsc path activated -- required for the
/// nucleus bias to take effect -- the nu-electron process uses a single
/// max(cc, nc) biasing factor, so independent CC/NC electron biasing and
/// nucleus biasing cannot both apply at once. For "guarantee an interaction"
/// use (one large factor for all) this is irrelevant.
class NeutrinoBiasMessenger : public G4UImessenger {
public:
    explicit NeutrinoBiasMessenger(G4NeutrinoPhysics* nuPhysics);
    ~NeutrinoBiasMessenger() override;
    void SetNewValue(G4UIcommand* command, G4String newValue) override;

private:
    G4NeutrinoPhysics* fNuPhysics;
    G4UIdirectory*     fDir;
    G4UIcommand*       fBiasCmd;
};

#endif
