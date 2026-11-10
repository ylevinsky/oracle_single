## oracle_single Git remote

- Connection type: HTTPS Git remote
- Reuse details: remote `origin` at `github.com/ylevinsky/oracle_single`, branch `main`; verified 2026-09-15 by pushing commit `927e103`.
- Credential reference: Git Credential Manager for the signed-in GitHub account; no token is stored in this file.

## Hermes OpenAI credential pool (Windows)

- Purpose: hold the **next** OpenAI API key to register with [Hermes Agent](https://hermes-agent.nousresearch.com/docs/user-guide/features/credential-pools) (`openai-api` provider) without committing secrets.
- Credential target: `Hermes/OpenAI/PoolNext` in Windows Credential Manager (generic credential).
- Setup: `temp_scripts\set-hermes-openai-pool-credential.ps1` (secure prompt).
- Register with Hermes: `temp_scripts\add-hermes-openai-pool-key.ps1` (reads the target, runs `hermes auth add openai-api`).
- Verify: `hermes auth list openai-api`.
- No API key values are stored in this repository.
