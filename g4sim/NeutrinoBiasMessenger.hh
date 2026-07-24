#ifndef NeutrinoBiasMessenger_h
#define NeutrinoBiasMessenger_h 1

#include "G4UImessenger.hh"
#include "globals.hh"

class G4UIdirectory;
class G4UIcommand;

/// Enables and scales Geant4's built-in neutrino interactions via the
/// G4EmParameters C++ API -- NOT the /physics_lists/em/Nu* UI commands, which
/// are not registered in every Geant4 build (and an unknown command aborts the
/// batch regardless of /control/suppressAbortion). Command (PreInit only):
///
///   /gdmltp/neutrinoBias <ccBias> <ncBias> <nucleusBias> <detectorRegion>
///
/// Sets SetNeutrinoActivation(true) + the three bias factors + the detector
/// region on G4EmParameters, which the neutrino processes read at
/// /run/initialize. Emitted by the geant4 backend's neutrino_bias config.
class NeutrinoBiasMessenger : public G4UImessenger {
public:
    NeutrinoBiasMessenger();
    ~NeutrinoBiasMessenger() override;
    void SetNewValue(G4UIcommand* command, G4String newValue) override;

private:
    G4UIdirectory* fDir;
    G4UIcommand*   fBiasCmd;
};

#endif
