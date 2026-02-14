# UI Field States

Project Page fields use a unified live state model:

- `neutral`: field is unset or hidden.
- `ok`: field is set and has no active `warn` or `fatal` issue.
- `warn`: at least one warning issue is active.
- `fatal`: at least one fatal issue is active.

Color mapping follows the dark theme tokens:

- `ok` -> existing green success token.
- `warn` -> muted amber border.
- `fatal` -> muted red border.
- `neutral` -> default border.

Implementation notes:

- State is applied via widget property `fieldState`.
- Live validation uses a debounce (`200ms`) to avoid jitter while typing.
- Unset semantics are preserved: empty input stays unset and is never coerced to `0`.
- `warn` and `fatal` show a one-line helper under the field plus a tooltip with short rationale and suggestion.

Validation pipeline:

1. Normative rules from the compatibility engine (`app/knowledge/ath/ruleset.v1.json`) are converted to field issues.
2. Experiment-based hints are loaded from the latest available:
   - `reports/ath_experiments/range_suggestions.v*.json`
   - `reports/ath_experiments/compat_rule_candidates.v*.json`
3. Field merge policy is deterministic: `fatal > warn > ok > neutral`.

Caveat:

- Experiment-derived warnings are guidance, not strict causality. Treat them as risk indicators and validate with counterfactual runs where needed (see `reports/ath_experiments/precision_plan.md`).
