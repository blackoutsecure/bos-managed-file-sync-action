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

Everything in one Marketplace install: canonical configuration files, managed blocks
inside files you also hand-edit, init-if-missing scaffolding, dry-run
previews, and a CI drift gate. Marketplace defaults are vendor neutral, and
any repo or org can extend them with its own services — no fork required.

## Start here

| Goal | Go to |
| --- | --- |
| Install the action | [Quick start](#quick-start-) |
| Check for drift in pull requests | [Drift check](#drift-check-on-pull-requests) |
| Choose a release reference | [Version pinning](#version-pinning) |
| Understand configuration inheritance | [Configuration layering](#-configuration-inheritance-and-layering) |
| Define or override services | [Config schema](#-config-schema) |
| Choose file behavior | [File modes](#file-modes) |
| Run locally | [Local CLI usage](#-local-usage-cli) |

## ✨ Features

- **Five sync modes** — `block` rewrites only the region between markers in a
  file you otherwise own, `file` overwrites a canonical file wholesale, `init`
  creates a file only when it is absent and never touches it again, `update`
  overwrites only an existing file, and `absent` retires a file that a service
  no longer manages.
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

## How it works

1. The action loads marketplace, global, repo, and workflow configuration.
2. It resolves the requested services after applying exclusions and disabled
  service filters.
3. It reconciles each managed destination according to its file mode.
4. It writes outputs, diffs, and a GitHub Job Summary.

| Run type | Writes files | Exit behavior | Best use |
| --- | --- | --- | --- |
| Apply | Yes, when changes are needed | `0` normally; `1` with `fail_on_drift` when drift exists; `2` on config error | Scheduled synchronization or a repair workflow. |
| Dry run | No | `0` unless configuration fails | Preview changes in logs and the Job Summary. |
| Drift gate | No | `1` when drift exists and `fail_on_drift` is enabled | Pull request validation. |

## Quick start 🚀

Create `.github/bos-universal-config.json` in the destination repository:

```json
{
  "managed_file_sync": {
    "direction": "source-to-destination",
    "services": ["common", "lf_line_endings", "dependabot_actions", "editorconfig"]
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
configuration, compliant/pending/applied totals, service-level counts, and a
file-by-file result table. Disabled and excluded services are listed
separately, so filtered services are not reported as compliant.

| State | Meaning |
| --- | --- |
| `Compliant` | The managed file already matches the resolved service content. |
| `Pending` | A dry run found a file that would be created, updated, or deleted. |
| `Applied` | Apply mode created, updated, or deleted the file. |
| `Excluded` | Service selection intentionally removed it with `exclude_services`. |
| `Disabled` | Service selection filtered it with `disabled_services`. |

States and action rows with no entries are omitted to keep the summary compact.

## 🏗️ Configuration inheritance and layering

This action uses a **four-tier config cascade** with switchable marketplace
defaults, org-wide defaults, repo-specific overrides, and CI-level workflow
inputs. The default sync direction and runner fallback are set in the runtime
defaults so they are easy to override without needing a special locked tier.

### Configuration tiers

The config is merged in cascade order:

1. **Tier 1: Marketplace config** (built-in, default ON)  
   Shipped with the action: best-practice services (`common`, `lf_line_endings`,
  `markdownlint`, `dependabot_actions`, `editorconfig`) and a managed note.
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
and `editorconfig` are synced.

#### Example 2: Marketplace + Org config

Create `.github/blackout-secure-managed-file-sync-global-config.json`:

```json
{
  "managed_file_sync": {
    "direction": "source-to-destination",
    "services": ["common", "lf_line_endings", "markdownlint", "dependabot_actions", "editorconfig"],
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
destination repos containing the hub-managed global config get `editorconfig` and
the org variables automatically.

#### Example 3: Marketplace + Org + Repo config

Same as above, plus create `.github/bos-universal-config.json` in the repo:

```json
{
  "managed_file_sync": {
    "services": ["common", "lf_line_endings", "markdownlint", "dependabot_actions", "editorconfig", "prettier"],
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

#### Hub-owned inline workflow services

To keep workflow templates owned by an automation hub rather than this action,
the hub can pass the complete service definitions through `global_config_json`.
Use `update` for kickers: it replaces an existing workflow but never creates a
new one. The hub remains responsible for serializing its canonical YAML as
`content_lines`.

```yaml
- uses: blackoutsecure/bos-managed-file-sync-action@v1
  with:
    global_config_json: >-
      {"managed_file_sync":{"services":["bos_universal_sync_kicker"],"service_definitions":{"bos_universal_sync_kicker":{"mode":"update","files":[{"path":".github/workflows/bos-universal-sync-kicker.yml","content_lines":["name: Blackout Secure universal sync (kicker)","# Complete canonical workflow lines from the automation hub."]}]}}}}
```

The same object can define `bos_universal_action_test_kicker`,
`bos_universal_launchpad_kicker`, `bos_universal_marketplace_kicker`, and
`bos_universal_security_kicker`. Do not supply only service names: every
inline service needs a `files` definition with canonical `content`,
`content_lines`, or a destination-local `content_file`.

### Precedence rules

When a field is defined in multiple tiers:

- **Services array**: appended by default across marketplace, global, and repo
  tiers, with
  duplicates removed while preserving first-seen order.
  To replace inherited services instead, set `use_marketplace_services: false`
  in that tier, for example
  `{"use_marketplace_services": false, "services": ["prettier"]}`.
- **Service exclusions**: use `exclude_services` (or `disabled_services`) to
  drop resolved services from the final set. This is how you remove a
  marketplace service for a specific global config or repo config.
- **Variables object**: merged. Global values add to marketplace values, and
  repo values can add or override both.
- **Marker namespace**: a lower tier replaces a higher tier (rare).
- **Managed note**: global config often sets this; repo config can override it.

Concrete example (global exclusion + repo append):

Global config (`.github/blackout-secure-managed-file-sync-global-config.json`):

```json
{
  "managed_file_sync": {
    "services": ["editorconfig"],
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
- Global appends: `editorconfig`
- Repo appends: `prettier`
- Global exclusion removes `markdownlint`
- Final set: `common`, `lf_line_endings`, `editorconfig`, `prettier`

For the standard baseline plus quality policy, prefer the profile bundle:

```json
{
  "managed_file_sync": {
    "services": ["quality_baseline"]
  }
}
```

To keep inherited defaults but exclude one service, use an exclusion rather
than replacing the entire service list:

```json
{
  "managed_file_sync": {
    "exclude_services": ["markdownlint"]
  }
}
```

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

### File modes

Each managed file uses one mode to define how the action reconciles the
destination file. A service can set a default mode, and an individual entry in
`files` can override it with its own `mode`.

| Mode | Behavior | Existing destination | Missing destination | Typical use |
| --- | --- | --- | --- | --- |
| `block` | Updates only the managed marker block and preserves surrounding content. | Updates the block; preserves the rest of the file. | Creates the file with the managed block. | Shared config files that the repo also edits. |
| `file` | Reconciles the entire file to the canonical content. | Overwrites the file. | Creates the file. | Fully managed canonical files. |
| `init` | Installs starter content once and never overwrites it afterward. | Leaves the file unchanged. | Creates the file. | Defaults that repositories may customize. |
| `update` | Reconciles only when the destination already exists. | Overwrites the file. | Skips the file; does not create it. | Existing workflows or files that must be opted into first. |
| `absent` | Retires the file from the managed set. | Deletes the file. | No action. | Removing a file from a service while preserving the service definition. |

For `block` mode, markers use the configured namespace and service name, for
example `>>> managed-file-sync:common >>>` and
`<<< managed-file-sync:common <<<`.

| Service | Mode | Managed path(s) |
| --- | --- | --- |
| `common` | block | `.gitignore` |
| `lf_line_endings` | block | `.gitattributes` |
| `dependabot_actions` | block | `.github/dependabot.yml` |
| `editorconfig` | block | `.editorconfig` |
| `shellcheck` | block | `.shellcheckrc` |
| `prettier` | block + init | `.prettierignore`, `.prettierrc.json` |
| `markdownlint` | file | `.markdownlint.json` |
| `baseline` | bundle | `common`, `lf_line_endings`, `editorconfig`, `markdownlint`, `dependabot_actions` |
| `quality_baseline` | bundle | `baseline`, `shellcheck`, `prettier` |

The `prettier` service intentionally uses two modes: `.prettierignore`
inherits the service-level `block` mode, while `.prettierrc.json` overrides it
with `init`. Strict JSON cannot contain the comment markers required by a
managed block, and `init` lets a repository customize its formatter config
without the sync action overwriting it later.

### EditorConfig vs. Prettier

These services are related but have different ownership boundaries:

| Service | Owns | Does not own |
| --- | --- | --- |
| `editorconfig` | General editor and repository defaults in `.editorconfig`. | Prettier-specific rules, ignore patterns, or formatter settings. |
| `prettier` | Prettier ignore patterns in `.prettierignore` and the starter formatter config in `.prettierrc.json`. | General editor settings or unrelated repository files. |

Prettier can read `.editorconfig`, so `editorconfig` may influence how Prettier
formats files. That is expected: `editorconfig` defines shared editor defaults,
while `prettier` defines formatter-specific policy. Keep repository-specific
overrides outside each managed block.


The Marketplace registry intentionally enables only the conservative
`baseline` services by default. Additional services and bundles are available
without being enabled automatically:

- `quality_baseline` adds ShellCheck and Prettier policy.
Community-health files, release metadata, and application configuration are
not Marketplace defaults. They are organization- or project-specific and
belong in global or repository `service_definitions`.

### Optional configuration files

These are reasonable service candidates, but they are intentionally not
Marketplace defaults because their contents depend on the repository’s runtime,
build system, or organization policy:

| File | Suggested mode | Why it is optional |
| --- | --- | --- |
| `.dockerignore` | `block` | Ignore rules vary by language, build context, and container strategy. |
| `.npmrc` | `file` or `init` | Registry, package-manager, and security settings are organization-specific. |
| `.nvmrc` | `init` | Node version is a project decision. |
| `.python-version` | `init` | Python version is a project and deployment decision. |
| `.tool-versions` | `init` | A shared version manager file must match the repository’s toolchain. |
| `.yamllint` or `.yamllint.yaml` | `file` or `init` | YAML rules vary across projects and may conflict with existing policy. |
| `.codespellrc` | `file` or `init` | Ignore lists and dictionaries are repository-specific. |
| `.git-blame-ignore-revs` | `file` | History policy should be authored by the repository. |

Define these in global or repository `service_definitions` only after the
canonical content and ownership are agreed. Do not manage both equivalent
configuration formats for the same tool, such as `.markdownlint.json` and
`.markdownlint.yaml`, in one repository.

List the resolved service registry at any time:

```bash
bos-sync services
```

### Organization-owned sync workflow

The workflow that invokes this action is intentionally not part of the
Marketplace registry. Its triggers, permissions, and commit policy are
organization-specific, so place its `managed_file_sync_workflow` definition in
your automation-hub global config and enable it there. This keeps Marketplace
consumers from receiving an opinionated workflow they did not request.

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
    "services": ["common", "lf_line_endings", "editorconfig"],
    "variables": {
      "owner": "Example Org"
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
    "disabled_services": ["markdownlint"]
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
| `mode` | `block` (default), `file`, `init`, `update`, or `absent`. Can be overridden per file. |
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
bos-sync apply --root . --services common,editorconfig

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
  the markers, `init` services never overwrite an existing file, `update`
  services never create a missing file, and `dry_run` never writes. Only
  `file` and `update` services replace content wholesale — use them
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
