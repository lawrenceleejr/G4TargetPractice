#include "DetectorMessenger.hh"
#include "DetectorConstruction.hh"

DetectorMessenger::DetectorMessenger(DetectorConstruction* det)
: fDetector(det)
{
    fReadGDMLCmd =
      new G4UIcmdWithAString("/detector/readGDML", this);

    fReadGDMLCmd->SetGuidance("Load GDML geometry file");
    fReadGDMLCmd->SetParameterName("filename", false);

    fGlobalFieldCmd =
      new G4UIcmdWith3VectorAndUnit("/detector/setGlobalField", this);

    fGlobalFieldCmd->SetGuidance("Set a uniform magnetic field over the whole geometry");
    fGlobalFieldCmd->SetGuidance("(e.g. a capture solenoid along z). Zero vector disables it.");
    fGlobalFieldCmd->SetParameterName("Bx", "By", "Bz", false);
    fGlobalFieldCmd->SetUnitCategory("Magnetic flux density");
    fGlobalFieldCmd->SetDefaultUnit("tesla");

    // Which volumes land in the neutrino G4Regions that
    // /physics_lists/nu/NuDetectorName and NuOscDistanceName select. Both are
    // PreInit-only: regions are built during /run/initialize.
    fTargetRegionCmd =
      new G4UIcmdWithAString("/detector/targetRegionPattern", this);
    fTargetRegionCmd->SetGuidance(
        "Substring a logical-volume name must contain to join the \"target\" "
        "region (the one /physics_lists/nu/NuDetectorName target biases).");
    fTargetRegionCmd->SetGuidance(
        "Default: empty = EVERY non-world volume. Set e.g. \"_sens\" to bias "
        "only sensitive volumes.");
    fTargetRegionCmd->SetParameterName("pattern", true);
    fTargetRegionCmd->SetDefaultValue("");
    fTargetRegionCmd->AvailableForStates(G4State_PreInit);

    fOscRegionCmd =
      new G4UIcmdWithAString("/detector/oscRegionPattern", this);
    fOscRegionCmd->SetGuidance(
        "Substring a logical-volume name must contain to join the \"tgtosc\" "
        "region, used by /physics_lists/nu/NuOscDistanceName tgtosc.");
    fOscRegionCmd->SetGuidance(
        "Default: empty = no oscillation region. Matching volumes go to tgtosc "
        "INSTEAD of target.");
    fOscRegionCmd->SetParameterName("pattern", true);
    fOscRegionCmd->SetDefaultValue("");
    fOscRegionCmd->AvailableForStates(G4State_PreInit);
}

DetectorMessenger::~DetectorMessenger()
{
    delete fReadGDMLCmd;
    delete fGlobalFieldCmd;
    delete fTargetRegionCmd;
    delete fOscRegionCmd;
}

void DetectorMessenger::SetNewValue(G4UIcommand* cmd, G4String val)
{
    if (cmd == fReadGDMLCmd) {
        fDetector->ReadGDML(val);
    } else if (cmd == fGlobalFieldCmd) {
        fDetector->SetGlobalField(fGlobalFieldCmd->GetNew3VectorValue(val));
    } else if (cmd == fTargetRegionCmd) {
        fDetector->SetTargetRegionPattern(val);
    } else if (cmd == fOscRegionCmd) {
        fDetector->SetOscRegionPattern(val);
    }
}
