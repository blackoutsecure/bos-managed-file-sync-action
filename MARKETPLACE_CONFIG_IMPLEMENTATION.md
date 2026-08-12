# Four-Tier Config Cascade Implementation Summary

## ✅ What Was Implemented

### 1. **Marketplace Config (Tier 0) — Built-in Best Practices**
- **File**: `src/sync_kit/marketplace-config.json` (shipped with action, read-only)
- **Recommended name for user configs**: `bos-sync-marketplace.json`
- **Default**: Enabled (`use_marketplace_config: true`)
- **Includes**:
  - Services: `common`, `lf_line_endings`, `markdownlint` (universally safe)
  - Exclusions: `dependabot.yml`, `.dependabot/*`, `renovate.json`, lock files (auto-update configs shouldn't sync)
  - Standard `marker_namespace: managed-file-sync`
  - Managed note about Blackout Secure

### 2. **Four-Tier Config Cascade**
```
Tier 0: Marketplace config (shipped, default ON)
  ↓ (marketplace overrides if use_marketplace_config: true)
Tier 1: Org-level global config (optional, .github/bos-managed-sync-global.json)
  ↓
Tier 2: Repo-specific config (optional, bos-universal-config.json)
  ↓
Tier 3: Workflow input (CI-level, --services argument)
```

### 3. **Exclusions Rationale** (Built into Marketplace)
- ❌ **`dependabot.yml`, `renovate.json`**: Per-repo automation config; syncing breaks dependency updates
- ❌ **Lock files** (`package-lock.json`, `yarn.lock`, `pnpm-lock.yaml`, `poetry.lock`): Generated artifacts with project-specific dependency trees
- ✅ **Linters & standards** (`common`, `lf_line_endings`, `markdownlint`): Safe, no project-specific data

### 4. **Config Loading & Merging Logic** (config.py)
- New function: `_load_marketplace_config()` — loads bundled marketplace best practices
- Updated: `load_repo_config()` — accepts `use_marketplace` parameter (default True)
- Merge strategy:
  - Scalars: lower tiers override upper tiers
  - Objects: deep-merged (combine all fields)
  - Arrays (services): tier 2 replaces tier 0 (not merged)
  - Can disable marketplace via `use_marketplace_config: false` in any tier

### 5. **Real Config Files in Repo**
- **`.github/bos-managed-sync-global.json`** (NEW) — Org-level defaults for Blackout Secure
  - Services: `common`, `lf_line_endings`, `markdownlint`, `dotfiles`
  - Variables: org_name, support_email, license
- **Removed**: Example files (`.example`) — marketplace config now serves as example

### 6. **CLI Updates** (cli.py)
- Already updated in previous session to accept `--global-config`
- Existing `_Plan` class passes both configs to `load_repo_config()`
- Marketplace config loads automatically with no extra flags needed

### 7. **GitHub Action Input** (action.yml)
- Added comment explaining four-tier cascade
- Note that marketplace config is tier 0, enabled by default
- Global config is tier 1, repo config is tier 2

### 8. **Comprehensive README Documentation**
- **New section**: "🏗️ Configuration inheritance and layering"
- Explains all four tiers with clear diagrams
- Rationale for exclusions (dependabot, lock files, etc.)
- Four detailed examples:
  1. Marketplace only (default)
  2. Marketplace + Org config
  3. Marketplace + Org + Repo config
  4. Disable marketplace for advanced setup
- Setup instructions for quickest start, org-wide defaults, repo-only
- Precedence rules for overlapping config fields

### 9. **Tests** (+5 new tests)
- `test_marketplace_config_is_loaded_by_default()` — verifies marketplace loads
- `test_marketplace_config_can_be_disabled()` — verifies `use_marketplace: false` works
- `test_repo_config_merges_with_marketplace()` — repo overrides services, inherits other fields
- `test_global_and_repo_configs_merge()` — global + repo merge correctly
- `test_marketplace_global_and_repo_cascade()` — all four tiers cascade correctly

**Result**: 120 tests passing (was 115, added 5)

## 📋 File Changes Summary

| File | Changes |
|------|---------|
| `src/sync_kit/marketplace-config.json` | NEW: Built-in marketplace best practices |
| `.github/bos-managed-sync-global.json` | NEW: Real org-level config for Blackout Secure |
| `src/sync_kit/config.py` | +99 lines: `_load_marketplace_config()`, updated `load_repo_config()` |
| `src/sync_kit/cli.py` | No changes needed (already wired from previous session) |
| `action.yml` | +26 lines: Documentation of four-tier cascade |
| `README.md` | +281 lines: Comprehensive config layering documentation |
| `test/test_config.py` | +99 lines: 5 new marketplace tests |
| `bos-universal-config.json` | 1 line: Updated comment to reference tier system |

## 🎯 User Configuration Pattern

### For new users (recommended):
```yaml
- uses: blackoutsecure/bos-managed-file-sync-action@v1
```
→ Marketplace defaults apply automatically

### For org standardization:
```yaml
- uses: blackoutsecure/bos-managed-file-sync-action@v1
  with:
    global_config_path: '.github/bos-managed-sync-global.json'
```
→ Marketplace + org defaults

### For repo-specific customization:
```yaml
- uses: blackoutsecure/bos-managed-file-sync-action@v1
  with:
    global_config_path: '.github/bos-managed-sync-global.json'
    config_path: 'bos-universal-config.json'
```
→ Full cascade with repo overrides

## 🔍 What's NOT Synced by Default (Marketplace Exclusions)

```json
"exclude_paths": [
  "dependabot.yml",           // Auto-update config is per-repo
  ".dependabot/*",
  "renovate.json",            // Same reason
  ".renovate.json",
  ".renovaterc*",
  "package-lock.json",        // Generated, project-specific
  "yarn.lock",
  "pnpm-lock.yaml",
  "Gemfile.lock",
  "poetry.lock"
]
```

**Rationale**: These files are either generated (lock files) or contain repo-specific automation rules (renovate/dependabot). Syncing them breaks their automation.

## ✨ Best Practices Included

- ✅ Common ignore rules (`.gitignore`)
- ✅ Line ending normalization (`.gitattributes`)
- ✅ Markdown linting config (`.markdownlint.json`)
- ❌ Skips auto-update tools (dependabot, renovate)
- ❌ Skips lock files (npm, yarn, pip, bundler, poetry)

## 🚀 Migration from Three-Tier to Four-Tier

Existing users with three-tier setup:
- Marketplace (tier 0) automatically enabled
- Org config (tier 1) stays at tier 1
- Repo config (tier 2) stays at tier 2
- **No breaking changes** — marketplace defaults are safe conservative practices

To disable marketplace (if needed):
```json
{"managed_file_sync": {"use_marketplace_config": false}}
```

## 📚 Documentation

- README section: "🏗️ Configuration inheritance and layering" (~350 lines)
- Four examples showing each tier combination
- Setup instructions from quickest to most comprehensive
- Clear precedence rules for conflicting configs
