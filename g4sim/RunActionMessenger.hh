#ifndef RUNACTIONMESSENGER_H
#define RUNACTIONMESSENGER_H

#include "G4UImessenger.hh"
#include "G4UIcmdWithAString.hh"
#include "G4UIcmdWithADoubleAndUnit.hh"
#include "G4UIcmdWithABool.hh"

class RunAction;

// Controls analysis/output options for the run.
class RunActionMessenger : public G4UImessenger {
public:
    RunActionMessenger(RunAction*);
    ~RunActionMessenger() override;

    void SetNewValue(G4UIcommand*, G4String) override;

private:
    RunAction* fRunAction;
    G4UIcmdWithAString* fNeutrinoModeCmd;
    // Optional HepMC3 export of particles leaving a volume (ExitWriter).
    G4UIcmdWithAString* fExitHepMCCmd;
    G4UIcmdWithAString* fExitVolumeCmd;
    G4UIcmdWithADoubleAndUnit* fExitMinKECmd;
    G4UIcmdWithABool* fExitKillCmd;
};

#endif
