# Alembic Migration Demo

## 1. Clean Database

Commands:

```bash
make migrate
```

Result:
All migrations applied successfully.

## 2. Existing Seed Data Migration

Commands:

```bash
make migration-test
```

Flow:

```text
base
 ↓
initial migration
 ↓
seed existing data
 ↓
priority migration
 ↓
backfill priority
 ↓
NOT NULL
```

Result:
Existing projects successfully received priority values.

## 3. Upgrade

```bash
make migrate
```

Result:
Successfully upgraded to head.

## 4. Downgrade

```bash
make migrate-previous
```

Result:
Successfully downgraded one migration.

## 5. Migration Safety

Explain:

- nullable → backfill → NOT NULL
- why direct NOT NULL would fail
- why downgrade can delete data

### Nullable → backfill → NOT NULL
The project priority migration adds the column as nullable first so existing rows are not blocked. After existing data is backfilled using real values derived from the deadline, the column is altered to `NOT NULL`.

### Why direct NOT NULL would fail
If the migration tries to add a non-nullable column to a table with existing rows, the database rejects the migration because current rows have no value for that column. This would break the migration at runtime.

### Why downgrade can delete data
A downgrade removes the column or table definition. That means any data stored in that column is no longer available in the downgraded schema. Downgrades are useful for development rollback testing, but they are not always data-safe in production.

## Loom

- Loom URL: https://www.loom.com/share/2ea7473126354d988d79d163a829832c
