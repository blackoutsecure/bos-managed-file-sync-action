# AGENTS.md

This file provides guidance to agents when working with code in this repository.

## What this is

`bos-managed-file-sync-action` is the reconciliation engine that keeps canonical files and
managed blocks in sync across repositories. It ships to the GitHub Marketplace as **Blackout
Secure Managed File Sync**: a composite action wrapping a pure-stdlib Python package
(`sync_kit`). Given a merged JSON config it resolves a service registry, diffs the result
against the checked-out working tree, and either reports drift or writes the files. Sync is
one-way, and `direction` accepts only `source-to-destination`.

`blackoutsecure/bos-automation-hub` is the canonical caller. Its reusable
`.github/workflows/bos-universal-sync.yml` checks out the target repo and the hub (at
`hub-source`), then invokes this action SHA-pinned with `global_config_path` set to
`hub-source/sync-files/config/managed-file-sync-global-config.json` and `managed_files_path`
set to `hub-source/sync-files`. That `sync-files/` tree is the payload (`community-health/`,
`github-meta/`, `legal/`, `org-profile/`, `workflows/`, `config/`). Every repository in the
organization runs that workflow, so this engine is what rewrites `LICENSE`,
`CODE_OF_CONDUCT.md`, `.editorconfig`, `.gitignore`, `README.md` blocks, and the gatekeeper
kicker workflow everywhere.

The action never commits, pushes, or opens a pull request; it mutates the working tree and
emits outputs, and the hub commits with its own `commit-and-push` action. Writing to
`.github/workflows/**` is a platform restriction, not an engine one: `GITHUB_TOKEN` can never
push there, so the hub mints a GitHub App token (`vars.GATEWALL_APP_ID` +
`secrets.GATEWALL_APP_PRIVATE_KEY`) or falls back to `secrets.WORKFLOW_SYNC_PAT`; with neither
it passes `config_json` disabling the two kicker services. Stack: Python `>=3.10` (the action
installs `3.12` via `actions/setup-python`), hatchling `>=1.27`, no runtime dependencies, dev
extras pytest, ruff, PyYAML; version `1.0.0`, console script `bos-sync`, license Apache-2.0.

## Commands

```bash
# Dev install (Python 3.10+; the action itself installs nothing)
python3 -m venv .venv && source .venv/bin/activate
python -m pip install -e '.[dev]'

# Run the sync locally against a scratch checkout — dry-run never writes
bos-sync apply --root /path/to/scratch-checkout --dry-run
bos-sync check --root /path/to/scratch-checkout   # drift gate, exit 1 on drift

# Tests, lint, generated docs
python -m pytest test/ -v
python -m pytest test/test_engine.py -v
python -m ruff check src test scripts
python3 scripts/render_readme_inputs.py --check   # --write to regenerate
```

Exit codes are shared by the CLI and the action: `0` in sync, `1` drift with
`--fail-on-drift`, `2` configuration or sync error.

## Validating changes

CI runs the hub's reusable `bos-universal-security.yml` and `.github/workflows/codeql.yml`,
which calls the hub's `security-scan.yml` with `codeql_languages: '["python", "actions"]'`.
The gatekeeper kicker also runs `bos-universal-sync.yml` in `commit` mode as a pre-flight, and
`test/test_repository_contract.py` asserts `action.yml`, `pyproject.toml`, and package metadata
still agree. Locally, work narrowest-first: the single test file for the module you touched,
then the full suite, then ruff, then `render_readme_inputs.py --check` if `action.yml` changed.

A change here can rewrite files in every downstream repository on the next scheduled sync. Any
behaviour change to marker handling, mode semantics, config merge order, or path safety must
be dry-run first: run `bos-sync check` against a real scratch checkout of at least one consumer
repo, with the hub's `sync-files/config/managed-file-sync-global-config.json` as
`--global-config`, and read the diff before release. Unit tests do not bound the blast radius.

## Architecture

```text
action.yml                          Composite action: setup-python then bootstrap the CLI
pyproject.toml                      Packaging, ruff/pytest config, bos-sync entrypoint
src/sync_kit/_bootstrap.py          Runs the bundled CLI without importing consumer code
src/sync_kit/cli.py                 Subcommands, exit codes, job summary
src/sync_kit/config.py              Config discovery, tier merge, template variables
src/sync_kit/catalog.py             Service parsing, bundles, file_patches, conflict checks
src/sync_kit/engine.py              Reconciliation, mode handling, atomic writes
src/sync_kit/markers.py             Delimiter contract, comment syntax, dedupe
src/sync_kit/paths.py               Path containment and symlink rejection
src/sync_kit/metadata.py            Package identity; reserved-key stripping
src/sync_kit/reporting.py           Failure findings, MFS-* rules, report settings
src/sync_kit/ai.py                  Optional advisory provider calls
src/sync_kit/managed-file-sync-marketplace-config.json   Bundled tier-1 baseline
scripts/render_readme_inputs.py     Regenerates the README input/output tables
test/                               pytest suite; conftest.py provides the Repo fixture
.github/bos-universal-config.json   Repo-owned overrides (security, marketplace, action_test)
.github/workflows/codeql.yml        Thin caller for the hub security-scan reusable
.github/workflows/bos-universal-gatekeeper-kicker.yml   Hub-managed dispatch front door
```

