# Git workflow (fork gadjou/FusionSolarPlus)

- `upstream` = JortvanSchijndel/FusionSolarPlus (the original). **Never open PRs or push there.**
- `master` mirrors upstream `master` only (fast-forward, no own commits).
- `jerome` is the integration branch: it contains all features.
- New work: create a feature branch **from `master`**, open the PR **on gadjou/FusionSolarPlus with base `jerome`**, then merge it into `jerome`.
  - If the code being changed does not exist on `master` (it comes from a fork-only feature, e.g. the Live Data button from `LiveUpdate`), branch from that feature branch instead.
  - After the merge: pull `jerome` locally and delete the merged feature branch (local + remote) only when asked.
- Push via SSH: `origin` = `git@github.com:gadjou/FusionSolarPlus.git` (HTTPS password auth does not work).
- PRs via `gh` (logged in as gadjou, default repo = the fork): `gh pr create --base jerome …`, `gh pr merge`. Never pass `--repo` pointing to upstream.

# Local setup

- This working tree is the code Home Assistant actually loads (`config/custom_components/fusionsolarplus` links here). Leave the checkout on `jerome` (or a branch that contains everything in it); switching to an older branch removes features (e.g. battery control) at the next HA restart.
- Changes are only active after an HA restart; the user tests before commit/PR.
- `custom_components/fusionsolarplus/README` is the user's personal notes, ignored via `.git/info/exclude`: do not commit it.
- Upstream sync (on request): fast-forward `master` to `upstream/master`, then merge `master` into `jerome` (merge commit, no rebase/force-push).
