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

    // --- HepMC3 export of the particles leaving a volume --------------------
    // The scoring-plane / phase-space file: g4sim already READS HepMC3 with
    // /gun/hepmcFile, so this closes the loop for staged simulation and for any
    // downstream tool that speaks HepMC3.
    fExitHepMCCmd = new G4UIcmdWithAString("/analysis/exitHepMC", this);
    fExitHepMCCmd->SetGuidance("Write particles LEAVING a volume to this HepMC3 file.");
    fExitHepMCCmd->SetGuidance("  One GenEvent per event; one vertex per crossing,");
    fExitHepMCCmd->SetGuidance("  at the point and time the particle crossed.");
    fExitHepMCCmd->SetGuidance("  Empty string disables the export (the default).");
    fExitHepMCCmd->SetParameterName("file", true);
    fExitHepMCCmd->SetDefaultValue("");
    fExitHepMCCmd->AvailableForStates(G4State_PreInit, G4State_Idle);

    fExitVolumeCmd = new G4UIcmdWithAString("/analysis/exitVolume", this);
    fExitVolumeCmd->SetGuidance("Physical volume whose exit surface is recorded.");
    fExitVolumeCmd->SetGuidance("  Default 'World': everything escaping the simulation.");
    fExitVolumeCmd->SetParameterName("volume", true);
    fExitVolumeCmd->SetDefaultValue("World");
    fExitVolumeCmd->AvailableForStates(G4State_PreInit, G4State_Idle);

    fExitMinKECmd = new G4UIcmdWithADoubleAndUnit("/analysis/exitMinKE", this);
    fExitMinKECmd->SetGuidance("Skip crossings below this kinetic energy.");
    fExitMinKECmd->SetGuidance("  A shower exit surface is dominated by soft photons;");
    fExitMinKECmd->SetGuidance("  a cut keeps the file to the particles worth carrying.");
    fExitMinKECmd->SetParameterName("ke", true);
    fExitMinKECmd->SetDefaultValue(0.0);
    fExitMinKECmd->SetDefaultUnit("MeV");
    fExitMinKECmd->AvailableForStates(G4State_PreInit, G4State_Idle);

    fExitKillCmd = new G4UIcmdWithABool("/analysis/exitKill", this);
    fExitKillCmd->SetGuidance("Stop tracks at the exit surface once recorded.");
    fExitKillCmd->SetGuidance("  Use for a staged run: the next stage continues from");
    fExitKillCmd->SetGuidance("  this surface, so transporting past it here double counts.");
    fExitKillCmd->SetParameterName("kill", true);
    fExitKillCmd->SetDefaultValue(false);
    fExitKillCmd->AvailableForStates(G4State_PreInit, G4State_Idle);
}

RunActionMessenger::~RunActionMessenger()
{
    delete fNeutrinoModeCmd;
    delete fExitHepMCCmd;
    delete fExitVolumeCmd;
    delete fExitMinKECmd;
    delete fExitKillCmd;
}

void RunActionMessenger::SetNewValue(G4UIcommand* cmd, G4String val)
{
    if (cmd == fNeutrinoModeCmd) {
        if (val == "on")        fRunAction->SetNeutrinoMode(RunAction::NuMode::kOn);
        else if (val == "off")  fRunAction->SetNeutrinoMode(RunAction::NuMode::kOff);
        else                    fRunAction->SetNeutrinoMode(RunAction::NuMode::kAuto);
    } else if (cmd == fExitHepMCCmd) {
        fRunAction->GetExitWriter()->SetFile(val);
    } else if (cmd == fExitVolumeCmd) {
        fRunAction->GetExitWriter()->SetVolume(val);
    } else if (cmd == fExitMinKECmd) {
        fRunAction->GetExitWriter()->SetMinKineticEnergy(
            fExitMinKECmd->GetNewDoubleValue(val));
    } else if (cmd == fExitKillCmd) {
        fRunAction->GetExitWriter()->SetKillAtBoundary(
            fExitKillCmd->GetNewBoolValue(val));
    }
}
