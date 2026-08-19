#include "RunActionMessenger.hh"
#include "RunAction.hh"
#include "G4UIcommand.hh"

RunActionMessenger::RunActionMessenger(RunAction* runAction)
: fRunAction(runAction)
{
    fNeutrinoModeCmd = new G4UIcmdWithAString("/analysis/neutrinoMode", this);
    fNeutrinoModeCmd->SetGuidance("Emit the nu_* neutrino-interaction branches.");
    fNeutrinoModeCmd->SetGuidance("  auto (default): on when the primary is a neutrino");
    fNeutrinoModeCmd->SetGuidance("  on  : always emit the nu_* branches");
    fNeutrinoModeCmd->SetGuidance("  off : never emit the nu_* branches");
    fNeutrinoModeCmd->SetParameterName("mode", true);
    fNeutrinoModeCmd->SetDefaultValue("auto");
    fNeutrinoModeCmd->SetCandidates("auto on off");
    // Must be applied before /run/beamOn (branches are booked at run start).
    fNeutrinoModeCmd->AvailableForStates(G4State_PreInit, G4State_Idle);
}

RunActionMessenger::~RunActionMessenger()
{
    delete fNeutrinoModeCmd;
}

void RunActionMessenger::SetNewValue(G4UIcommand* cmd, G4String val)
{
    if (cmd == fNeutrinoModeCmd) {
        if (val == "on")        fRunAction->SetNeutrinoMode(RunAction::NuMode::kOn);
        else if (val == "off")  fRunAction->SetNeutrinoMode(RunAction::NuMode::kOff);
        else                    fRunAction->SetNeutrinoMode(RunAction::NuMode::kAuto);
    }
}
