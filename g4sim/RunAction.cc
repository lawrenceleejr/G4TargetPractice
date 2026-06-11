#include "RunAction.hh"
#include "G4Run.hh"
#include "EventAction.hh"

#ifdef USE_CELERITAS
#include <CeleritasG4.hh>
#endif

RunAction::RunAction()
: G4UserRunAction(),
  fFile(nullptr), fTree(nullptr),
  E(0), x(0), y(0), z(0),
  finalE(0), finalX(0), finalY(0), finalZ(0),
  px(0), py(0), pz(0), theta(0), phi(0),
  totalEdep(0), nSteps(0), nSecondaries(0)
{}

RunAction::~RunAction() {}

void RunAction::BeginOfRunAction([[maybe_unused]] const G4Run* run) {
#ifdef USE_CELERITAS
    celeritas::TrackingManagerIntegration::Instance().BeginOfRunAction(run);
#endif
    fFile = new TFile("output.root", "RECREATE");
    fTree = new TTree("tree", "Simulation data");

    fTree->Branch("eventID", &eventID, "eventID/I");
    fTree->Branch("primaryPDG", &primaryPDG, "primaryPDG/I");
    fTree->Branch("nuInteractionProcess", &nuInteractionProcess);
    fTree->Branch("isCC", &isCC, "isCC/O");
    fTree->Branch("isNC", &isNC, "isNC/O");
    fTree->Branch("outgoingLeptonPDG", &outgoingLeptonPDG, "outgoingLeptonPDG/I");
    fTree->Branch("outgoingLeptonE", &outgoingLeptonE, "outgoingLeptonE/D");
    fTree->Branch("outgoingLeptonPx", &outgoingLeptonPx, "outgoingLeptonPx/D");
    fTree->Branch("outgoingLeptonPy", &outgoingLeptonPy, "outgoingLeptonPy/D");
    fTree->Branch("outgoingLeptonPz", &outgoingLeptonPz, "outgoingLeptonPz/D");
    fTree->Branch("q0", &q0, "q0/D");
    fTree->Branch("Q2", &Q2, "Q2/D");
    fTree->Branch("W", &W, "W/D");
    fTree->Branch("xBj", &xBj, "xBj/D");
    fTree->Branch("yBj", &yBj, "yBj/D");

    fTree->Branch("step_time", &step_time);
    fTree->Branch("step_stepLength", &step_stepLength);
    fTree->Branch("step_preMomX", &step_preMomX);
    fTree->Branch("step_preMomY", &step_preMomY);
    fTree->Branch("step_preMomZ", &step_preMomZ);
    fTree->Branch("step_postMomX", &step_postMomX);
    fTree->Branch("step_postMomY", &step_postMomY);
    fTree->Branch("step_postMomZ", &step_postMomZ);

    fTree->Branch("interactionType", &interactionType);
    fTree->Branch("step_proc", &step_proc);
    fTree->Branch("step_creatorproc", &step_creatorproc);
    fTree->Branch("step_preX", &step_preX);
    fTree->Branch("step_preY", &step_preY);
    fTree->Branch("step_preZ", &step_preZ);
    fTree->Branch("step_postX", &step_postX);
    fTree->Branch("step_postY", &step_postY);
    fTree->Branch("step_postZ", &step_postZ);
    fTree->Branch("step_kinE", &step_kinE);
    fTree->Branch("step_edep", &step_edep);
    fTree->Branch("step_trackID", &step_trackID);
    fTree->Branch("step_parentID", &step_parentID);
    fTree->Branch("step_PDG", &step_PDG);
    fTree->Branch("trk_birthPosX", &trk_birthPosX);
    fTree->Branch("trk_birthPosY", &trk_birthPosY);
    fTree->Branch("trk_birthPosZ", &trk_birthPosZ);
    fTree->Branch("trk_birthKE", &trk_birthKE);

    fTree->Branch("E", &E, "E/D");
    fTree->Branch("x", &x, "x/D");
    fTree->Branch("y", &y, "y/D");
    fTree->Branch("z", &z, "z/D");
    fTree->Branch("costh", &costh, "costh/D");
    fTree->Branch("vertexX", &vertexX, "vertexX/D");
    fTree->Branch("vertexY", &vertexY, "vertexY/D");
    fTree->Branch("vertexZ", &vertexZ, "vertexZ/D");
    fTree->Branch("vertexT", &vertexT, "vertexT/D");
    fTree->Branch("finalE", &finalE, "finalE/D");
    fTree->Branch("finalX", &finalX, "finalX/D");
    fTree->Branch("finalY", &finalY, "finalY/D");
    fTree->Branch("finalZ", &finalZ, "finalZ/D");
    fTree->Branch("px", &px, "px/D");
    fTree->Branch("py", &py, "py/D");
    fTree->Branch("pz", &pz, "pz/D");
    fTree->Branch("finalPx", &finalPx, "finalPx/D");
    fTree->Branch("finalPy", &finalPy, "finalPy/D");
    fTree->Branch("finalPz", &finalPz, "finalPz/D");
    fTree->Branch("finalCosth", &finalCosth, "finalCosth/D");
    fTree->Branch("theta", &theta, "theta/D");
    fTree->Branch("phi", &phi, "phi/D");
    fTree->Branch("finalPhi", &finalPhi, "finalPhi/D");
    fTree->Branch("finalPhiDeg", &finalPhiDeg, "finalPhiDeg/D");    
    fTree->Branch("totalEdep", &totalEdep, "totalEdep/D");
    fTree->Branch("nSteps", &nSteps, "nSteps/I");
    fTree->Branch("nSecondaries", &nSecondaries, "nSecondaries/I");
    fTree->Branch("secEnergies", &secEnergies);
    fTree->Branch("nGamma", &nGamma, "nGamma/I");
    fTree->Branch("nElectron", &nElectron, "nElectron/I");
    fTree->Branch("nPositron", &nPositron, "nPositron/I");
    fTree->Branch("nProtonSec", &nProtonSec, "nProtonSec/I");
    fTree->Branch("nNeutron", &nNeutron, "nNeutron/I");
    fTree->Branch("nPionPlus", &nPionPlus, "nPionPlus/I");
    fTree->Branch("nPionMinus", &nPionMinus, "nPionMinus/I");
    fTree->Branch("nPionZero", &nPionZero, "nPionZero/I");
    fTree->Branch("nMuonPlus", &nMuonPlus, "nMuonPlus/I");
    fTree->Branch("nMuonMinus", &nMuonMinus, "nMuonMinus/I");
    fTree->Branch("nTauPlus", &nTauPlus, "nTauPlus/I");
    fTree->Branch("nTauMinus", &nTauMinus, "nTauMinus/I");
    fTree->Branch("nKaonPlus", &nKaonPlus, "nKaonPlus/I");
    fTree->Branch("nKaonMinus", &nKaonMinus, "nKaonMinus/I");
    fTree->Branch("nKaonZero", &nKaonZero, "nKaonZero/I");
    fTree->Branch("nKaonZeroL", &nKaonZeroL, "nKaonZeroL/I");
    fTree->Branch("nKaonZeroS", &nKaonZeroS, "nKaonZeroS/I");
    fTree->Branch("secTotalE", &secTotalE, "secTotalE/D");
    fTree->Branch("secMeanE", &secMeanE, "secMeanE/D");
    fTree->Branch("secTrackLength", &secTrackLength, "secTrackLength/D");
    fTree->Branch("secStartX", &secStartX);
    fTree->Branch("secStartY", &secStartY);
    fTree->Branch("secStartZ", &secStartZ);
    fTree->Branch("secEndX", &secEndX);
    fTree->Branch("secEndY", &secEndY);
    fTree->Branch("secEndZ", &secEndZ);
    fTree->Branch("nBackward", &nBackward, "nBackward/I");
    fTree->Branch("nDecay", &nDecay, "nDecay/I");
    fTree->Branch("nCompton", &nCompton, "nCompton/I");
    fTree->Branch("nPairProd", &nPairProd, "nPairProd/I");
    fTree->Branch("nIonisation", &nIonisation, "nIonisation/I");
    fTree->Branch("nBremsstrahlung", &nBremsstrahlung, "nBremsstrahlung/I");
    fTree->Branch("nPhotoElectric", &nPhotoElectric, "nPhotoElectric/I");
    fTree->Branch("nAnnihilation", &nAnnihilation, "nAnnihilation/I");
    fTree->Branch("targetZ", &targetZ, "targetZ/I");
    fTree->Branch("targetA", &targetA, "targetA/I");
    fTree->Branch("targetPDG", &targetPDG, "targetPDG/I");
}

