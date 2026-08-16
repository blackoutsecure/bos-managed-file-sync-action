# Blackout Secure Managed File Sync

Copyright © 2025-2026 Blackout Secure | Apache License 2.0

[![Marketplace](https://img.shields.io/badge/GitHub%20Marketplace-blue?logo=github)](https://github.com/marketplace/actions/blackout-secure-managed-file-sync)
[![GitHub release](https://img.shields.io/github/v/release/blackoutsecure/bos-managed-file-sync-action)](https://github.com/blackoutsecure/bos-managed-file-sync-action/releases)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue)](LICENSE)
[![Website](https://img.shields.io/badge/website-blackoutsecure.app-1f1f1f)](https://blackoutsecure.app)
[![Made by BlackoutSecure](https://img.shields.io/badge/made%20by-BlackoutSecure-1f1f1f)](https://github.com/blackoutsecure)

A drop-in composite GitHub Action that reads JSON config → resolves a service
registry → reconciles your repository's managed files → reports or fixes drift.

Everything in one Marketplace install: canonical configuration files, managed
blocks inside files you also hand-edit, init-if-missing scaffolding, dry-run
previews, and a CI drift gate. Marketplace defaults are vendor neutral, and any
repo or org extends them with its own services — no fork required.

Sync is deliberately one-way. The merged catalog, service definitions, and
templates are the **source**; the checked-out repository is the
**destination**. `direction` defaults to `source-to-destination`, the only
supported value; reverse and bidirectional sync fail validation before any file
is touched.

## ✨ Features

- **Five file modes** — `block` rewrites only the region between markers in a
  file you otherwise own, `file` overwrites a canonical file wholesale, `init`
  creates a file only when it is absent, `update` overwrites only an existing
  file, and `absent` retires a file from the managed set.
- **Managed blocks** — canonical content lives between
  `>>> managed-file-sync:<service> >>>` and `<<< managed-file-sync:<service> <<<`
  markers, written with the comment syntax of the target file type. The
  namespace is configurable, so the action can adopt blocks written by another
  tool.
- **Config-driven service registry** — services are pure data. The bundled
  Marketplace registry covers common hygiene files; orgs and repos extend or
  override it through `service_definitions`.
- **Layered config** — bundled Marketplace defaults are deep-merged with an
  optional organization global config, a repository config, and inline workflow
  JSON.
- **Bundles** — a service can `include` other services, so a repo opts into a
  whole standard with one name.
- **Dry run + drift gate** — `dry_run` previews changes without writing;
  `fail_on_drift` turns the preview into a CI gate that fails with an exact
  list of out-of-sync files and a unified diff per file in the job log.
- **Actionable outputs** — `changed`, `changed_count`, `changed_files`, and
  `changed_files_json` make it trivial to open a pull request only when
  something actually moved.
- **Job summary** — successful runs write package identity, a drift narrative,
  resolved configuration, service-level counts, and file-by-file results.
  Failed runs still write a formal report with the exact error, stable rule ID,
  deterministic remediation, confidence, source, and optional AI guidance. Both
  paths use the automation hub's canonical report headings and severity labels.
- **Independent package metadata** — package identity remains available even
  when repository policy is absent, overridden, or not loaded, and reserved
  identity keys are stripped from every config tier.
- **AI-assisted reporting** — uses GitHub Models automatically when a usable
  token is available, supports explicit OpenAI-compatible providers, and can
  summarize drift or recommend error remediation. Deterministic guidance is
  always retained. Disable all model calls with
  `ai.enable_ai_drift_summary: false`.
- **Pure-stdlib Python core** — no third-party runtime dependency at all. The
  composite Action invokes its bundled source directly, with no package install
  or online build step.

## 📖 Table of Contents

- [📋 Prerequisites](#-prerequisites)
- [🚀 Quick start](#-quick-start)
  - [Drift check on pull requests](#drift-check-on-pull-requests)
  - [AI reporting and data handling](#ai-reporting-and-data-handling)
  - [Version pinning](#version-pinning)
- [⚙️ Action inputs](#️-action-inputs)
- [📤 Action outputs](#-action-outputs)
- [📊 Job summary](#-job-summary)
- [📦 Built-in services](#-built-in-services)
  - [File modes](#file-modes)
  - [Service registry](#service-registry)
  - [Managed blocks](#managed-blocks)
  - [Services that are deliberately not defaults](#services-that-are-deliberately-not-defaults)
- [🏗️ Configuration inheritance and layering](#️-configuration-inheritance-and-layering)
  - [Configuration tiers](#configuration-tiers)
  - [Merge and precedence rules](#merge-and-precedence-rules)
  - [Package metadata is not policy](#package-metadata-is-not-policy)
  - [Examples](#examples)
- [📝 Config schema reference](#-config-schema-reference)
  - [Top-level keys](#top-level-keys)
  - [Organization reporting](#organization-reporting)
  - [AI settings](#ai-settings)
  - [Template variables](#template-variables)
  - [Environment variables](#environment-variables)
  - [Service definition fields](#service-definition-fields)
  - [Managed templates directory](#managed-templates-directory)
- [⚠️ Runtime and repository notes](#️-runtime-and-repository-notes)
- [🔐 Security and safety](#-security-and-safety)
- [💻 Local usage (CLI)](#-local-usage-cli)
- [🤝 Contributing](#-contributing)
- [📜 License](#-license)

## 📋 Prerequisites

- GitHub-hosted Linux runner (`ubuntu-latest` or newer) — the action installs
  Python via `actions/setup-python` automatically.
- `actions/checkout` before the action runs, so there is a working tree to
  reconcile.
- For drift checks: nothing beyond the default `contents: read`.
- For committing fixes: `contents: write`, plus `pull-requests: write` when the
  workflow opens a PR.
- Optional for AI drift summaries and error remediation: `models: read`. The
  action supplies the workflow token to GitHub Models inside its sync step.

## 🚀 Quick start

Create `.github/bos-universal-config.json` in the destination repository:

```json
{
  "managed_file_sync": {
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
      models: read          # optional GitHub Models drift summary
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

That's it. The repository config and the conventional global config are
auto-discovered, so the workflow does not repeat config paths. For ad hoc runs,
the `services` input overrides the configured service list.

| Run type | Writes files | Exit behavior | Best use |
| --- | --- | --- | --- |
| Apply | Yes, when changes are needed | `0` normally, `2` on config error | Scheduled synchronization or a repair workflow. |
| Dry run | No | `0` unless configuration fails | Preview changes in logs and the job summary. |
| Drift gate | No | `1` when drift exists with `fail_on_drift` | Pull request validation. |

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

### AI reporting and data handling

AI is enabled in `auto` mode by the bundled Marketplace config and is always
opportunistic. The action looks for GitHub Models credentials first, then uses
an explicitly configured external provider when its endpoint and credential are
both available. If no provider is usable, or a request fails, the run continues
with deterministic local guidance.

For drift summaries, only file path, service name, and action are sent. For
failure remediation, only the error category, exact error text, reported
location, and deterministic remediation are sent. Config documents, managed
file contents, diffs, and credentials are never sent. Model output is advisory:
it cannot change the finding, severity, deterministic recommendation, exit code,
or files written by the sync engine.

To prohibit every model call for an organization or repository while retaining
deterministic summaries and remediation:

```json
{
  "managed_file_sync": {
    "ai": { "enable_ai_drift_summary": false }
  }
}
```

To keep AI drift summaries but disable only AI error remediation, set
`ai.enable_ai_error_remediation` to `false`.

See [AI settings](#ai-settings) for the full schema and provider environment
variables.

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
| `use_marketplace_config` | `true` | `true` (default) applies the bundled marketplace baseline config first, then layers global/repo/inline config on top. Set `false` to skip the bundled baseline entirely and rely solely on your global/repository config. |
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

| Exit code | Meaning |
| --- | --- |
| `0` | The working tree is in sync, or changes were applied successfully. |
| `1` | Drift was detected with `fail_on_drift: 'true'`. |
| `2` | Configuration or sync error. |

## 📊 Job summary

When GitHub Actions provides `GITHUB_STEP_SUMMARY` and
`organization.reporting.enable_job_summary` is enabled, the action writes a job
summary containing package identity, the drift narrative (AI-assisted or local),
the resolved configuration and config cascade, action and service breakdowns,
and a file-by-file result table. Reserved package-metadata keys found in config
are reported as ignored. Rows with no entries are omitted to keep the summary
compact.

Configuration, marker, path-safety, and filesystem failures also write a
best-effort report even when configuration resolution stopped before a normal
sync plan existed. The failure report includes an executive verdict,
configuration context, a stable `MFS-*` rule, exact evidence and location,
deterministic remediation with source/confidence, optional AI-assisted
remediation with provider/confidence, and the report methodology. Failure-report
I/O or AI availability never masks the original annotation or exit code.

Success and failure reports use the same top-level layout as the automation
hub: **Executive summary**, **Configuration used**, **Recommended Actions**, and
**Detailed Findings**.

| Machine severity | Report label | Meaning |
| --- | --- | --- |
| `pass` | Pass | The control was evaluated and satisfied. |
| `warn` | Warning | Advisory drift was found and review is recommended. |
| `fail` | High | A required control failed and must be corrected. |
| `skip` | Not Assessed | The control was not evaluated; compliance cannot be inferred. |

The reusable `bos-automation-hub` workflow owns standalone HTML/PDF rendering
and authenticated artifact upload through its shared `job-report` action. This
composite action emits the raw drift outputs and its direct-invocation Markdown
summary; it does not upload artifacts or generate a duplicate rich report.

| State | Meaning |
| --- | --- |
| `Compliant` | The managed file already matches the resolved service content. |
| `Pending` | A dry run found a file that would be created, updated, or deleted. |
| `Applied` | Apply mode created, updated, or deleted the file. |
| `Excluded` | Service selection intentionally removed it with `exclude_services`. |
| `Disabled` | Service selection filtered it with `disabled_services`. |

## 📦 Built-in services

Every service below ships with the action and can be overridden per repo. The
registry is deliberately vendor neutral — organization-specific services belong
in your global or repository config.

### File modes

Each managed file uses one mode. A service sets a default mode, and an
individual entry in `files` can override it.

| Mode | Existing destination | Missing destination | Typical use |
| --- | --- | --- | --- |
| `block` | Updates the managed block; preserves the rest of the file. | Creates the file with the managed block. | Shared config files the repo also edits. |
| `file` | Overwrites the file. | Creates the file. | Fully managed canonical files. |
| `init` | Leaves the file unchanged. | Creates the file. | Starter defaults a repo may customize. |
| `update` | Overwrites the file. | Skips it; never creates. | Files that must be opted into first, such as workflows. |
| `absent` | Deletes the file. | No action. | Retiring a file while keeping the service definition. |

### Service registry

| Service | Mode | Managed path(s) | Marketplace default |
| --- | --- | --- | --- |
| `common` | block | `.gitignore` | ✅ |
| `lf_line_endings` | block | `.gitattributes` | ✅ |
| `editorconfig` | block | `.editorconfig` | ✅ |
| `markdownlint` | file (+ `absent` cleanup) | `.markdownlint.yaml`; retires the legacy `.markdownlint.json` | ✅ |
| `dependabot_actions` | block | `.github/dependabot.yml` | ✅ |
| `dependabot_pip` | block | `.github/dependabot.yml` | ✅ |
| `shellcheck` | block | `.shellcheckrc` | — |
| `yamllint` | file | `.yamllint.yml` | — |
| `coverage_artifacts` | block | `.gitignore` | — |
| `prettier` | block + init | `.prettierignore`, `.prettierrc.json` | — |
| `baseline` | bundle | `common`, `lf_line_endings`, `editorconfig`, `markdownlint`, `dependabot_actions`, `dependabot_pip` | — |
| `quality_baseline` | bundle | `baseline`, `shellcheck`, `yamllint`, `prettier` | — |

`markdownlint` migrated from `.markdownlint.json` to `.markdownlint.yaml`
(the richer, better-commented format) using a second `files` entry in
`absent` mode targeting the old path — the recommended pattern for retiring
a managed file's format without leaving a stale duplicate that a tool might
prefer over the new one (markdownlint-cli resolves `.markdownlint.json`
before `.markdownlint.yaml` when both exist, silently shadowing the intended
config).

`prettier` intentionally mixes modes: `.prettierignore` inherits the
service-level `block` mode, while `.prettierrc.json` overrides it with `init`.
Strict JSON cannot carry comment markers, and `init` lets a repository
customize its formatter config without later being overwritten.

`coverage_artifacts` ignores `.coverage`, `.coverage.*`, `coverage.xml`, and
`htmlcov/` — opt-in, since some repos intentionally commit or publish those
(e.g. a Pages-hosted coverage badge). A higher tier (e.g. an org global
config) can enable it for every repo by adding it to `services`; any repo can
still opt back out for itself with `disabled_services: ["coverage_artifacts"]`
— a repo's own exclusion always wins over another tier's enablement.

`editorconfig` and `prettier` have distinct ownership boundaries:

| Service | Owns | Does not own |
| --- | --- | --- |
| `editorconfig` | General editor and repository defaults in `.editorconfig`. | Prettier rules, ignore patterns, or formatter settings. |
| `prettier` | Ignore patterns in `.prettierignore` and the starter `.prettierrc.json`. | General editor settings or unrelated repository files. |

List the resolved registry for any repo with `bos-sync services`.

### Managed blocks

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
  `version: 2` / `updates:`), the service declares a `scaffold` written once at
  creation and never touched again.
- A start marker with no end marker → the run fails rather than guessing where
  the block ends.
- Markdown, HTML, and XML use wrapping comments
  (`<!-- >>> managed-file-sync:docs >>> -->`); JSON and lock files are treated
  as commentless, so notes are skipped instead of corrupting them.
- `managed_note` stamps a provenance line under each start marker, and as a
  header on whole-file and init targets. The Marketplace default resolves at run
  time to the kit that wrote the block and the config file that selected it:

  ```text
  # >>> managed-file-sync:common >>>
  # Managed by Blackout Secure Managed File Sync — configure services in .github/bos-universal-config.json.
  ```

  Set `managed_note` to your own string (or `false`) in any tier to change it.

| Existing block state | `take_over_managed_files: false` (default) | `take_over_managed_files: true` |
| --- | --- | --- |
| Configured namespace exists | Update it in place. | Update it in place. |
| Different namespace exists | Fail safely; no duplicate is written. | Remove the competing block and write the configured block. |
| Multiple namespaces exist | Fail safely; ownership is ambiguous. | Remove all competing blocks for that service, then write. |
| No block exists | Append the configured block. | Append the configured block. |

### Services that are deliberately not defaults

Community-health files, release metadata, and application configuration depend
on the repository's runtime, build system, or organization policy, so they are
not Marketplace defaults. Define them in global or repository
`service_definitions` once the canonical content and ownership are agreed.

| File | Suggested mode | Why it is optional |
| --- | --- | --- |
| `.dockerignore` | `block` | Ignore rules vary by language, build context, and container strategy. |
| `.npmrc` | `file` or `init` | Registry, package-manager, and security settings are organization-specific. |
| `.nvmrc` | `init` | Node version is a project decision. |
| `.python-version` | `init` | Python version is a project and deployment decision. |
| `.tool-versions` | `init` | A shared version-manager file must match the repository toolchain. |
| `.codespellrc` | `file` or `init` | Ignore lists and dictionaries are repository-specific. |
| `.git-blame-ignore-revs` | `file` | History policy should be authored by the repository. |

Do not manage two equivalent formats for the same tool (for example
`.markdownlint.json` and `.markdownlint.yaml`) in one repository.

The workflow that invokes this action is also excluded on purpose: its
triggers, permissions, and commit policy are organization-specific. Put that
`update`-mode service in your automation hub's global config.

## 🏗️ Configuration inheritance and layering

### Configuration tiers

Configuration is merged in cascade order; later tiers win.

| # | Tier | Source | Notes |
| --- | --- | --- | --- |
| 1 | Marketplace defaults | Bundled [marketplace config](src/sync_kit/managed-file-sync-marketplace-config.json) | Conservative baseline services, marker namespace, managed note, and AI defaults. Disable via the `use_marketplace_config: false` action input, or set `use_marketplace_config: false` in any config tier. |
| 2 | Organization global config | `.github/blackout-secure-managed-file-sync-global-config.json` | Loaded automatically when present. `use_global_config: 'true'` requires it, `'false'` disables discovery. |
| 3 | Repository config | `.github/bos-universal-config.json` (preferred), `bos-universal-config.json`, `managed-file-sync.json`, `.managed-file-sync.json` | Optional; repos inherit tiers 1–2 when absent. |
| 4 | Workflow inputs | `services`, `config_json`, `global_config_json`, `managed_files_path` | Per-run control without touching config files. |

All files are read from the installed action or the destination checkout;
config discovery never fetches from another repository. A hub that owns policy
must publish its canonical global config into the destination checkout.

### Merge and precedence rules

| Field kind | Behavior |
| --- | --- |
| Scalars | Later tiers replace earlier tiers. |
| Objects | Deep-merged, so one nested field can be overridden without repeating the object. |
| `services` | Appended across tiers with duplicates removed in first-seen order. Set `use_marketplace_services: false` in a tier to replace inherited services instead. |
| `exclude_services` / `disabled_services` | Appended across tiers, then removed from the resolved set. |
| `variables` | Merged; repo values override global and Marketplace values. |
| `marker_namespace`, `managed_note` | A later tier replaces the earlier value. |
| `service_definitions` | Merged by service name; a same-named entry fully replaces the inherited definition. |

To keep inherited defaults but drop one service, prefer an exclusion over
replacing the whole list:

```json
{
  "managed_file_sync": {
    "exclude_services": ["markdownlint"]
  }
}
```

To use only global and repository policy without Marketplace defaults:

```json
{
  "managed_file_sync": {
    "use_marketplace_config": false,
    "services": []
  }
}
```

This is rarely needed; Marketplace defaults are conservative. Define
replacement services in `service_definitions` before enabling them.

### Package metadata is not policy

Package identity is separate from this cascade. The kit's name, version,
author, description, official website, repository, documentation, issue and
release trackers, Marketplace listing, support contact, license, and copyright
come from package-owned metadata and remain available even when repository
policy is absent, overridden, or fails to load.

Official links:

- Website: <https://blackoutsecure.app>
- Repository: <https://github.com/blackoutsecure/bos-managed-file-sync-action>
- Documentation: <https://github.com/blackoutsecure/bos-managed-file-sync-action#readme>
- Issues: <https://github.com/blackoutsecure/bos-managed-file-sync-action/issues>
- Releases: <https://github.com/blackoutsecure/bos-managed-file-sync-action/releases>
- Marketplace: <https://github.com/marketplace/actions/blackout-secure-managed-file-sync>
- Support: <info@blackoutsecure.app>

Identity-shaped keys, including `name`, `version`, `author`, `description`,
`website`, `repository`, `support_email`, `license`, and `copyright`, are
stripped from the top level of **every** tier before the merge. Ignored keys are
reported by `bos-sync validate` and in the job summary. Nested
`service_definitions[*].description` is policy, not identity, and is preserved.

`bos-sync validate` prints package metadata and the applied config cascade
before any policy output.

### Examples

**Organization defaults plus a repository addition.** Global config
(`.github/blackout-secure-managed-file-sync-global-config.json`):

```json
{
  "managed_file_sync": {
    "services": ["editorconfig"],
    "exclude_services": ["markdownlint"],
    "variables": {
      "org_name": "my-org",
      "support_email": "platform-team@my-org.com"
    }
  }
}
```

Repository config (`.github/bos-universal-config.json`):

```json
{
  "managed_file_sync": {
    "services": ["prettier"],
    "variables": { "project_name": "my-typescript-project" }
  }
}
```

Resolved set: Marketplace defaults plus `editorconfig` and `prettier`, minus
`markdownlint`. Variables from both tiers are merged.

**Replace inherited services instead of appending:**

```json
{
  "managed_file_sync": {
    "use_marketplace_services": false,
    "services": ["prettier"]
  }
}
```

**Hub-owned inline services.** An automation hub can pass complete service
definitions through `global_config_json`, keeping workflow templates in the hub
rather than in this action. Use `update` mode for kicker workflows: it replaces
an existing workflow but never creates one.

```yaml
- uses: blackoutsecure/bos-managed-file-sync-action@v1
  with:
    global_config_json: >-
      {"managed_file_sync":{"services":["bos_universal_sync_kicker"],"service_definitions":{"bos_universal_sync_kicker":{"mode":"update","files":[{"path":".github/workflows/bos-universal-sync-kicker.yml","content_lines":["name: Blackout Secure universal sync (kicker)"]}]}}}}
```

Every inline service needs a `files` definition with `content`, `content_lines`,
or a destination-local `content_file`; names alone are rejected.

## 📝 Config schema reference

Per-repo sync policy lives in the `managed_file_sync` section of a JSON config
file. Universal configs may use `sync` as a grouped alias. If both keys are
present, the explicit `managed_file_sync` section wins. A document without
either key is treated as the sync section itself. When an external policy owner
such as the automation hub supplies a full universal config, the action also
retains top-level `organization`, `security`, `marketplace`, and `general`
companion sections for reporting. Those sections are not bundled defaults.
Every field is optional and unknown keys are ignored, so newer versions can
extend the schema without breaking older callers.

```json
{
  "managed_file_sync": {
    "services": ["common", "lf_line_endings", "editorconfig"],
    "variables": { "owner": "Example Org" }
  }
}
```

The equivalent grouped universal-config form is:

```json
{
  "sync": {
    "services": ["common", "lf_line_endings", "editorconfig"]
  },
  "organization": {
    "reporting": { "title_prefix": "Example Org" }
  }
}
```

Services can also be toggled with an object, which suits generated configs:

```json
{
  "managed_file_sync": {
    "services": { "common": true, "prettier": false },
    "disabled_services": ["markdownlint"]
  }
}
```

### Top-level keys

| Key | Type | Default | Description |
| --- | --- | --- | --- |
| `direction` | string | `source-to-destination` | One-way sync direction. Any other value is rejected. |
| `services` | array or object | Marketplace baseline | Enabled services. `["*"]` enables every file-managing service in the registry. |
| `use_marketplace_config` | boolean | `true` | `false` drops the bundled Marketplace tier for this run. |
| `use_marketplace_services` | boolean | `true` | `false` replaces inherited `services` at this tier instead of appending. |
| `exclude_services` | array | `[]` | Services removed from the resolved set for this scope. |
| `disabled_services` | array | `[]` | Names removed after resolution — useful with `*` and bundles. |
| `service_definitions` | object | `{}` | Local services. Keys use letters, numbers, `.`, `_`, or `-`; same-named entries override inherited services. |
| `managed_files_path` | string | `.github/managed-files` | Base path for `content_file` template lookup. |
| `variables` | object | `{}` | Values for `{{token}}` placeholders in service content. |
| `marker_namespace` | string | `managed-file-sync` | Marker namespace for managed blocks. |
| `managed_note` | string or array | see below | Provenance note written into managed blocks and file headers. |
| `take_over_managed_files` | boolean | `false` | When `true`, removes competing managed blocks for the same service; when `false`, the run fails instead. |
| `cleanup_duplicate_lines` | boolean | `false` | When `true`, after a managed block is written, lines outside ANY managed block that exactly duplicate one of its lines are removed (e.g. a hand-added `.venv/` in `.gitignore` once a `common` block also ignores it). Never touches content inside a managed block, this service's or another's. |
| `ai` | object | see below | AI-assisted drift summary policy. |

### Organization reporting

Reporting policy lives at top-level `organization.reporting`, outside the sync
section. The direct action consumes the Markdown title, job-summary, and
annotation controls. The reusable automation-hub workflow consumes the same
policy when it renders and uploads the standalone audit report.

| Key | Default | Owner and behavior |
| --- | --- | --- |
| `enable_job_summary` | `true` | Direct action and hub: write `$GITHUB_STEP_SUMMARY`; `false` suppresses it. |
| `enable_annotations` | `true` | Direct action and hub: emit GitHub `error`/`warning` workflow annotations; plain stderr remains visible when disabled. |
| `enable_html` | `true` | Hub: generate the standalone HTML audit report. |
| `enable_pdf` | `false` | Hub: attempt PDF export when Chrome or Chromium is available. |
| `html_path` | `blackout-secure-report.html` | Hub: workspace path for HTML output. |
| `pdf_path` | `blackout-secure-report.pdf` | Hub: workspace path for optional PDF output. |
| `artifact_name` | `blackout-secure-audit-report` | Hub workflow: authenticated Actions artifact name. |
| `title_prefix` | `Blackout Secure` | Direct action and hub: prefix generated report titles. |
| `fail_on` | `fail` | Hub report step: `fail`, `warn`, or `never`. Direct action exits remain controlled by sync errors and `fail_on_drift`. |

```json
{
  "organization": {
    "reporting": {
      "enable_job_summary": true,
      "enable_annotations": true,
      "enable_html": true,
      "enable_pdf": false,
      "html_path": "blackout-secure-report.html",
      "pdf_path": "blackout-secure-report.pdf",
      "artifact_name": "blackout-secure-audit-report",
      "title_prefix": "Blackout Secure",
      "fail_on": "fail"
    }
  }
}
```

The published action intentionally does not bundle organization security gates,
Marketplace publication metadata, action-test matrices, or repository-owned
universal config. The automation hub supplies those companion sections through
its global or inline config when it invokes this action.

### AI settings

```json
{
  "managed_file_sync": {
    "ai": {
      "enable_ai_drift_summary": true,
      "ai_drift_summary_provider": "auto",
      "enable_ai_error_remediation": true,
      "ai_error_remediation_provider": "auto",
      "local_heuristic_fallback": true
    }
  }
}
```

| Key | Type | Default | Description |
| --- | --- | --- | --- |
| `ai.enable_ai_drift_summary` | boolean | `true` | Enables AI drift summaries. For backward compatibility, `false` is also the master switch that prohibits all model calls. |
| `ai.ai_drift_summary_provider` | string | `auto` | `auto`, `none`, `github-models`, or an external OpenAI-compatible provider name. |
| `ai.enable_ai_error_remediation` | boolean | `true` | Adds advisory AI remediation to failure reports. Deterministic remediation is always shown. |
| `ai.ai_error_remediation_provider` | string | drift provider | `auto`, `none`, `github-models`, or an external OpenAI-compatible provider name. |
| `ai.local_heuristic_fallback` | boolean | `true` | Keeps the deterministic summary when no provider is usable. |

### Template variables

Service content is rendered with `{{token}}` placeholders. Unknown tokens are
left untouched rather than blanked out. Every key in `variables` is available as
a token, and the built-ins below are always present.

| Variable | Default | Source |
| --- | --- | --- |
| `{{package_name}}` | `bos-managed-file-sync` | Installed package metadata. Cannot be overridden by config. |
| `{{package_title}}` | `Blackout Secure Managed File Sync` | Installed package metadata. Cannot be overridden by config. |
| `{{package_version}}` | installed version | Installed package metadata. Cannot be overridden by config. |
| `{{config_source}}` | `managed-file-sync-marketplace-config.json` | The highest-precedence config file in effect: the repository config, else the global config, else the bundled Marketplace file. Cannot be overridden by config. |
| `{{year}}` | current year | System clock at run time. |
| `{{repository}}` | _(empty)_ | `GITHUB_REPOSITORY`, as `owner/repo`. |
| `{{owner}}` | _(empty)_ | Owner half of `GITHUB_REPOSITORY`, falling back to `GITHUB_REPOSITORY_OWNER`. |
| `{{repo}}` | _(empty)_ | Repository half of `GITHUB_REPOSITORY`. |
| `{{project_name}}` | `{{repo}}` | Override in `variables`. |
| `{{fallback_default_runner}}` | `ubuntu-latest` | Override in `variables`; used whenever a runner value is missing or invalid. |
| `{{DEFAULT_RUNNER}}` | `{{fallback_default_runner}}` | `variables.DEFAULT_RUNNER`, then the `DEFAULT_RUNNER` environment variable. |
| `{{RUNNER_X64}}` | `{{fallback_default_runner}}` | `variables.RUNNER_X64`, then the `RUNNER_X64` environment variable. |
| `{{RUNNER_ARM64}}` | `{{fallback_default_runner}}` | `variables.RUNNER_ARM64`, then the `RUNNER_ARM64` environment variable. |
| `{{WORKLOAD_ARCH}}` | `auto` | `workload_arch` input: `auto`, `x64`, `arm64`, or `default`. Unknown values degrade to `auto`. |
| `{{SELECTED_RUNNER}}` | resolved at run time | `{{WORKLOAD_ARCH}}`, or `RUNNER_ARCH` when the workload is `auto`. |

A runner value is valid when it is a single label (`ubuntu-latest`) or a JSON
array string of labels (`["ubuntu-latest"]`); anything else falls back to
`{{fallback_default_runner}}`.

### Environment variables

| Variable | Used for | Purpose |
| --- | --- | --- |
| `GITHUB_REPOSITORY`, `GITHUB_REPOSITORY_OWNER` | Templates | Populate `{{repository}}`, `{{owner}}`, and `{{repo}}`. |
| `DEFAULT_RUNNER`, `RUNNER_X64`, `RUNNER_ARM64` | Templates | Runner labels for workflow templates. |
| `RUNNER_ARCH` | Templates | Auto-detects runner architecture for `{{SELECTED_RUNNER}}`. |
| `MFS_WORKLOAD_ARCH` | Action step | Set from the `workload_arch` input. |
| `GITHUB_OUTPUT`, `GITHUB_STEP_SUMMARY` | Reporting | Emit action outputs and the job summary; skipped when unset. |
| `GITHUB_MODELS_TOKEN`, `GITHUB_TOKEN` | AI | Credential for GitHub Models, in that order. The composite step supplies `github.token` as `GITHUB_TOKEN`. |
| `GITHUB_MODELS_ENDPOINT`, `GITHUB_MODELS_MODEL` | AI | Optional endpoint and model overrides; endpoints must be HTTPS. |
| `<PROVIDER>_API_KEY`, `<PROVIDER>_API_ENDPOINT`, `<PROVIDER>_MODEL` | AI | External provider settings, for example `OPENAI_API_KEY`. |
| `AI_API_KEY`, `AI_API_ENDPOINT` | AI | Generic fallbacks for an external provider. |

Keep credentials in Actions secrets or the runner environment; never commit them
to config files.

### Service definition fields

```json
{
  "managed_file_sync": {
    "services": ["security_policy", "release_config"],
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
| `includes` | Makes the service a bundle: it expands to the listed services instead of managing files. Mutually exclusive with `files`. |
| `description` | Shown by `bos-sync services`. |
| `files[].path` | Repo-relative path. Absolute paths and `..` are rejected. |
| `files[].mode` | Per-file override of the service mode. |
| `files[].content` | String, or array of lines. |
| `files[].content_lines` | Array of lines, joined with newlines. |
| `files[].content_file` | Template source resolved beneath `managed_files_path`. Exactly one content source per file entry. |
| `files[].scaffold` | Block mode only: root structure written once when the file is created. |
| `files[].comment_prefix` | Override marker comment syntax. Use `open\|close` for wrapping styles. |
| `files[].marker_namespace` | Marker namespace for this block. Competing namespaces fail safely instead of creating a duplicate. |

To adopt an existing block written by another manager, keep the service name and
set `files[].marker_namespace` to the existing namespace — the action then
updates that block in place instead of appending a second one. For an
intentional ownership handoff, enable `take_over_managed_files: true`; only
competing blocks for the same service are removed, and the rest of the file is
preserved.

### Managed templates directory

`content_file` sources resolve beneath `managed_files_path`, which defaults to
`.github/managed-files` — close to the other governance files, out of the
repository root, and compatible with config layering. The destination is always
declared per file via `files[].path`.

```json
{
  "managed_file_sync": {
    "managed_files_path": ".github/managed-files",
    "services": ["release_config"]
  }
}
```

The same value can be overridden per run with the `managed_files_path` input.
The action never writes to a template source and never pushes to another
repository.

## ⚠️ Runtime and repository notes

- **Checkout is required.** Put `actions/checkout` before the action; without a
  working tree there is nothing to reconcile.
- **Sync is one-way.** The catalog and templates are the source, the checkout is
  the destination. `direction` accepts only `source-to-destination`.
- **Config discovery is local.** Global and repository config are read from the
  destination checkout; nothing is fetched from another repository.
- **Conflicting ownership fails fast.** Two services may share a path only when
  both are `block` mode with distinct markers; every other overlap is rejected
  before any write.
- **Bundles cannot cycle.** `includes` is expanded with a depth limit and a
  clear error instead of looping.
- **Network access is optional.** Only AI reporting can make an outbound
  request; the sync path itself never touches the network.

## 🔐 Security and safety

- **Least privilege.** Drift checks only need `contents: read`. Grant
  `contents: write` only in workflows that commit, and prefer opening a pull
  request over pushing to a protected branch.
- **Path containment.** Service paths must be repo relative; absolute paths and
  `..` segments are rejected. Resolved targets and `content_file` templates must
  remain inside their allowed roots after following parent symlinks, and managed
  targets cannot themselves be symlinks.
- **No code execution.** Service definitions are pure data. The engine never
  evaluates content, shells out, or fetches remote URLs.
- **Constrained AI egress.** Optional AI reporting requires an HTTPS endpoint
  plus an explicit credential. Drift requests send path/service/action metadata;
  remediation requests send error category/text/location and the deterministic
  recommendation. Config documents, managed-file contents, diffs, and
  credentials are excluded. Every provider failure degrades to deterministic
  guidance, and `ai.enable_ai_drift_summary: false` prohibits AI entirely.
- **Identity cannot be spoofed by config.** Package name, version, author, and
  description are read from the installed package; the matching config keys are
  stripped from every tier before merging.
- **Minimal runtime supply chain.** The sync path is stdlib only and runs from
  the bundled source without installing build dependencies. The action's
  `actions/setup-python` dependency is SHA-pinned.
- **Non-destructive by default.** `block` preserves everything outside the
  markers, `init` never overwrites, `update` never creates, and `dry_run` never
  writes. Only `file` and `update` replace content wholesale — use them
  deliberately.
- **Best-effort concurrent-change detection.** Before committing, and again
  immediately before each mutation, the engine rechecks every target's identity,
  mode, and content. Detected conflicts fail for a retry, but callers should
  still prevent concurrent writers when strict serialization is required.
- **Protect central config.** Anyone who can change global or repository config
  can change files in every consuming repo. Protect those repos and pin this
  action to a tag or SHA.
- **No secrets in config.** Keep credentials out of `managed_file_sync` configs
  and templates. Use GitHub Secrets for sensitive values and GitHub Variables
  for non-sensitive shared values.
- **Untrusted pull requests.** Run drift checks with `pull_request` (never
  `pull_request_target`) and no write permissions.

## 💻 Local usage (CLI)

The kit ships a standalone `bos-sync` CLI for local triage or non-GitHub CI:

```bash
python -m pip install \
  'git+https://github.com/blackoutsecure/bos-managed-file-sync-action.git@v1.0.0'

# List the resolved service registry
bos-sync services --root .

# Print package metadata and the config cascade, then validate policy
bos-sync validate --root .

# Preview, then apply
bos-sync apply --root . --dry-run
bos-sync apply --root . --services common,editorconfig

# CI drift gate (dry-run + non-zero exit on drift)
bos-sync check --root .
bos-sync check --root . --no-diff       # file list only, no diffs

# Require a custom organization config
bos-sync validate --root . --global-config .github/org-sync.json --use-global-config

# Ignore a conventional global config for one local run
bos-sync validate --root . --no-global-config

# Use managed templates from a custom directory
bos-sync apply --root . --managed-files-path .github/managed-files
```

Exit codes match the action: `0` in sync, `1` drift detected, `2` config error.

## 🤝 Contributing

Issues and PRs are welcome on `dev`. Run the checks with:

```bash
python -m pip install -e '.[dev]'
python -m pytest test/ -v
python -m ruff check src test scripts
python3 scripts/render_readme_inputs.py --check
```

Contributions that keep the engine generic are welcome. Organization-specific
service definitions belong in your own global or repository config, not in
Marketplace defaults.

## 📜 License

Apache License 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).