### Sync flow

1. `cli._Plan` resolves package identity first, then the repo root.
2. `config.load_repo_config` merges four tiers, later winning: bundled marketplace config; org
   global config (`.github/blackout-secure-managed-file-sync-global-config.json`); repo config
   (`.github/bos-universal-config.json`, `bos-universal-config.json`, `managed-file-sync.json`,
   `.managed-file-sync.json`); inline workflow JSON. Objects deep-merge; `services`,
   `exclude_services`, `disabled_services`, and `file_patches` append; reserved identity keys
   are stripped from every tier first.
3. `catalog.load_catalog` validates `service_definitions` (exactly one of `content` /
   `content_lines` / `content_file` per entry); `apply_file_patches` applies ordered exact-line
   `remove` then `append` edits; `resolve_services` expands `includes` bundles, applies `*`,
   subtracts disabled and excluded names, and runs `check_conflicts` — two services may share a
   path only when both are `block` mode.
4. `engine.SyncEngine.sync` plans every file then writes. Per-file mode: `block` rewrites only
   the delimited region; `file` overwrites wholesale; `init` creates only when absent; `update`
   overwrites only when present and never creates; `absent` deletes. Writes are atomic and
   staged: every target is re-verified for identity, mode, and bytes immediately before
   mutation, then written through a temporary file in an `O_NOFOLLOW`-opened parent. `dry_run`
   computes the same change set and touches nothing; `changed`, `changed_count`,
   `changed_files`, and `changed_files_json` go to `GITHUB_OUTPUT`.

### Delimiter contract

A managed block is exactly two marker lines in the target file's comment syntax:

```text
# >>> managed-file-sync:common >>>
...canonical content...
# <<< managed-file-sync:common <<<
```

The tag is `<namespace>:<service>`. Namespace defaults to `managed-file-sync`, overridable per
tier (`marker_namespace`) or per file (`files[].marker_namespace`); both halves must match
`[A-Za-z0-9_.-]+`. Wrapping styles use the `open|close` form, so Markdown, HTML, and XML get
`<!-- >>> managed-file-sync:docs >>> -->`; `.json` and `.lock` are commentless. Text outside
the markers is preserved byte for byte, reusing the detected line ending. Missing markers
append the block, and `scaffold` writes a root structure once at creation only (for example
`version: 2` / `updates:` in `.github/dependabot.yml`). Anything but exactly one start and one
end marker, an end before a start, or content containing a marker line raises `MarkerError`
rather than guessing; a competing namespace for the same service fails safely unless
`take_over_managed_files` is `true`. `cleanup_duplicate_lines` (default `false`) drops lines
outside _any_ managed block that duplicate the block's lines, depth-counted so another
service's block is never touched.

### Action contract

Inputs: `use_global_config` (`auto`), `use_marketplace_config` (`true`), `global_config_path`
(`.github/blackout-secure-managed-file-sync-global-config.json`), `config_path`,
`global_config_json`, `config_json`, `services`, `managed_files_path`, `workload_arch`
(`auto`), `working_directory` (`.`), `dry_run` (`false`), `fail_on_drift` (`false`),
`show_diff` (`true`), `python_version` (`3.12`). Outputs: `changed`, `changed_count`,
`changed_files`, `changed_files_json`. Each input maps to an `MFS_*` environment variable then
to a `bos-sync apply` flag. The README tables between `<!-- BEGIN action-inputs -->` and
`<!-- END action-outputs -->` are generated from `action.yml`, so any contract edit must be
followed by `render_readme_inputs.py --write`.

### Root `*_file.json` files

`dev_file.json`, `origin_main_file.json`, `sha_file.json`, and `tag_v1023_file.json` are four
byte-identical snapshots of an older resolved managed-file-sync config, captured while comparing
what different git refs (`dev`, `origin/main`, a commit SHA, tag `v1.0.23`) served;
`main_file.json` is empty because the file was absent on that ref. All five landed in commit
`cc4c878`. They are not fixtures: nothing reads them, they are not in `.gitignore`, and their
content is a stale subset of `src/sync_kit/managed-file-sync-marketplace-config.json` carrying
hub-workflow keys this engine ignores. Treat them as leftover debugging artifacts.