void RunAction::FillEvent(EventAction* evt)
{
    step_time.clear();
    step_stepLength.clear();
    step_preMomX.clear();
    step_preMomY.clear();
    step_preMomZ.clear();
    step_postMomX.clear();
    step_postMomY.clear();
    step_postMomZ.clear();

    step_trackID.clear();
    step_parentID.clear();
    step_PDG.clear();
    step_preX.clear();
    step_preY.clear();
    step_preZ.clear();
    step_postX.clear();
    step_postY.clear();
    step_postZ.clear();
    step_kinE.clear();
    step_edep.clear();
    step_proc.clear();
    step_creatorproc.clear();
    trk_birthPosX.clear();
    trk_birthPosY.clear();
    trk_birthPosZ.clear();
    trk_birthKE.clear();

    for (const auto& s : evt->steps) {
        step_trackID.push_back(s.trackID);
        step_parentID.push_back(s.parentID);
        step_PDG.push_back(s.PDG);
        step_preX.push_back(s.prePos.x());
        step_preY.push_back(s.prePos.y());
        step_preZ.push_back(s.prePos.z());
        step_postX.push_back(s.postPos.x());
        step_postY.push_back(s.postPos.y());
        step_postZ.push_back(s.postPos.z());
        step_time.push_back(s.globalTime);
        step_stepLength.push_back(s.stepLength);
        step_preMomX.push_back(s.preMom.x());
        step_preMomY.push_back(s.preMom.y());
        step_preMomZ.push_back(s.preMom.z());
        step_postMomX.push_back(s.postMom.x());
        step_postMomY.push_back(s.postMom.y());
        step_postMomZ.push_back(s.postMom.z());
        step_kinE.push_back(s.kineticE);
        step_edep.push_back(s.edep);
        step_proc.push_back(s.processName);
        step_creatorproc.push_back(s.creatorprocessName);
        trk_birthPosX.push_back(s.birthPos.x());
        trk_birthPosY.push_back(s.birthPos.y());
        trk_birthPosZ.push_back(s.birthPos.z());
        trk_birthKE.push_back(s.birthKE);
    }
}

void RunAction::EndOfRunAction([[maybe_unused]] const G4Run* run) {
#ifdef USE_CELERITAS
    celeritas::TrackingManagerIntegration::Instance().EndOfRunAction(run);
#endif
 if(fTree && fFile) {
   fFile->cd();
   fTree->Write();
   fFile->Close();
 }
}
