#include "NeutrinoBiasMessenger.hh"

#include "G4NeutrinoPhysics.hh"
#include "G4UIdirectory.hh"
#include "G4UIcommand.hh"
#include "G4UIparameter.hh"

#include <sstream>

NeutrinoBiasMessenger::NeutrinoBiasMessenger(G4NeutrinoPhysics* nuPhysics)
    : fNuPhysics(nuPhysics)
{
    fDir = new G4UIdirectory("/gdmltp/");
    fDir->SetGuidance("GDMLTargetPractice engine controls.");

    fBiasCmd = new G4UIcommand("/gdmltp/neutrinoBias", this);
    fBiasCmd->SetGuidance(
        "Enable + bias Geant4's built-in neutrino interactions (before "
        "/run/initialize). Args: ccBias ncBias nucleusBias detectorRegion. "
        "Sets the bias factors on the registered G4NeutrinoPhysics instance, "
        "so it works in builds that do not register the /physics_lists/em/Nu* "
        "UI commands.");
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
    if (command != fBiasCmd || fNuPhysics == nullptr) return;
    std::istringstream iss(newValue);
    G4double cc = 1.0, nc = 1.0, nuc = 1.0;
    G4String region = "DefaultRegionForTheWorld";
    iss >> cc >> nc >> nuc;
    if (iss >> region) { /* optional region token consumed */ }

    // These setters live on G4NeutrinoPhysics (verified against the Geant4
    // source); they only store members, consumed in ConstructProcess() at
    // /run/initialize. NuETotXscActivated(true) is required for the nucleus
    // bias to be applied (and switches the nu-e process to a single max(cc,nc)
    // total-cross-section factor).
    fNuPhysics->SetNuDetectorName(region);
    fNuPhysics->SetNuEleCcBias(cc);
    fNuPhysics->SetNuEleNcBias(nc);
    fNuPhysics->SetNuNucleusBias(nuc);
    fNuPhysics->NuETotXscActivated(true);
    G4cout << "NeutrinoBiasMessenger: neutrino interactions biased CC=" << cc
           << " NC=" << nc << " nucleus=" << nuc << " in region '" << region
           << "'." << G4endl;
}
