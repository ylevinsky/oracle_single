#!/usr/bin/env node
'use strict';

// Project hook for the myoracle MCP conventions. Wired from .cursor/hooks.json:
//   preToolUse (Write/Edit)      - block creating myoracle_mcp/a.py
//   beforeShellExecution         - block running myoracle_mcp/a.py
//   postToolUse (Write)          - remind about MCP integration for .py files
// Fails open: on any parsing problem the action is allowed.

const fs = require('fs');

function readStdinJson() {
  try {
    return JSON.parse(fs.readFileSync(0, 'utf8'));
  } catch {
    return {};
  }
}

const input = readStdinJson();
const event = String(input.hook_event_name || input.event_name || input.event || '');
const toolInput = input.tool_input || input.input || {};
const filePath = String(toolInput.file_path || toolInput.path || input.file_path || input.path || '');
const command = String(input.command || toolInput.command || '');
const cwd = String(input.cwd || toolInput.cwd || '');

const norm = (s) => s.replace(/\\/g, '/').toLowerCase();
const nFile = norm(filePath);
const nCmd = norm(command);
const nCwd = norm(cwd);

const MCP_DIR = 'oracle_single/myoracle_mcp';
const BAD_FILE = '/myoracle_mcp/a.py';

function deny(userMessage, agentMessage) {
  process.stdout.write(JSON.stringify({
    permission: 'deny',
    user_message: userMessage,
    agent_message: agentMessage,
  }));
  process.exit(0);
}

function allow() {
  process.stdout.write(JSON.stringify({ permission: 'allow' }));
  process.exit(0);
}

function context(text) {
  process.stdout.write(JSON.stringify({ additional_context: text }));
  process.exit(0);
}

let kind;
if (/shell/i.test(event)) kind = 'shell';
else if (/pretooluse/i.test(event)) kind = 'pre';
else if (/posttooluse/i.test(event)) kind = 'post';
else if (command && !filePath) kind = 'shell';
else if (filePath) kind = 'pre';
else kind = 'other';

if (kind === 'shell') {
  const runsBadFile =
    nCmd.includes(MCP_DIR + '/a.py') ||
    (/a\.py/.test(nCmd) && nCwd.endsWith('/myoracle_mcp'));
  if (runsBadFile) {
    deny(
      'Blocked: myoracle_mcp/a.py must not be created or run. The RH connection check is the check_saved_oracle_connectivity tool.',
      'The command references myoracle_mcp/a.py, which is banned by project rules. Use the appropriate @mcp.tool() from the myoracle MCP server instead.',
    );
  }
  allow();
}

if (kind === 'pre') {
  if (nFile.endsWith(BAD_FILE)) {
    deny(
      'Blocked: myoracle_mcp/a.py must not be created. Put the code in a named module under oracle_single/myoracle_mcp/ and register a @mcp.tool() for it.',
      'Creating myoracle_mcp/a.py is banned by project rules. Follow the add-myoracle-tool skill workflow instead.',
    );
  }
  allow();
}

if (kind === 'post') {
  if (!nFile.endsWith('.py')) allow();

  if (nFile.includes(MCP_DIR)) {
    context(
      'A Python file was written inside oracle_single/myoracle_mcp/. Unless it is already done: import it from server.py, register one @mcp.tool() per user-facing action, document it in oracle_single/myoracle_mcp/README.md, and add or extend a test in test_server.py when it can run without a live database.',
    );
  } else {
    context(
      'A Python file was written outside oracle_single/myoracle_mcp/. Generated Python belongs in the local MCP server: move the logic into a module under oracle_single/myoracle_mcp/, register a @mcp.tool() for it, and do not leave a one-off script in ORCL/ or a temp path as the only way to run the code. If this file is unrelated (test fixture, setup script, etc.), ignore this reminder.',
    );
  }
}

allow();