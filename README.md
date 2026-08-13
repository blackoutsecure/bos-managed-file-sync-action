# Blackout Secure Managed File Sync

Copyright © 2025-2026 Blackout Secure | Apache License 2.0

[![Marketplace](https://img.shields.io/badge/GitHub%20Marketplace-blue?logo=github)](https://github.com/marketplace/actions/blackout-secure-managed-file-sync)
[![GitHub release](https://img.shields.io/github/v/release/blackoutsecure/bos-managed-file-sync-action)](https://github.com/blackoutsecure/bos-managed-file-sync-action/releases)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue)](LICENSE)
[![Made by BlackoutSecure](https://img.shields.io/badge/made%20by-BlackoutSecure-1f1f1f)](https://github.com/blackoutsecure)

A drop-in composite GitHub Action that **reads JSON config → resolves a service
registry → reconciles your repo's managed files → reports or fixes drift**.

Synchronization is deliberately one-way. The merged catalog, service
definitions, and templates are the **source**; the checked-out repository is
the **destination**. `managed_file_sync.direction` defaults to
`source-to-destination`, which is the only supported value. Reverse and
bidirectional sync fail validation before any file is changed.

Everything in one Marketplace install: canonical dotfiles, managed blocks
inside files you also hand-edit, init-if-missing scaffolding, dry-run
previews, and a CI drift gate. Marketplace defaults are vendor neutral, and
any repo or org can extend them with its own services — no fork required.

## ✨ Features

- **Four sync modes** — `block` rewrites only the region between markers in a
  file you otherwise own, `file` overwrites a canonical file wholesale, `init`
  creates a file only when it is absent and never touches it again, and
  `absent` retires a file that a service no longer manages.
- **Managed blocks** — canonical content lives between
  `>>> managed-file-sync:<service> >>>` and `<<< managed-file-sync:<service> <<<`
  markers, written with the comment syntax of the target file type. The marker
  namespace is configurable, so the action can also manage blocks written by
  another tool.
- **Config-driven service registry** — services are pure data. The built-in
  marketplace registry covers common services; repos extend or override it via
  `service_definitions`.
- **Dry run + drift gate** — `dry_run` previews changes without writing;
  `fail_on_drift` turns the preview into a CI gate that fails with an exact
  list of out-of-sync files. Every change is reported as a unified diff in the
  job log, so a review needs no local checkout.
- **Bundles** — a service can `include` other services, so a repo opts into a
  whole standard with one name.
- **Actionable outputs** — `changed`, `changed_count`, `changed_files`, and
  `changed_files_json` make it trivial to open a pull request only when
  something actually moved.
- **Job summary** — GitHub Actions runs receive a concise audit of resolved
  configuration, totals, service-level outcomes, and every managed file.
- **Pure-stdlib Python core** — no third-party runtime dependency at all. The
  composite Action invokes its bundled source directly, without a package
  install or online build step.

## 📋 Prerequisites

- GitHub-hosted Linux runner (`ubuntu-latest` or newer) — the action installs
  Python via `actions/setup-python` automatically.
- `actions/checkout` before the action runs, so there is a working tree to
  reconcile.
- For **drift checks**: nothing beyond the default `contents: read`.
- For **committing fixes**: `contents: write` (and `pull-requests: write` if
  you open a PR with the changes).

## Quick start 🚀

Create `.github/bos-universal-config.json` in the destination repository:

```json
{
  "managed_file_sync": {
    "direction": "source-to-destination",
    "services": ["common", "lf_line_endings", "dependabot_actions", "dotfiles"]
  }
}
```

```yaml
name: Managed file sync

on:
  schedule:
    - cron: '29 14 * * 1'   # weekly Monday 14:29 UTC
  workflow_dispatch:

permissions:
  contents: read

jobs:
  sync:
    runs-on: ubuntu-latest
    permissions:
      contents: write
      pull-requests: write
    steps:
      - uses: actions/checkout@v4

      - id: sync
        uses: blackoutsecure/bos-managed-file-sync-action@v1

      - if: steps.sync.outputs.changed == 'true'
        uses: peter-evans/create-pull-request@v6
        with:
          title: 'chore: sync managed files'
          commit-message: 'chore: sync managed files'
          branch: chore/managed-file-sync
```

That's it. The repo config and conventional optional global config are
auto-discovered, so the workflow does not repeat config paths. For ad hoc runs,
the `services` input can still override the configured service list.

### Drift check on pull requests

```yaml
name: Managed file drift

on:
  pull_request:

permissions:
  contents: read

jobs:
  drift:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: blackoutsecure/bos-managed-file-sync-action@v1
        with:
          dry_run: 'true'
          fail_on_drift: 'true'
```

The job fails with a list of out-of-sync files and never writes to the working
tree.

### Version pinning

Pick a `uses:` ref shape based on how strict your supply-chain posture needs to
be. All three forms are supported equally.

| Form | Example | When to use |
| --- | --- | --- |
| Floating major (default) | `blackoutsecure/bos-managed-file-sync-action@v1` | Friendly default. Auto-tracks every `v1.x.y` release as we ship fixes and service updates. Recommended for most callers. |
| Immutable tag | `blackoutsecure/bos-managed-file-sync-action@v1.0.0` | Pin to a specific release. Byte-identical managed content across runs; requires manual bumps. Recommended when a surprise service change would break a pipeline. |
| SHA-pinned | `blackoutsecure/bos-managed-file-sync-action@<40-char-sha> # v1.0.0` | Strictest. Survives even a malicious tag-move on this repo. Recommended for regulated / high-security callers. Use Dependabot's `package-ecosystem: github-actions` to keep the pin current. |

The SHA for any tag is `git rev-list -n 1 v1.0.0` against this repo, or the
`commit` field of the GitHub Release JSON.

## ⚙️ Action inputs

<!-- BEGIN action-inputs -->
| Input | Default | Description |
| --- | --- | --- |
| `use_global_config` | `auto` | `auto` loads the org/hub-level global config when present. `true` requires it; `false` disables it. |
| `global_config_path` | `.github/blackout-secure-managed-file-sync-global-config.json` | Org/hub-level config path. Auto-discovered by default and merged as the first tier; repo config (config_path) overrides it. |
| `config_path` | _(none)_ | Path to the repo config file. Defaults to auto-discovery of `.github/bos-universal-config.json` (preferred), `bos-universal-config.json`, `managed-file-sync.json`, or `.managed-file-sync.json`. |
| `global_config_json` | _(none)_ | Inline JSON object to merge with the org/hub-level config before the repo config is applied. Useful for one-off workflow runs without creating a file. |
| `config_json` | _(none)_ | Inline JSON object to merge with the repo/global config. Useful for ad hoc workflow runs without creating a config file. |
| `services` | _(none)_ | Comma or space separated list of services to sync. Overrides the service list in the config. Use `*` to select every configured file service. |
| `managed_files_path` | _(none)_ | Optional workflow override for the managed template directory used by `content_file` entries. When empty, the merged config value is used, falling back to `.github/managed-files`. |
| `workload_arch` | `auto` | Runner workload selection for built-in variables: `auto`, `x64`, `arm64`, or `default`. `auto` uses `RUNNER_ARCH` when available. |
| `working_directory` | `.` | Repository root to sync. |
| `dry_run` | `false` | `true` to report what would change without writing any file. |
| `fail_on_drift` | `false` | `true` to exit non-zero when managed files are out of sync. |
| `show_diff` | `true` | `true` to print a unified diff for every changed file in the job log. |
| `python_version` | `3.12` | Python version installed on the runner for the sync step. |
<!-- END action-inputs -->

> [!NOTE]
> The table above is auto-generated from `action.yml` by
> [scripts/render_readme_inputs.py](scripts/render_readme_inputs.py). Edit
> `action.yml` and run `python3 scripts/render_readme_inputs.py --write`.

## 📤 Action outputs

<!-- BEGIN action-outputs -->
| Output | Description |
| --- | --- |
| `changed` | `true` when managed files changed (or would change in dry-run mode). |
| `changed_count` | Number of changed files. |
| `changed_files` | Newline separated list of changed file paths. |
| `changed_files_json` | JSON array of changed file paths. |
<!-- END action-outputs -->

Exit behaviour: the step exits `0` when the tree is in sync, `1` when drift is
detected with `fail_on_drift: 'true'`, and `2` on a config error.

## Job summary

When run in GitHub Actions, the action writes a Job Summary with the resolved
configuration, success/failure totals, service-level counts, and a file-by-file
result table. In a dry run, a file that would change is marked **Failure** so
drift is immediately visible; files already in sync are marked **Success**. In
apply mode, a successfully created, updated, or deleted file is marked
**Success**.

## 🏗️ Configuration inheritance and layering

This action uses a **four-tier config cascade** with switchable marketplace
defaults, org-wide defaults, repo-specific overrides, and CI-level workflow
inputs. The default sync direction and runner fallback are set in the runtime
defaults so they are easy to override without needing a special locked tier.

### Configuration tiers

The config is merged in cascade order:

1. **Tier 1: Marketplace config** (built-in, default ON)  
   Shipped with the action: best-practice services (`common`, `lf_line_endings`,
  `markdownlint`, `dependabot_actions`, `dotfiles`) and a managed note.
  Explicitly enable or disable it with
   `use_marketplace_config: true|false` in any tier above it. Typically disabled
   only for advanced customization.

2. **Tier 2: Org-level global config** (`use_global_config` + `global_config_path` inputs)  
   Org-wide defaults: additional services, org-specific marker namespace (rare),
   org-wide managed note, shared variables (org name, license, support email).
  The conventional `.github/blackout-secure-managed-file-sync-global-config.json`
  path is loaded automatically when present. Set `use_global_config: 'true'`
  to require the file or `'false'` to disable discovery.

3. **Tier 3: Repo-specific config** (`config_path` input)  
   Repository overrides: additional services, repo-specific variables, local
  metadata, service exclusions. Auto-discovered as
  `.github/bos-universal-config.json` (preferred), then
  `bos-universal-config.json`, `managed-file-sync.json`, or
  `.managed-file-sync.json`. Optional; repos inherit from marketplace + global
   if not present.

4. **Tier 4: Workflow input overrides** (`services` input)  
   CI-level control: override the service list for a specific workflow run
   without touching config files. Use for per-branch or per-environment
   customization.

### Merge strategy

- **Scalars** (strings, numbers, booleans): lower tiers override upper tiers.
- **Objects** (dicts): deep-merged, so you can override a single field without
  repeating the whole object.
- **Services arrays**: appended by default across marketplace → global → repo,
  with de-duplication in order.
- **Service array override mode**: set `use_marketplace_services: false` in a
  tier to replace inherited `services` instead of appending.
- **Disabling marketplace**: set `use_marketplace_config: false` in org or repo
  config to merge only global+repo+workflow.

### Recommended file paths

- **Marketplace config**: `src/sync_kit/blackout-secure-managed-file-sync-marketplace-config.json` (switchable defaults)
- **Org global config**: `.github/blackout-secure-managed-file-sync-global-config.json` (optional, hub-authored and present in the destination checkout)
- **Repo config**: `.github/bos-universal-config.json` (preferred, optional per repo)
- **Managed templates path**: `.github/managed-files` (default)

### Examples

#### Example 1: Marketplace only (default)

No configs needed; the marketplace defaults apply:

```yaml
- uses: blackoutsecure/bos-managed-file-sync-action@v1
```

Result: `common`, `lf_line_endings`, `markdownlint`, `dependabot_actions`,
and `dotfiles` are synced.

#### Example 2: Marketplace + Org config

Create `.github/blackout-secure-managed-file-sync-global-config.json`:

```json
{
  "managed_file_sync": {
    "direction": "source-to-destination",
    "services": ["common", "lf_line_endings", "markdownlint", "dependabot_actions", "dotfiles"],
    "variables": {
      "org_name": "my-org",
      "support_email": "platform-team@my-org.com",
      "license": "Apache-2.0"
    }
  }
}
```

Workflow:

```yaml
- uses: blackoutsecure/bos-managed-file-sync-action@v1
```

Result: marketplace config merged with org config (services append by default). All
destination repos containing the hub-managed global config get `dotfiles` and
the org variables automatically.

#### Example 3: Marketplace + Org + Repo config

Same as above, plus create `.github/bos-universal-config.json` in the repo:

```json
{
  "managed_file_sync": {
    "services": ["common", "lf_line_endings", "markdownlint", "dependabot_actions", "dotfiles", "prettier"],
    "variables": {
      "project_name": "my-typescript-project"
    }
  }
}
```

Workflow:

```yaml
- uses: blackoutsecure/bos-managed-file-sync-action@v1
```

Result: marketplace → org → repo merged (services append by default; objects deep-merge).
This repo gets `prettier` in addition to org services, with its own project name
variable.

#### Minimal managed kicker call

Once both config files use their conventional paths, a hub-managed kicker only
needs runtime behavior inputs:

```yaml
- uses: blackoutsecure/bos-managed-file-sync-action@v1
  with:
    fail_on_drift: ${{ (inputs.mode || 'commit') == 'check' }}
    show_diff: 'true'
```

The kicker remains responsible for its triggers, permissions, checkout, and
commit/check flow. The action reads sources and writes destinations inside that
checkout; automatic discovery does not fetch a config or template from another
repository. A hub that owns the policy must publish or install its canonical
global config into the destination checkout at the conventional path.

### Precedence rules

When a field is defined in multiple tiers:

- **Services array**: appended by default (tier 0 + tier 1 + tier 2), with
  duplicates removed while preserving first-seen order.
  To replace inherited services instead, set `use_marketplace_services: false`
  in that tier, for example
  `{"use_marketplace_services": false, "services": ["prettier"]}`.
- **Service exclusions**: use `exclude_services` (or `disabled_services`) to
  drop resolved services from the final set. This is how you remove a
  marketplace service for a specific global config or repo config.
- **Variables object**: merged. Tier 2 adds to tier 0's variables.
- **Marker namespace**: tier 2 replaces tier 0 (rare).
- **Managed note**: tier 1 (org) often sets this; tier 2 can override.

Concrete example (global exclusion + repo append):

Global config (`.github/blackout-secure-managed-file-sync-global-config.json`):

```json
{
  "managed_file_sync": {
    "services": ["dotfiles"],
    "exclude_services": ["markdownlint"]
  }
}
```

Repo config (`.github/bos-universal-config.json`):

```json
{
  "managed_file_sync": {
    "services": ["prettier"]
  }
}
```

Resulting enabled services:

- Marketplace defaults start as: `common`, `lf_line_endings`, `markdownlint`, `dependabot_actions`
- Global appends: `dotfiles`
- Repo appends: `prettier`
- Global exclusion removes `markdownlint`
- Final set: `common`, `lf_line_endings`, `dotfiles`, `prettier`

If the repo wants to replace inherited services instead of appending, set:

```json
{
  "managed_file_sync": {
    "use_marketplace_services": false,
    "services": ["prettier"]
  }
}
```

### Disabling marketplace config

To use only org + repo configs without marketplace best practices:

```json
{
  "managed_file_sync": {
    "use_marketplace_config": false,
    "services": []
  }
}
```

Set this in org or repo config. This is rarely needed; marketplace defaults are
conservative and safe. Define replacement services in the global or repo
`service_definitions` object before enabling them.

## 📦 Built-in services

Every service below ships with the action and can be overridden per repo. The
registry is deliberately vendor neutral — org-specific services belong in your
global or repo config.

| Service | Mode | Managed path(s) |
| --- | --- | --- |
| `common` | block | `.gitignore` |
| `lf_line_endings` | block | `.gitattributes` |
| `dependabot_actions` | block | `.github/dependabot.yml` |
| `dotfiles` | init | `.editorconfig` |
| `codeowners` | init | `.github/CODEOWNERS` |
| `license` | init | `LICENSE` |
| `notice_apache2` | init | `NOTICE` |
| `shellcheck` | block | `.shellcheckrc` |
| `prettier` | block + init | `.prettierignore`, `.prettierrc.json` |
| `markdownlint` | file | `.markdownlint.json` |
| `managed_file_sync_workflow` | file | `.github/workflows/managed-file-sync.yml` |
| `baseline` | bundle | `common`, `lf_line_endings`, `dotfiles`, `markdownlint`, `dependabot_actions` |

List the resolved service registry at any time:

```bash
bos-sync services
```

### Managing the sync workflow

Enable `managed_file_sync_workflow` to have the service manage the workflow
that invokes this action. It is deliberately opt-in and is not part of
`baseline`, because it owns a workflow file and its trigger/commit policy.

```json
{
  "managed_file_sync": {
    "services": ["managed_file_sync_workflow"]
  }
}
```

The managed workflow writes to `.github/workflows/managed-file-sync.yml`. Pull
requests run a dry-run drift check; scheduled runs and `workflow_dispatch` in
`commit` mode apply and commit updates. A manual `check` run only reports
drift. Override this service in global or repo config when your organization
needs different triggers, permissions, action pins, or commit behavior.

## 🧩 Managed blocks

Block services rewrite only the region between markers, using the comment
syntax of the target file type:

```gitignore
# untouched, repo-specific entries
tmp/

# >>> managed-file-sync:common >>>
node_modules/
dist/
# <<< managed-file-sync:common <<<
```

- Missing markers → the block is appended and the file created as needed. When
  a file needs a root structure to be valid (`.github/dependabot.yml` needs
  `version: 2` / `updates:`), the service declares a `scaffold` that is written
  once at creation time and never touched again.
- A start marker with no end marker → the run **fails** rather than guessing
  where the block ends.
- Markdown, HTML, and XML use wrapping comments
  (`<!-- >>> managed-file-sync:docs >>> -->`).
- Blocks belonging to another namespace are never touched, so this action can
  coexist with other file-syncing tools in the same file.
- Set `managed_note` to stamp a provenance line under each start marker (and as
  a header on whole-file / init targets). Formats without comment syntax, such
  as JSON, are skipped automatically.

## 📝 Config schema

Per-repo policy lives in the `managed_file_sync` section of a JSON config file
— `.github/bos-universal-config.json` (preferred), `bos-universal-config.json`,
`managed-file-sync.json`, or `.managed-file-sync.json`. A document without that
key is treated as the section itself. Every field is optional and unknown keys
are ignored, so newer versions can extend the schema without breaking older
callers.

A minimal repo config:

```json
{
  "managed_file_sync": {
    "services": ["common", "lf_line_endings", "dotfiles", "codeowners"],
    "variables": {
      "owner": "Example Org",
      "codeowner": "@example-org/platform-team"
    }
  }
}
```

Services can also be toggled with an object, which is convenient for generated
configs:

```json
{
  "managed_file_sync": {
    "services": { "common": true, "prettier": false },
    "disabled_services": ["license"]
  }
}
```

| Key | Type | Description |
| --- | --- | --- |
| `direction` | string | One-way sync direction. Defaults to and only accepts `source-to-destination`; reverse and bidirectional modes are rejected. |
| `services` | array or object | Enabled services. `["*"]` enables every file-managing service in the registry. |
| `use_marketplace_services` | boolean | Controls array merge behavior for `services` at this tier. Default `true` appends to inherited services; `false` replaces inherited services. |
| `exclude_services` | array | Services to remove from the resolved set for this scope (global or repo). |
| `disabled_services` | array | Names removed after resolution — useful with `*` and bundles. |
| `service_definitions` | object | Repo-local services. Keys use letters, numbers, `.`, `_`, or `-`; same-named entries override marketplace/global services. |
| `managed_files_path` | string | Base path for managed templates (`content_file` lookup). Default `.github/managed-files`. Set it in global config for org-wide defaults, or in repo config for local override. |
| `variables` | object | Values for `{{token}}` placeholders in service content. |
| `marker_namespace` | string | Marker namespace for managed blocks. Uses letters, numbers, `.`, `_`, or `-`; default `managed-file-sync`. |
| `managed_note` | string or array | Provenance note written into managed blocks and file headers. Off by default. |

Built-in variables: `{{year}}`, `{{owner}}`, `{{repo}}`, and `{{repository}}`
(from `GITHUB_REPOSITORY`).

`{{project_name}}` is also built-in and defaults to the repository name
(`{{repo}}`) when not specified/overridden in config variables.

Runner built-ins are also available for template rendering:

- `{{DEFAULT_RUNNER}}`
- `{{RUNNER_X64}}`
- `{{RUNNER_ARM64}}`
- `{{fallback_default_runner}}`
- `{{WORKLOAD_ARCH}}`
- `{{SELECTED_RUNNER}}`

Runner fallback behavior:

- Source env vars: `DEFAULT_RUNNER`, `RUNNER_X64`, `RUNNER_ARM64`
- If any value is missing, empty, or invalid, it falls back to
  `{{fallback_default_runner}}` which defaults to `ubuntu-latest`.
- Valid values are either a single runner label (for example
  `ubuntu-latest`) or a JSON array string (for example
  `["ubuntu-latest"]`).

Workload selection:

- Set action input `workload_arch` to `auto` (default), `x64`, `arm64`, or
  `default`.
- `auto` uses `RUNNER_ARCH` to pick `{{RUNNER_X64}}` or `{{RUNNER_ARM64}}`.
- Invalid or unavailable runtime arch falls back to `{{DEFAULT_RUNNER}}`.
- `{{SELECTED_RUNNER}}` is the final resolved runner value for templates.

Unknown tokens are left untouched rather than blanked out.

### Example service definitions

Add a `service_definitions` entry:

```json
{
  "managed_file_sync": {
    "services": ["common", "security_policy", "release_config"],
    "service_definitions": {
      "security_policy": {
        "mode": "init",
        "description": "Vulnerability reporting policy.",
        "files": [
          {
            "path": "SECURITY.md",
            "content_lines": [
              "# Security Policy",
              "",
              "Report vulnerabilities to security@example.com."
            ]
          }
        ]
      },
      "release_config": {
        "mode": "file",
        "files": [
          { "path": ".releaserc.json", "content_file": "templates/releaserc.json" }
        ]
      }
    }
  }
}
```

| Field | Description |
| --- | --- |
| `mode` | `block` (default), `file`, `init`, or `absent`. Can be overridden per file. |
| `includes` | Makes the service a bundle: it expands to the listed services instead of managing files. |
| `description` | Shown by `bos-sync services`. |
| `files[].path` | Repo-relative path. Absolute paths and `..` are rejected. |
| `files[].content` | String, or array of lines. |
| `files[].content_lines` | Array of lines, joined with newlines. |
| `files[].scaffold` | Block mode only: root structure written once when the file is created. |
| `files[].content_file` | Template file source for service definitions, resolved from `managed_files_path` (default `.github/managed-files`). |
| `files[].comment_prefix` | Override marker comment syntax. Use `open\|close` for wrapping styles. |

### Managed files base path and service paths

Use `.github/managed-files` as the default template base path unless your org
already has a standard location.

Service paths can be handled in two ways:

- Use built-in services and their default managed file paths.
- Define your own `service_definitions` with explicit `files[].path` values.

Built-in destinations are listed once in [Built-in services](#-built-in-services).

Built-in config layers are bundled in:

- [src/sync_kit/blackout-secure-managed-file-sync-marketplace-config.json](src/sync_kit/blackout-secure-managed-file-sync-marketplace-config.json)

## 💻 Local usage (CLI)

The kit also ships a standalone `bos-sync` CLI for local triage or non-GitHub
CI:

```bash
python -m pip install \
  'git+https://github.com/blackoutsecure/bos-managed-file-sync-action.git@v1.0.0'

# List the resolved service registry
bos-sync services --root .

# Validate config without touching any file
bos-sync validate --root .

# Preview, then apply
bos-sync apply --root . --dry-run
bos-sync apply --root . --services common,dotfiles

# CI drift gate (dry-run + non-zero exit on drift)
bos-sync check --root .
bos-sync check --root . --no-diff       # file list only, no diffs

# Use managed templates from a custom directory (default is .github/managed-files)
bos-sync apply --managed-files-path .github/managed-files
```

Exit codes: `0` in sync, `1` drift detected, `2` config error.

## 📁 Managed templates directory

Recommended default path: `.github/managed-files`.

Why this path is recommended:

- Keeps sync templates near repo governance files in `.github`.
- Avoids cluttering the repository root.
- Works naturally with repo/global config layering.

For repo/global `service_definitions`, `content_file` sources resolve from
`managed_files_path`, which defaults to `.github/managed-files`.

Destination is always defined per service file via `files[].path`.
Source content comes from the merged built-in/global/repo service definition:
inline content or `content_file` resolved beneath `managed_files_path`. The
action never writes to that source or pushes changes to another repository.

You can set this path in config:

```json
{
  "managed_file_sync": {
    "managed_files_path": ".github/managed-files",
    "services": ["release_config"]
  }
}
```

Or override in workflow input:

```yaml
- uses: blackoutsecure/bos-managed-file-sync-action@v1
  with:
    managed_files_path: '.github/managed-files'
```

Recommended baseline:

- Set `managed_files_path` in repo/global config to `.github/managed-files`.
- Keep reusable `content_file` templates under `.github/managed-files/**`.
- Keep the optional global config at
  `.github/blackout-secure-managed-file-sync-global-config.json` for automatic
  discovery. Use `use_global_config: 'true'` only when absence must fail.

## 🔐 Security and safety notes

- **Least privilege.** Drift checks only need `contents: read`. Grant
  `contents: write` only in workflows that commit, and prefer opening a pull
  request over pushing to a protected branch.
- **Path containment.** Service paths must be repo relative; absolute paths and
  `..` segments are rejected. Resolved targets and `content_file` templates
  must also remain inside their allowed roots after following parent symlinks,
  and managed targets cannot themselves be symlinks.
- **No code execution.** Service definitions are pure data. The engine never
  evaluates content, shells out, or fetches remote URLs.
- **Minimal runtime supply chain.** The sync path is stdlib only and runs from
  the bundled source without installing build dependencies. The action's
  `actions/setup-python` dependency is SHA-pinned.
- **Non-destructive by default.** `block` services preserve everything outside
  the markers, `init` services never overwrite an existing file, and `dry_run`
  never writes. Only `file` services replace content wholesale — use them
  deliberately.
- **Best-effort concurrent-change detection.** Before committing and again
  immediately before each mutation, the engine rechecks each target's identity,
  mode, and content. Detected conflicts fail for a retry, but callers should
  still prevent concurrent writers when strict serialization is required.
- **Protect central config.** Anyone who can change central global/repo config
  can change files in every repo that consumes it. Protect those repos and pin
  this action to a tag or SHA.
- **No secrets in config.** Keep credentials out of `managed_file_sync`
  configs and templates. Use GitHub Secrets for sensitive values and GitHub
  Variables for non-sensitive shared values.
- **Untrusted pull requests.** Run drift checks with `pull_request` (never
  `pull_request_target`) and no write permissions.

## 🤝 Contributing

Issues and PRs are welcome on `dev`. Run the tests with:

```bash
python -m pip install -e '.[dev]'
python -m pytest test/ -v
python -m ruff check src test scripts
python3 scripts/render_readme_inputs.py --check
```

Contributions that keep the engine generic are welcome. Org-specific service
definitions belong in your own global/repo config, not in marketplace defaults.

## 📜 License

Apache License 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).
