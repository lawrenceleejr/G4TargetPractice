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
}

DetectorMessenger::~DetectorMessenger()
{
    delete fReadGDMLCmd;
    delete fGlobalFieldCmd;
}

void DetectorMessenger::SetNewValue(G4UIcommand* cmd, G4String val)
{
    if (cmd == fReadGDMLCmd) {
        fDetector->ReadGDML(val);
    } else if (cmd == fGlobalFieldCmd) {
        fDetector->SetGlobalField(fGlobalFieldCmd->GetNew3VectorValue(val));
    }
}
