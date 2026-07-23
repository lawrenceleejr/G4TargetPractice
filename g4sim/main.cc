#include "G4NeutrinoE.hh"
#include "G4AntiNeutrinoE.hh"
#include "G4NeutrinoMu.hh"
#include "G4AntiNeutrinoMu.hh"
#include "G4NeutrinoTau.hh"
#include "G4AntiNeutrinoTau.hh"
#include "G4RunManager.hh"
#include "G4UImanager.hh"
#include "G4VisExecutive.hh"
#include "G4UIExecutive.hh"
#include "G4PhysListFactory.hh"

#include "DetectorConstruction.hh"
#include "PrimaryGenerator.hh"
#include "RunAction.hh"
#include "PrimaryGeneratorMessenger.hh"
#include "EventAction.hh"
#include "G4NeutrinoPhysics.hh"
#include "G4PhysListFactory.hh"
#include "G4VModularPhysicsList.hh"
#include "SteppingAction.hh"
#include "G4EmExtraPhysics.hh"
#include "G4ParticleTable.hh"

#ifdef USE_CELERITAS
#include <CeleritasG4.hh>

namespace {
celeritas::SetupOptions MakeCeleritasOptions()
{
    celeritas::SetupOptions opts;
    // Track-slot counts sized for CPU offload; increase for GPU execution
    opts.max_num_tracks = 2024;
    opts.initializer_capacity = 2024 * 128;
    // Celeritas does not support the standalone Coulomb scattering process
    opts.ignore_processes = {"CoulombScat"};
    // Uniform zero magnetic field (this application defines no field)
    opts.make_along_step = celeritas::UniformAlongStepFactory();
    // This application registers no Geant4 sensitive detectors, so disable
    // Celeritas hit reconstruction (it errors at setup if none are found)
    opts.sd.enabled = false;
    return opts;
}
}  // namespace
#endif


int main(int argc, char** argv) {

  G4PhysListFactory factory;
       auto available = factory.AvailablePhysLists();
   for (auto& name : available) {
      std::cout << name << std::endl;
    }

  // Create the run manager
    G4RunManager* runManager = new G4RunManager;

    auto detector = new DetectorConstruction();
    runManager->SetUserInitialization(detector);

    G4VModularPhysicsList* physics = factory.GetReferencePhysList("FTFP_BERT");
    physics->RegisterPhysics(new G4NeutrinoPhysics());
#ifdef USE_CELERITAS
    auto& celerIntegration = celeritas::TrackingManagerIntegration::Instance();
    physics->RegisterPhysics(
        new celeritas::TrackingManagerConstructor(&celerIntegration));
    celerIntegration.SetOptions(MakeCeleritasOptions());
    G4cout << "Celeritas offload enabled: e-/e+/gamma tracks are handed to "
              "Celeritas for transport.\n"
              "Set CELER_DISABLE=1 in the environment to disable the offload "
              "at runtime." << G4endl;
#endif
    runManager->SetUserInitialization(physics);

     auto runAction = new RunAction();
    runManager->SetUserAction(runAction);

     auto eventAction = new EventAction(runAction);
    runManager->SetUserAction(eventAction);

     auto primary = new PrimaryGenerator(runAction);
     runManager->SetUserAction(primary);
     runAction->SetGenerator(primary);   // lets RunAction auto-detect neutrino primaries

     runManager->SetUserAction(new SteppingAction(eventAction, runAction));

    // UI / macro execution
    G4UImanager* uiManager = G4UImanager::GetUIpointer();
    
    if (argc == 2) {
        uiManager->ApplyCommand("/control/execute " + std::string(argv[1]));
    }

    // Cleanup
    delete runManager;

    return 0;
}
