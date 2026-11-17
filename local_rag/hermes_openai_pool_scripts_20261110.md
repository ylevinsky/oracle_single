# Hermes OpenAI pool credential scripts — 2026-11-10

- Request: add the next OpenAI project API key to the Hermes `openai-api` credential pool without storing secrets in git.
- Repository change: `temp_scripts/hermes-credential-manager.ps1`, `set-hermes-openai-pool-credential.ps1`, and `add-hermes-openai-pool-key.ps1`. Credential reference documented in `connectios_history.md`.
- Windows flow: store the key under Credential Manager target `Hermes/OpenAI/PoolNext`, then run the add script so Hermes records `hermes auth add openai-api --type api-key`.
- Cloud-agent note: Hermes CLI can register keys on Linux directly; the Credential Manager scripts are for the Windows workstation where Hermes runs day to day.
- Security: no API keys, tokens, or credential blob contents are recorded here.
