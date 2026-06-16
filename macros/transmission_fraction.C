// ============================================================================
// transmission_fraction.C
//
// Compute the fraction of primary beta electrons that punch all the way
// through the three-sheet silicon stack defined in
// gdml/silicon_3layer_300um.gdml.
//
// A primary (trackID == 1, parentID == 0) is counted as "through" if it
// reaches the far side of the third sheet, i.e. its trajectory crosses
// z = +0.750 mm (the back face of layer 3).
//
// Two equivalent estimators are reported:
//   1. finalZ           -- the primary's final position (simple, robust for a
//                          forward beam: a punched-through e- ends downstream).
//   2. max primary step -- the largest post-step z reached by the primary
//                          track (robust even against rare back-scatter).
//
// Usage (the prebuilt image already has ROOT):
//   root -l -b -q 'macros/transmission_fraction.C("output.root")'
// ============================================================================

#include <vector>
#include <cmath>
#include "TFile.h"
#include "TTree.h"

void transmission_fraction(const char* filename = "output.root",
                           double zBack = 0.750 /* mm, back face of layer 3 */)
{
    TFile* f = TFile::Open(filename);
    if (!f || f->IsZombie()) {
        printf("ERROR: could not open %s\n", filename);
        return;
    }
    TTree* t = (TTree*)f->Get("tree");
    if (!t) {
        printf("ERROR: TTree 'tree' not found in %s\n", filename);
        return;
    }

    // --- Branches we need ---
    double finalZ = 0.0;
    std::vector<double>* step_postZ   = nullptr;
    std::vector<int>*    step_trackID = nullptr;

    t->SetBranchAddress("finalZ",       &finalZ);
    t->SetBranchAddress("step_postZ",   &step_postZ);
    t->SetBranchAddress("step_trackID", &step_trackID);

    const Long64_t nEvents = t->GetEntries();
    Long64_t nThroughFinal = 0;   // estimator 1: finalZ
    Long64_t nThroughStep  = 0;   // estimator 2: max primary step

    for (Long64_t i = 0; i < nEvents; ++i) {
        t->GetEntry(i);

        if (finalZ > zBack) ++nThroughFinal;

        // Largest z reached by the primary track (trackID == 1).
        double zMaxPrimary = -1e30;
        for (size_t s = 0; s < step_postZ->size(); ++s) {
            if ((*step_trackID)[s] == 1 && (*step_postZ)[s] > zMaxPrimary)
                zMaxPrimary = (*step_postZ)[s];
        }
        if (zMaxPrimary > zBack) ++nThroughStep;
    }

    auto report = [nEvents](const char* label, Long64_t nThrough) {
        const double p   = nEvents ? double(nThrough) / nEvents : 0.0;
        const double err = nEvents ? std::sqrt(p * (1.0 - p) / nEvents) : 0.0;
        printf("  %-22s %8lld / %-8lld  =  %.4f  +/- %.4f   (%.2f%%)\n",
               label, (long long)nThrough, (long long)nEvents, p, err, 100.0 * p);
    };

    printf("\n=== Beta transmission through 3 x 300 um Si (back face z > %.3f mm) ===\n",
           zBack);
    report("by finalZ:",        nThroughFinal);
    report("by max primary step:", nThroughStep);
    printf("==========================================================================\n\n");

    f->Close();
}
