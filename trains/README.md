# train patches

`nt.py train` fetches PR heads and merges them in manifest order. These patches
resolve the API overlaps and repair the legacy serial test fixture.

Each JSON file records the PR head and the tree immediately before its patch.
For a conflicted merge, that is the preceding train commit's tree. For a clean
merge, it is the completed merge's tree. Changed inputs stop the train.

API #61 keeps #70's server-owned IDs, serialized file allocation, and conflict
checks while adding the REST bridge. It also supplies record zone IDs in
delegation responses. API #68 adds the delegation edge introduced by #61.
NicTool #365 uses today's serial date in its test fixture.

To refresh a conflicted merge, resolve it in the member's train branch and save
`git diff --binary AUTO_MERGE` as its patch. For a clean merge, save the fix with
`git diff --binary HEAD` before committing. Record `git rev-parse HEAD^{tree}`
and `git rev-parse refs/nt/pr/<number>` in the JSON file, then replay the train
and rerun the affected suites. Remove a patch when its PR no longer needs it.
