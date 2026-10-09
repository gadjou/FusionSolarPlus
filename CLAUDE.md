# Git workflow (fork gadjou/FusionSolarPlus)

- `upstream` = JortvanSchijndel/FusionSolarPlus (the original). **Never open PRs or push there.**
- `master` mirrors upstream `master` only (fast-forward, no own commits).
- `jerome` is the working/integration branch.
- New work: create a feature branch from `jerome`, open the PR **on gadjou/FusionSolarPlus with base `jerome`**, then merge it into `jerome`.
- Upstream sync (on request): fast-forward `master` to `upstream/master`, then merge `master` into `jerome` (merge commit, no rebase/force-push).
