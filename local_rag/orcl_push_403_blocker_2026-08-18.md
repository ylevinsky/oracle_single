# Git push blocker: ORCL Azure DevOps HTTP 403

- Request and scope: push commit `db66c6a Add generic Oracle plan and index tools` from `C:\git\ORCL` to `origin/master`.
- Exact error: `fatal: unable to access 'https://dev.azure.com/Essence-grp/Operations/_git/ORCL/': The requested URL returned error: 403`.
- Outcome: no remote branch was changed. The local commit remains present.
- Verified blocker: Azure DevOps rejected the currently configured Git credential or identity for this repository. The error is authorization-level, not a network or Git commit failure.
- Safe resolution: authenticate Git Credential Manager as an Azure DevOps identity with Contribute permission to `Essence-grp/Operations/ORCL`, then retry `git push origin master`. Do not remove an existing Credential Manager entry without explicit approval.