# Release Notes Draft

## Highlights
- Centralized service registry model: marketplace config is now the built-in source of default services.
- Service merge behavior improved: `services` append by default across marketplace, global, and repo tiers.
- New service override control: `use_marketplace_services` allows replacing inherited services when needed.
- Exclusion behavior improved: `exclude_services` (and `disabled_services`) now cleanly remove inherited marketplace/global services at the global or repo scope.

## Usability and Documentation
- Simplified public README structure for marketplace users.
- Added concrete merge and exclusion examples for global + repo layering.
- Clarified built-in service behavior and managed template path usage.
- Synchronized universal sync, security, action-test, and Marketplace caller contracts with `bos-automation-hub`.
- Added Marketplace repository metadata refresh support to the managed caller.

## Security and Safety
- Added explicit guidance to avoid secrets in managed configs/templates.
- Reinforced least-privilege workflow guidance and untrusted PR safety recommendations.
- Kept strict path containment and no-code-execution guarantees documented.

## Internal Quality Improvements
- Reduced redundant config resolution work on CLI path.
- Hardened config type validation for booleans/lists to prevent silent misconfiguration.
- Removed stale internal implementation document from the repository root.
- Added repository-level anti-drift tests for shared hub configuration and kicker contracts.

## Validation
- Test suite: 144 passed.
- Linting: all checks passed.
- Action metadata and README generated table checks: passed.
