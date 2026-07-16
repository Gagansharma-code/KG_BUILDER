-- =============================================================================
-- Migration 003 — pins.alternate_functions TEXT[] → JSONB
-- =============================================================================
--
-- Why:
--   Phase 0 schema draft changes PinDefinition.alternate_functions from
--   list[str] to list[AlternateFunction] with shape:
--     { "name": str, "af_index": int|null, "peripheral": str|null }
--   Postgres TEXT[] cannot store structured objects. Widen to JSONB.
--
-- Chosen approach (Option A):
--   ALTER COLUMN to JSONB. Existing string elements (if any) are wrapped as
--   {"name": <elem>, "af_index": null, "peripheral": null}.
--
-- Deferred (Option B):
--   A pin_alternate_functions junction table can replace JSONB later if AF
--   cardinality or query patterns require it.
--
-- Also adds:
--   pins.default_function — reset-state function (PinDefinition.default_function)
--
-- DO NOT auto-run in app code. Apply during deployment / DBA upgrade window.
-- Numbered 003 because 002_ann_index_helper.sql already exists.
-- =============================================================================

BEGIN;

-- Preserve prior string AFs as AlternateFunction-shaped JSON objects.
-- jsonb_agg is an aggregate, so the USING expression must wrap unnest() in
-- a scalar subquery (plain jsonb_agg(...) at the top level is invalid).
ALTER TABLE pins
  ALTER COLUMN alternate_functions TYPE JSONB
  USING (
    CASE
      WHEN alternate_functions IS NULL THEN NULL
      ELSE (
        SELECT COALESCE(
          jsonb_agg(
            jsonb_build_object(
              'name', elem,
              'af_index', NULL,
              'peripheral', NULL
            )
            ORDER BY ord
          ),
          '[]'::jsonb
        )
        FROM unnest(alternate_functions) WITH ORDINALITY AS u(elem, ord)
        WHERE elem IS NOT NULL
      )
    END
  );

COMMENT ON COLUMN pins.alternate_functions IS
  'JSON array of AlternateFunction objects: '
  '[{ "name": str, "af_index": int|null, "peripheral": str|null }, ...]';

-- Reset-state / default pin function (distinct from multiplexed AFs).
ALTER TABLE pins
  ADD COLUMN IF NOT EXISTS default_function VARCHAR(100);

COMMENT ON COLUMN pins.default_function IS
  'Reset-state pin function from datasheet; maps to PinDefinition.default_function';

COMMIT;
