#include "NeutrinoBiasMessenger.hh"

#include "G4EmParameters.hh"
#include "G4UIdirectory.hh"
#include "G4UIcommand.hh"
#include "G4UIparameter.hh"

#include <sstream>

NeutrinoBiasMessenger::NeutrinoBiasMessenger()
{
    fDir = new G4UIdirectory("/gdmltp/");
    fDir->SetGuidance("GDMLTargetPractice engine controls.");

    fBiasCmd = new G4UIcommand("/gdmltp/neutrinoBias", this);
    fBiasCmd->SetGuidance(
        "Enable + bias Geant4's built-in neutrino interactions (before "
        "/run/initialize). Args: ccBias ncBias nucleusBias detectorRegion. "
        "Uses the G4EmParameters API directly, so it works in builds that do "
        "not register the /physics_lists/em/Nu* UI commands.");
    for (const char* name : {"ccBias", "ncBias", "nucleusBias"}) {
        auto* p = new G4UIparameter(name, 'd', false);
        p->SetParameterRange(std::string(name) + " >= 1.");
        fBiasCmd->SetParameter(p);
    }
    fBiasCmd->SetParameter(new G4UIparameter("detectorRegion", 's', true));
    fBiasCmd->AvailableForStates(G4State_PreInit);
}

NeutrinoBiasMessenger::~NeutrinoBiasMessenger()
{
    delete fBiasCmd;
    delete fDir;
}

void NeutrinoBiasMessenger::SetNewValue(G4UIcommand* command, G4String newValue)
{
    if (command != fBiasCmd) return;
    std::istringstream iss(newValue);
    G4double cc = 1.0, nc = 1.0, nuc = 1.0;
    G4String region = "DefaultRegionForTheWorld";
    iss >> cc >> nc >> nuc;
    if (iss >> region) { /* optional region token consumed */ }

    auto* emp = G4EmParameters::Instance();
    emp->SetNeutrinoActivation(true);
    emp->SetNuDetectorName(region);
    emp->SetNuElectronCcBias(cc);
    emp->SetNuElectronNcBias(nc);
    emp->SetNuNucleusBias(nuc);
    G4cout << "NeutrinoBiasMessenger: neutrino interactions enabled; bias "
           << "CC=" << cc << " NC=" << nc << " nucleus=" << nuc
           << " in region '" << region << "'." << G4endl;
}
