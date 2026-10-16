# train patches

`nt.py train` fetches PR heads and merges them in manifest order. A patch here
resolves an overlap between two of them, or between a PR and main. None is
needed today.

Each JSON file records the PR head and the tree immediately before its patch.
For a conflicted merge, that is the preceding train commit's tree. For a clean
merge, it is the completed merge's tree. Changed inputs stop the train.

To refresh a conflicted merge, resolve it in the member's train branch and save
`git diff --binary AUTO_MERGE` as its patch. For a clean merge, save the fix with
`git diff --binary HEAD` before committing. Record `git rev-parse HEAD^{tree}`
and `git rev-parse refs/nt/pr/<number>` in the JSON file, then replay the train
and rerun the affected suites. Remove a patch when its PR no longer needs it.
