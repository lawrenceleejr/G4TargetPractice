#include "EventAction.hh"
#include "G4Event.hh"
#include "RunAction.hh"
#include "G4PrimaryParticle.hh"
#include "G4PrimaryVertex.hh"
#include "CLHEP/Units/PhysicalConstants.h"
#include <cmath>

EventAction::EventAction(RunAction* runAction)
  : fRunAction(runAction)
{}

EventAction::~EventAction() {}

void EventAction::BeginOfEventAction(const G4Event* event)
{
    eventID = event->GetEventID();

    // Per-event collections
    steps.clear();
    trackTable.clear();

    // Primary kinematics
    E = x = y = z = 0;
    px = py = pz = 0;
    finalE = finalX = finalY = finalZ = 0;
    finalPx = finalPy = finalPz = 0;
    totalEdep_ = 0;
    nSteps_ = 0;
    primaryPDG = 0;

    // Neutrino-interaction quantities
    interactionRecorded = false;
    nuInteractionProcess = "None";
    isCC = false;
    isNC = false;
    vertexX = vertexY = vertexZ = vertexT = 0;
    nuTargetZ = nuTargetA = -1;
    outgoingLeptonPDG = 0;
    outgoingLeptonE = outgoingLeptonPx = outgoingLeptonPy = outgoingLeptonPz = 0;
    q0 = Q2 = W = xBj = yBj = 0;

    // Primary particle PDG (from the generated vertex)
    if (auto* vertex = event->GetPrimaryVertex(0)) {
        if (auto* primary = vertex->GetPrimary(0)) {
            primaryNuPDG = primary->GetPDGcode();
            primaryPDG = primaryNuPDG;
        }
    }
}

void EventAction::AddStepInfo(int trackID, int parentID, int PDG,
                              const G4ThreeVector& prePos, const G4ThreeVector& postPos,
                              double preKinE, double postKinE,
                              double edep, double globalTime, double stepLength,
                              const std::string& processName,
                              const std::string& creatorProcess,
                              const G4ThreeVector& birthPos, double birthKE)
{
    StepInfo s;
    s.trackID = trackID;
    s.parentID = parentID;
    s.PDG = PDG;
    s.prePos = prePos;
    s.postPos = postPos;
    s.preKinE = preKinE;
    s.postKinE = postKinE;
    s.edep = edep;
    s.globalTime = globalTime;
    s.stepLength = stepLength;
    s.processName = processName;
    s.creatorProcess = creatorProcess;
    s.birthPos = birthPos;
    s.birthKE = birthKE;
    steps.push_back(s);

    // Fold into the per-track summary (map iterates sorted by trackID).
    auto& t = trackTable[trackID];
    if (!t.started) {
        t.started = true;
        t.parentID = parentID;
        t.pdg = PDG;
        t.startX = birthPos.x();
        t.startY = birthPos.y();
        t.startZ = birthPos.z();
        t.startE = birthKE;
        t.creatorProcess = creatorProcess;
    }
    t.edep += edep;
    t.length += stepLength;
    // End fields track the latest step (steps for a track arrive in order).
    t.endX = postPos.x();
    t.endY = postPos.y();
    t.endZ = postPos.z();
    t.endE = postKinE;
}

void EventAction::EndOfEventAction(const G4Event*)
{
    if (!fRunAction) return;

    // Neutrino DIS-style kinematics (only when the neutrino block is active and
    // a charged-current lepton was found).
    if (fRunAction->NeutrinoBranchesEnabled() && isCC && outgoingLeptonPDG != 0 && E > 0.0) {
        const double nucleonMass = 939.565 * CLHEP::MeV;
        G4ThreeVector pNu(px, py, pz);
        G4ThreeVector pLep(outgoingLeptonPx, outgoingLeptonPy, outgoingLeptonPz);
        double qEnergy = E - outgoingLeptonE;
        G4ThreeVector qVec = pNu - pLep;
        q0 = qEnergy;
        Q2 = qVec.mag2() - qEnergy * qEnergy;
        double W2 = nucleonMass * nucleonMass + 2.0 * nucleonMass * qEnergy - Q2;
        W = (W2 > 0.0) ? std::sqrt(W2) : 0.0;
        xBj = (2.0 * nucleonMass * qEnergy > 0.0) ? Q2 / (2.0 * nucleonMass * qEnergy) : 0.0;
        yBj = qEnergy / E;
    }

    // --- Event scalars ---
    fRunAction->eventID = eventID;
    fRunAction->primaryPDG = primaryPDG;
    fRunAction->primaryE = E;
    fRunAction->primaryStartX = x;
    fRunAction->primaryStartY = y;
    fRunAction->primaryStartZ = z;
    fRunAction->primaryStartPx = px;
    fRunAction->primaryStartPy = py;
    fRunAction->primaryStartPz = pz;
    fRunAction->primaryEndE = finalE;
    fRunAction->primaryEndX = finalX;
    fRunAction->primaryEndY = finalY;
    fRunAction->primaryEndZ = finalZ;
    fRunAction->primaryEndPx = finalPx;
    fRunAction->primaryEndPy = finalPy;
    fRunAction->primaryEndPz = finalPz;
    fRunAction->totalEdep = totalEdep_;
    fRunAction->nSteps = nSteps_;
    fRunAction->nTracks = static_cast<int>(trackTable.size());

    // --- Neutrino block ---
    if (fRunAction->NeutrinoBranchesEnabled()) {
        fRunAction->nu_isCC = isCC;
        fRunAction->nu_isNC = isNC;
        fRunAction->nu_interactionProcess = nuInteractionProcess;
        fRunAction->nu_vertexX = vertexX;
        fRunAction->nu_vertexY = vertexY;
        fRunAction->nu_vertexZ = vertexZ;
        fRunAction->nu_vertexT = vertexT;
        fRunAction->nu_targetZ = nuTargetZ;
        fRunAction->nu_targetA = nuTargetA;
        fRunAction->nu_outLeptonPDG = outgoingLeptonPDG;
        fRunAction->nu_outLeptonE = outgoingLeptonE;
        fRunAction->nu_outLeptonPx = outgoingLeptonPx;
        fRunAction->nu_outLeptonPy = outgoingLeptonPy;
        fRunAction->nu_outLeptonPz = outgoingLeptonPz;
        fRunAction->nu_Q2 = Q2;
        fRunAction->nu_W = W;
        fRunAction->nu_x = xBj;
        fRunAction->nu_y = yBj;
        fRunAction->nu_q0 = q0;
    }

    fRunAction->FillEvent(this);
    fRunAction->GetTree()->Fill();
}