## Conventions

Pure stdlib in the sync path — adding a runtime dependency is a design change. Modules stay
small and single-purpose, every public function carries a one-line docstring, and comments
explain why a non-obvious choice exists rather than restating the code. Validation failures
raise `ConfigError` or `MarkerError` from `errors.py` with the config path in the message,
never a bare `assert` or `sys.exit`. Ruff enforces `E,F,W,I,B,UP,S,SIM` at line length 100.
Tests use the `repo` fixture from `test/conftest.py` and assert on file bytes and the resulting
`Change` set, not log text.

```python
def cleanup_duplicate_lines(section: dict[str, Any]) -> bool:
    """Whether block sync removes duplicate lines left outside a managed block.

    Off by default: ... removing text outside the marked region is a stronger
    action than the rest of this tool takes anywhere else.
    """
    return _bool_field(section.get("cleanup_duplicate_lines"), "cleanup_duplicate_lines", False)
```

## Blackout Secure conventions

These apply to every repository in the `blackoutsecure` organization.

### Branch model

- `dev` is the default branch and where all work lands.
- `main` is the promoted stable runtime that consumers reference through `@main`.
- Version tags (`vX.Y.Z` and a floating `vX`) point at promoted runtime commits.
- Promotion is driven from `bos-automation-hub` (`release-promote.yml`). Do not push
  directly to `main` and do not move tags by hand.

### Centrally managed files - do not hand-edit here

`blackoutsecure/bos-automation-hub` distributes these through
`bos-managed-file-sync-action`. Change the source under the hub's `sync-files/`, never the
copy in this repository:

- `LICENSE`, `CODE_OF_CONDUCT.md`, `CONTRIBUTING.md`, `SECURITY.md`, `SUPPORT.md`
- `.github/FUNDING.yml`, `.github/PULL_REQUEST_TEMPLATE.md`, `.github/ISSUE_TEMPLATE/`
- `.github/workflows/bos-universal-gatekeeper-kicker.yml`
- the `# >>> managed-file-sync:<service> >>> ... # <<< managed-file-sync:<service> <<<`
  delimited blocks inside `.editorconfig`, `.markdownlint.yaml`, `.shellcheckrc`,
  `.yamllint.yml`, `.gitignore`, and `README.md`

`.github/bos-universal-config.json` is repo-owned. It holds this repository's overrides on
top of the hub's global config and is the right place to change gate behaviour.

### CI gate

Pushes and pull requests run the hub's reusable `bos-universal-security.yml`, reported as a
single required check. It runs markdownlint, yamllint, shellcheck, and actionlint; ESLint,
Prettier, Ruff, pytest, and Bats where the repository has them; `bos-code-scanning-kit`
(secret scan, SAST, GHAS posture) and CodeQL; dependency review; and compliance checks for
the canonical README header and a conventional-commit PR title
(`feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert: subject`).

Every `uses:` reference in a workflow must be a commit SHA with a trailing version comment,
for example `actions/checkout@<sha> # v4.2.2`.

## Boundaries

### Always

- Dry-run any behaviour change against a real scratch checkout before release, and add a
  regression test for every marker, mode, or merge-semantics change.
- Keep the sync path stdlib-only and free of shell-outs, `eval`, and network calls.
- Run `python3 scripts/render_readme_inputs.py --write` after touching `action.yml`.
- Keep path containment intact: reject absolute paths, `..`, symlinked targets, and anything
  resolving outside the repo root or `managed_files_path`.

### Ask first

- Any change to the delimiter format, namespace grammar, or comment-prefix mapping. Blocks in
  every downstream repo are matched by these exact strings; a change orphans them.
- Any change to overwrite semantics — the `block`/`file`/`init`/`update`/`absent` matrix,
  `take_over_managed_files`, or `cleanup_duplicate_lines`.
- Any change to the action contract (renaming, removing, or re-defaulting an input or output,
  or altering exit-code meanings), to config tier order or merge rules, or adding a service to
  the bundled Marketplace defaults, which enables it for every consumer that has not opted out.

### Never

- Commit secrets, tokens, or credentials to config, templates, tests, or fixtures.
- Weaken the guard that stops the engine clobbering unmanaged content: byte-for-byte
  preservation outside markers, the fail-safe on ambiguous or malformed markers, the
  depth-counted protection in `dedupe_lines_outside_block`, or the pre-write recheck.
- Use an unpinned `uses:` ref; every action reference is a commit SHA with a version comment.
- Push directly to `main`, move a tag by hand, or bypass `release-promote.yml`.
- Add commit, push, or pull-request logic here, or hand-edit centrally managed files and
  managed blocks in this repository.
