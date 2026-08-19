#ifndef EVENTACTION_H
#define EVENTACTION_H

#include "G4UserEventAction.hh"
#include "G4Event.hh"
#include "RunAction.hh"
#include "globals.hh"
#include "G4ThreeVector.hh"
#include <vector>
#include <string>
#include <map>

class RunAction;

// One recorded Geant4 step (all tracks). Feeds the lean step_* branches and,
// via aggregation, the per-track trk_* table.
struct StepInfo {
    int trackID;
    int parentID;
    int PDG;
    G4ThreeVector prePos;
    G4ThreeVector postPos;
    double preKinE;        // kinetic energy at the pre-step point
    double postKinE;       // kinetic energy at the post-step point
    double edep;
    double globalTime;
    double stepLength;
    std::string processName;
    std::string creatorProcess;
    G4ThreeVector birthPos;   // track vertex position
    double birthKE;           // track vertex kinetic energy
};

// Per-track summary, accumulated over the track's steps (see AddStepInfo).
struct TrackSummary {
    int parentID = 0;
    int pdg = 0;
    double startX = 0, startY = 0, startZ = 0, startE = 0;
    double endX = 0, endY = 0, endZ = 0, endE = 0;
    std::string creatorProcess = "Primary";
    double edep = 0.0;     // summed energy deposit over the track's steps
    double length = 0.0;   // summed step length
    bool started = false;  // start fields locked on the first step seen
};

class EventAction : public G4UserEventAction {
public:
    EventAction(RunAction* runAction);
    ~EventAction() override;

    void BeginOfEventAction(const G4Event*) override;
    void EndOfEventAction(const G4Event* event) override;

    // Record one step; also folds it into the per-track table.
    void AddStepInfo(int trackID, int parentID, int PDG,
                     const G4ThreeVector& prePos, const G4ThreeVector& postPos,
                     double preKinE, double postKinE,
                     double edep, double globalTime, double stepLength,
                     const std::string& processName,
                     const std::string& creatorProcess,
                     const G4ThreeVector& birthPos, double birthKE);

    void AddEdep(double edep) { totalEdep_ += edep; }
    void IncrementStep() { nSteps_++; }

    // --- Per-event collections ---
    std::vector<StepInfo> steps;
    std::map<int, TrackSummary> trackTable;

    // --- Per-event scalars ---
    int eventID = 0;
    int primaryPDG = 0;
    int primaryTrackID = 0;

    double E = 0, x = 0, y = 0, z = 0;       // primary initial KE / position
    double px = 0, py = 0, pz = 0;           // primary initial momentum
    double finalE = 0, finalX = 0, finalY = 0, finalZ = 0;  // primary stop point
    double finalPx = 0, finalPy = 0, finalPz = 0;           // primary final momentum

    double totalEdep_ = 0;
    int nSteps_ = 0;

    // --- Neutrino-interaction quantities (only meaningful in neutrino mode) ---
    int primaryNuPDG = 0;
    bool interactionRecorded = false;
    std::string nuInteractionProcess = "None";
    bool isCC = false;
    bool isNC = false;
    double vertexX = 0, vertexY = 0, vertexZ = 0, vertexT = 0;
    int nuTargetZ = -1, nuTargetA = -1;
    int outgoingLeptonPDG = 0;
    double outgoingLeptonE = 0;
    double outgoingLeptonPx = 0, outgoingLeptonPy = 0, outgoingLeptonPz = 0;
    double q0 = 0, Q2 = 0, W = 0, xBj = 0, yBj = 0;

private:
    RunAction* fRunAction;
};

#endif
