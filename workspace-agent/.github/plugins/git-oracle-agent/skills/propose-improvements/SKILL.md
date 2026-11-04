---
name: propose-improvements
description: Propose improvements as dated step files and implement them step by step after approval. Use when the user asks for improvements, a check with proposals, or an improvement plan.
---

# Propose Improvements

## Instructions

1. Check the target functionality first (code + live state via existing MCP tools when Oracle work is involved; never open saved connections from one-off scripts when a tool exists).
2. Propose every improvement set as a new file named `improvement_<YYYY-MM-DD>_<functionality_name>_steps.md` in the workspace root:
   - `<YYYY-MM-DD>` is today's date (e.g. `2026-10-06`).
   - `<functionality_name>` is lowercase with hyphens or underscores (e.g. `synchronization`).
   - Never reuse the generic `improvement_steps.md` for a proposal; it is only an index linking to dated files.
3. Each proposal file must contain:
   - Source of findings (files, tools, queries used).
   - Current-state summary.
   - Numbered steps with `[ ]` checkboxes, each with its own done-criteria.
   - Explicit approval gate: implement step by step only after the user approves (whole plan or per step).
4. Update `improvement_steps.md` index to link the new dated file.
5. Show the user the file link and enumerate every step in chat.
6. After approval, implement strictly step by step:
   - One step at a time, in order unless the user reorders.
   - Python/MCP work follows the `add-myoracle-tool` skill (module under `oracle_single/myoracle_mcp/`, one `@mcp.tool()` in `server.py`, README entry, `test_server.py` coverage when possible without live DB).
   - Stop after each step (or agreed batch) and report status + done-criteria result before continuing.
7. Never start implementation before approval. If the user says "implement", confirm which steps are approved first.

## Examples

**Example 1:**
User: "check synchronization process and propose improvements"
Response: create `improvement_2026-10-06_synchronization_steps.md` with 10 checkbox steps, link it in `improvement_steps.md`, list Steps 1-10 in chat, wait for approval.

**Example 2:**
User: "approve steps 1-2"
Response: implement Step 1, verify its done-criteria, report, then proceed to Step 2 only.

## Performance Notes

- Keep proposal files focused; split efforts by functionality, one dated file per functionality per day.
- Prefer existing MCP tools for checks over new scripts.

## Troubleshooting

- Date unknown: use the workspace/system date at creation time, never a guessed date.
- Functionality name unclear: derive it from the checked process or asked topic (e.g. `synchronization`, `backup`, `alert-log`).
- User asks for `improvement_steps.md` directly: create/update it only as the index, and put the actual proposal in the dated file.
