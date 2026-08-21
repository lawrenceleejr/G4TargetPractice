#pragma once
#include "G4UserSteppingAction.hh"
#include "G4Step.hh"

class EventAction;
class RunAction;
class G4Step;

class SteppingAction : public G4UserSteppingAction {
public:
  SteppingAction(EventAction* eventAction, RunAction* runAction );
    ~SteppingAction() override = default;

    void UserSteppingAction(const G4Step* step) override;

private:
    /// Optional HepMC3 export: record the track if this step leaves the
    /// watched volume (no-op unless /analysis/exitHepMC is set).
    void RecordExitCrossing(const G4Step* step);

    EventAction* fEventAction;
  RunAction* fRunAction;
};
