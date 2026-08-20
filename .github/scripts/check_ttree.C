// Open an ntuple with REAL ROOT and insist it is a classic TTree.
//
// This is the check that would have caught the RNTuple regression: uproot 5.7
// made `file["tree"] = data` write an RNTuple, which uproot reads back happily
// -- so every Python-side test still passed -- while `root output.root` said
//
//     Error in <TKey::ReadObj>: Unknown class ROOT::RNTuple
//
// Usage:  root -l -b -q '.github/scripts/check_ttree.C("out/output.root")'
// Exits non-zero (and says why) unless the file holds a readable TTree.
void check_ttree(const char* path, Long64_t expect_entries = -1) {
    TFile* f = TFile::Open(path);
    if (!f || f->IsZombie()) {
        printf("FAIL: cannot open %s\n", path);
        gSystem->Exit(1);
    }
    TObject* obj = f->Get("tree");
    if (!obj) {
        printf("FAIL: no object named 'tree' in %s\n", path);
        f->ls();
        gSystem->Exit(1);
    }
    printf("[check_ttree] %s: 'tree' is a %s\n", path, obj->IsA()->GetName());
    TTree* t = dynamic_cast<TTree*>(obj);
    if (!t) {
        printf("FAIL: 'tree' is %s, not a TTree -- plain ROOT cannot read it\n",
               obj->IsA()->GetName());
        gSystem->Exit(1);
    }
    const Long64_t n = t->GetEntries();
    printf("[check_ttree] entries: %lld, branches: %d\n",
           n, t->GetListOfBranches()->GetEntries());
    if (expect_entries >= 0 && n != expect_entries) {
        printf("FAIL: expected %lld entries, found %lld\n", expect_entries, n);
        gSystem->Exit(1);
    }
    // the branches every consumer needs, and one real read of each kind
    const char* required[] = {"eventID", "primaryE", "totalEdep", "trk_pdg"};
    for (auto name : required) {
        if (!t->GetBranch(name)) {
            printf("FAIL: missing branch %s\n", name);
            gSystem->Exit(1);
        }
    }
    if (n > 0 && t->Draw("totalEdep", "", "goff") < 0) {
        printf("FAIL: could not read totalEdep\n");
        gSystem->Exit(1);
    }
    // process names live in an int-code branch plus the legend tree (uproot
    // cannot write vector<string> into a TTree); either encoding is fine here,
    // but an encoded file must carry its legend
    if (t->GetBranch("trk_creatorProcess")) {
        TTree* legend = dynamic_cast<TTree*>(f->Get("gdmltp_strings"));
        TBranch* b = t->GetBranch("trk_creatorProcess");
        const bool coded = TString(b->GetTitle()).Contains("/I")
                        || TString(b->GetTitle()).Contains("[n");
        printf("[check_ttree] trk_creatorProcess title: %s | legend: %s\n",
               b->GetTitle(), legend ? "present" : "absent");
        if (coded && !legend) {
            printf("FAIL: coded process names with no gdmltp_strings legend\n");
            gSystem->Exit(1);
        }
    }
    printf("[check_ttree] OK: %s holds a classic TTree\n", path);
    f->Close();
}
