# Handled Error: Codex SSL Certificate Verification and Unsupported Model Configuration

## Target Scope
Codex CLI / VS Code Agent on Windows Workstation

## User Request
Update SSL certificate; resolve Codex errors.

## Error Encountered
1. TLS / SSL Certificate trust issues with python, uv, and MCP servers when communicating over HTTPS/WSS in enterprise environment.
2. Codex execution error:
   ERROR: {"type":"error","status":400,"error":{"type":"invalid_request_error","message":"The 'gpt-5.3-codex-spark' model is not supported when using Codex with a ChatGPT account."}}

## Verified Solution and Outcome
1. Generated updated root CA certificate bundle C:\Users\brillix\.ssl\cacert.pem (632 certificates) consolidating Windows Update root SST, Windows Machine and User Root/CA stores, and updated modern CAs.
2. Updated certifi cacert.pem across all local Python and uv environments (including mem0-local, oracle-oci MCP servers, and oracle_connectivity_mcp).
3. Configured user environment variables SSL_CERT_FILE, REQUESTS_CA_BUNDLE, CURL_CA_BUNDLE, and NODE_EXTRA_CA_CERTS pointing to C:\Users\brillix\.ssl\cacert.pem.
4. Updated C:\Users\brillix\.codex\config.toml to use supported model gpt-5.6-terra and removed unsupported service_tier = "priority".
5. Verified Codex doctor health checks and ran codex exec successfully.
