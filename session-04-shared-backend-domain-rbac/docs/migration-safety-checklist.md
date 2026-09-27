# Migration Safety Checklist

## Migration Commands

- `make migrate` — applies all migrations up to the latest revision.
- `make migrate-next` — applies the next migration only.
- `make migrate-previous` — rolls back the most recent migration.
- `make migrate-base` — rolls the database back to the base revision.
- `make seed` — inserts the normal seed data.
- `make migration-test` — recreates the existing-data migration scenario by applying the initial schema, inserting seed data, and then applying the next migration.

## Existing-Data Migration Safety

When a migration adds a new `NOT NULL` field to an existing table, the migration must provide a safe strategy for existing rows, such as a default value or a backfill.

For example, the `project.priority` migration should first add the column as nullable, backfill existing projects, and only then change the column to `NOT NULL`.

The pattern should be:

```
Base
  ↓
Initial migration
  ↓
Insert existing seed data
  ↓
Next migration
  ↓
Backfill existing rows
  ↓
Latest schema
```

This demonstrates that the migration can safely handle data that existed before the new field was introduced.

## Rollback Safety

`make migrate-previous` should successfully roll back the latest migration when rollback is supported.

However, a downgrade that removes a column or table can permanently remove data stored in that schema element. Therefore, successful execution of a downgrade does not necessarily mean the operation is data-safe.

For example, rolling back the `project.priority` migration removes the `priority` column and therefore any stored priority values in that column.

Downgrades should be treated as a development/testing rollback mechanism unless the migration explicitly preserves the affected data or a production recovery strategy is available.

## Checklist for Every Migration

- [ ] Migration upgrades cleanly from the previous revision.
- [ ] Migration is tested against a realistic existing-data scenario when it affects current rows.
- [ ] `NOT NULL` additions include an explicit default or backfill strategy.
- [ ] Backfill logic is based on real business rules and existing data values.
- [ ] Downgrade path has been reviewed and is safe or clearly marked as destructive.
- [ ] The migration does not silently drop business-critical data.
