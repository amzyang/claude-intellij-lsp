---
description: Check or upgrade the configured JetBrains IntelliJ language server
argument-hint: "[--check | --accept-eula HASH]"
disable-model-invocation: true
---

Run the local updater from the project where intellij-lsp is installed:

```sh
python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/upgrade.py"
```

Requested arguments: $ARGUMENTS

Run the command with no arguments for an upgrade, or append `--check` for a read-only version check. For `--accept-eula HASH`, append the flag and the single 16-character lowercase hex hash only if supplied by the user to confirm that specific agreement. Reject any other arguments; never interpolate free-form input into the shell command.

Report the result. If the updater stops for changed terms, show the local EULA path and the follow-up command; do not accept terms or re-run on the user's behalf. On a successful switch, tell the user to run `/reload-plugins`. Do not change licenses, remove old builds, or update the Claude Code plugin itself.
