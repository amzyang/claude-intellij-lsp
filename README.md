# IntelliJ LSP for Claude Code

An unofficial Claude Code plugin for Java and Kotlin navigation on macOS and Linux. It connects Claude Code's LSP tool to the `lsp-router` shipped with JetBrains' standalone language server. The router selects the server by workspace root so separate sessions on the same project can reuse its index. No running IDE is required.

## Before installing

- Install a current JetBrains server bundle that includes **both** `bin/lsp-router` and `bin/intellij-server`. See [JetBrains' platform bundle manifest](https://github.com/JetBrains/intellij-lsp.nvim/blob/main/lua/intellij-lsp/server_bundles.lua) for the version, download URL template and SHA-256 checksums. The binaries are not part of this repository.
- Review the bundle's `EULA.txt`. If you accept it, supply the first 16 lowercase hex characters of that file's SHA-256 when configuring the plugin. On macOS, from the extracted bundle directory:

  ```sh
  shasum -a 256 EULA.txt | cut -c1-16
  ```

- Use `bin/intellij-server license status` to check for an active license or trial. EULA acceptance is **not** license activation. The plugin does not start a trial or sign in for you. See [JetBrains' licensing instructions](https://github.com/JetBrains/intellij-lsp.nvim#first-start).

## Install

In Claude Code:

```text
/plugin install intellij-lsp --marketplace amzyang/claude-intellij-lsp
```

Confirm the marketplace, select the installation scope, and supply the **absolute `bin` directory** and the **accepted EULA hash**. Or install from your shell:

```sh
claude plugin install intellij-lsp --marketplace amzyang/claude-intellij-lsp --scope local --config 'server_bin=/absolute/path/to/bundle/bin' --config 'accepted_eula_hash=YOUR_ACCEPTED_HASH'
```

This adapter uses stdio, leaves build-tool detection to the server, and passes `--data-sharing=none`. If the EULA changes after a bundle upgrade, review the new terms before updating the hash.

## Upgrade the language server

From a project with the plugin configured, check the build published for this machine or upgrade to it:

```text
/intellij-lsp:upgrade --check
/intellij-lsp:upgrade
```

Requires Python 3, curl, and the platform extractor (`ditto` on macOS, `tar` on Linux). The updater verifies the download against the SHA-256 in JetBrains' platform manifest, stages the new build under `~/.local/share/intellij-server`, and switches the plugin's saved `server_bin`. These options are per user and affect all installations of this plugin. Older builds stay on disk. An equal build is a no-op; a newer local build is never downgraded.

If the EULA changes, the new build stays staged and the old configuration remains active. Read the indicated `EULA.txt`; only if you accept it, run `/intellij-lsp:upgrade --accept-eula HASH` with the hash shown. After switching, run `/reload-plugins` and verify a jump. To roll back, select the old `bin` path and its matching accepted EULA hash in the plugin options, then reload. Updating the Claude Code plugin via its marketplace does not update the JetBrains server.

## Verify navigation

Use a fresh Claude Code session in a small Java or Kotlin project, with only this language provider enabled for the file type. Ask the LSP tool to go from a method call to its definition in another file. A returned location in the expected source file verifies navigation; seeing the plugin in the installed list only verifies installation. Keep other projects' Java providers unchanged while testing.
