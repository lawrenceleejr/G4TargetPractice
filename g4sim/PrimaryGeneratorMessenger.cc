#include "PrimaryGeneratorMessenger.hh"
#include "PrimaryGenerator.hh"
#include "G4UIdirectory.hh"
#include "G4SystemOfUnits.hh"

#include <sstream>

PrimaryGeneratorMessenger::PrimaryGeneratorMessenger(PrimaryGenerator* gun)
: fGun(gun)
{
    auto* dir = new G4UIdirectory("/gun/");
    dir->SetGuidance("Primary generator commands");

    // ---- Existing commands ----
    fParticleCmd = new G4UIcmdWithAString("/gun/particle", this);
    fParticleCmd->SetGuidance("Set particle type (e.g. e-, nu_mu, nu_e)");
    fParticleCmd->AvailableForStates(G4State_PreInit, G4State_Idle);

    fEnergyCmd = new G4UIcmdWithADoubleAndUnit("/gun/energy", this);
    fEnergyCmd->SetGuidance("Set nominal particle energy (monoenergetic, or mean/E0)");
    fEnergyCmd->SetDefaultUnit("GeV");
    fEnergyCmd->AvailableForStates(G4State_PreInit, G4State_Idle);

    fPositionCmd = new G4UIcmdWith3Vector("/gun/position", this);
    fPositionCmd->SetGuidance("Set particle start position.\n"
                              "Syntax: x y z [unit]  (default unit: mm)\n"
                              "Example: /gun/position 0 0 -60 cm");
    fPositionCmd->AvailableForStates(G4State_PreInit, G4State_Idle);

    fDirectionCmd = new G4UIcmdWith3Vector("/gun/direction", this);
    fDirectionCmd->SetGuidance("Set beam direction (unit vector). "
                               "Use (0,0,0) to restore isotropic 4pi mode.");
    fDirectionCmd->AvailableForStates(G4State_PreInit, G4State_Idle);

    // ---- Energy distribution mode ----
    fEnergyModeCmd = new G4UIcmdWithAString("/gun/energyMode", this);
    fEnergyModeCmd->SetGuidance("Energy sampling mode: mono | gauss | exp | arb");
    fEnergyModeCmd->SetCandidates("mono gauss exp arb");
    fEnergyModeCmd->AvailableForStates(G4State_PreInit, G4State_Idle);

    fGaussSigmaCmd = new G4UIcmdWithADoubleAndUnit("/gun/gaussSigma", this);
    fGaussSigmaCmd->SetGuidance("Sigma for Gaussian energy mode");
    fGaussSigmaCmd->SetDefaultUnit("GeV");
    fGaussSigmaCmd->AvailableForStates(G4State_PreInit, G4State_Idle);

    fEnergyMinCmd = new G4UIcmdWithADoubleAndUnit("/gun/energyMin", this);
    fEnergyMinCmd->SetGuidance("Minimum energy for exp and arb modes");
    fEnergyMinCmd->SetDefaultUnit("GeV");
    fEnergyMinCmd->AvailableForStates(G4State_PreInit, G4State_Idle);

    fEnergyMaxCmd = new G4UIcmdWithADoubleAndUnit("/gun/energyMax", this);
    fEnergyMaxCmd->SetGuidance("Maximum energy for exp and arb modes");
    fEnergyMaxCmd->SetDefaultUnit("GeV");
    fEnergyMaxCmd->AvailableForStates(G4State_PreInit, G4State_Idle);

    // ---- Arbitrary histogram ----
    fAddEnergyBinCmd = new G4UIcmdWithAString("/gun/addEnergyBin", this);
    fAddEnergyBinCmd->SetGuidance(
        "Add a bin to the arbitrary-distribution histogram.\n"
        "Format: /gun/addEnergyBin <energy> <unit> <relativeWeight>\n"
        "Example: /gun/addEnergyBin 500 MeV 2.0");
    fAddEnergyBinCmd->AvailableForStates(G4State_PreInit, G4State_Idle);

    fClearEnergyBinsCmd = new G4UIcmdWithoutParameter("/gun/clearEnergyBins", this);
    fClearEnergyBinsCmd->SetGuidance("Clear all bins defined for the arb energy mode");
    fClearEnergyBinsCmd->AvailableForStates(G4State_PreInit, G4State_Idle);
}

void PrimaryGeneratorMessenger::SetNewValue(G4UIcommand* command, G4String newValue)
{
    if (command == fParticleCmd) {
        fGun->SetParticleName(newValue);
    }
    else if (command == fEnergyCmd) {
        fGun->SetEnergy(fEnergyCmd->GetNewDoubleValue(newValue));
    }
    else if (command == fPositionCmd) {
        // Parse "x y z [unit]" manually so that a trailing unit (e.g. cm) is
        // applied correctly.  G4UIcmdWith3Vector reads only three doubles and
        // leaves any unit token unread, so we handle conversion here.
        std::istringstream pss(newValue.c_str());
        G4double px, py, pz;
        std::string unitStr = "mm";  // Geant4 internal unit default
        pss >> px >> py >> pz >> unitStr;
        G4double unitFactor = G4UIcommand::ValueOf(unitStr.c_str());
        if (unitFactor == 0.0) unitFactor = 1.0;  // unknown unit → mm
        fGun->SetPosition(G4ThreeVector(px * unitFactor,
                                        py * unitFactor,
                                        pz * unitFactor));
    }
    else if (command == fDirectionCmd) {
        fGun->SetDirection(fDirectionCmd->GetNew3VectorValue(newValue));
    }
    else if (command == fEnergyModeCmd) {
        fGun->SetEnergyMode(newValue);
    }
    else if (command == fGaussSigmaCmd) {
        fGun->SetGaussSigma(fGaussSigmaCmd->GetNewDoubleValue(newValue));
    }
    else if (command == fEnergyMinCmd) {
        fGun->SetEnergyMin(fEnergyMinCmd->GetNewDoubleValue(newValue));
    }
    else if (command == fEnergyMaxCmd) {
        fGun->SetEnergyMax(fEnergyMaxCmd->GetNewDoubleValue(newValue));
    }
    else if (command == fAddEnergyBinCmd) {
        // Parse "energy unit weight"
        std::istringstream iss(newValue.c_str());
        G4double energyVal;
        std::string unitStr;
        G4double weight;
        if (!(iss >> energyVal >> unitStr >> weight)) {
            G4Exception("PrimaryGeneratorMessenger", "BadBinFormat", JustWarning,
                        "Usage: /gun/addEnergyBin <energy> <unit> <weight>. Bin ignored.");
            return;
        }
        // Convert energy to G4 internal units using the unit string
        G4double unitFactor = G4UIcommand::ValueOf(unitStr.c_str());
        fGun->AddEnergyBin(energyVal * unitFactor, weight);
    }
    else if (command == fClearEnergyBinsCmd) {
        fGun->ClearEnergyBins();
    }
}
