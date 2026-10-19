# Migration-tool recipes

Snippets for `zero-downtime-migrations` section 7. Each shows: a concurrent index outside a transaction,
a NOT VALID constraint plus a separate validation, and the tool's own lock/statement timeout hook where it
has one. Check the tool version in the repo before copying; transaction-handling options move between
releases.

## Alembic (SQLAlchemy)

```python
# versions/0042_orders_customer_idx.py
from alembic import op

def upgrade():
    op.execute("SET lock_timeout = '2s'")
    with op.get_context().autocommit_block():          # commits whatever ran before this block
        op.create_index("orders_customer_id_idx", "orders", ["customer_id"],
                        postgresql_concurrently=True, if_not_exists=True)

def downgrade():
    with op.get_context().autocommit_block():
        op.drop_index("orders_customer_id_idx", table_name="orders",
                      postgresql_concurrently=True, if_exists=True)
```

```python
# versions/0043_orders_customer_fk_not_valid.py
def upgrade():
    op.execute("SET lock_timeout = '2s'")
    op.create_foreign_key("orders_customer_id_fk", "orders", "customers",
                          ["customer_id"], ["id"], postgresql_not_valid=True)

# versions/0044_validate_orders_customer_fk.py  (separate file, separate deploy step)
def upgrade():
    op.execute("SET statement_timeout = '4h'")
    op.execute("ALTER TABLE orders VALIDATE CONSTRAINT orders_customer_id_fk")
```

- Configure `transaction_per_migration=True` in `env.py` when any migration uses `autocommit_block()`.
- `alembic upgrade head --sql` renders the SQL (offline mode) for review.
- Autogenerate never detects renames (it emits drop + add, which loses data) and misses server
  defaults, CHECK constraints and enum changes; read every generated op.
- `if_not_exists` / `if_exists` on `create_index` / `drop_index` exist in current Alembic (checked on 1.20);
  drop them on old versions. `postgresql_not_valid=True` is passed through to SQLAlchemy's
  `ForeignKeyConstraint` and renders `NOT VALID`.

## Django

```python
# 0042_orders_customer_idx.py
from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models

class Migration(migrations.Migration):
    atomic = False                                   # CONCURRENTLY cannot run in a transaction
    dependencies = [("shop", "0041_previous")]
    operations = [
        AddIndexConcurrently("order", models.Index(fields=["customer"], name="orders_customer_id_idx")),
    ]
```

```python
# 0043: constraint without validation; 0044 (separate file): ValidateConstraint
from django.contrib.postgres.operations import AddConstraintNotValid, ValidateConstraint
from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [("shop", "0042_orders_customer_idx")]
    operations = [
        AddConstraintNotValid("order", models.CheckConstraint(
            condition=models.Q(customer__isnull=False), name="orders_customer_id_nn")),
    ]
# 0044: operations = [ValidateConstraint("order", "orders_customer_id_nn")]
```

`CheckConstraint(condition=...)` is the Django 5.1+ spelling; older versions use `check=`.

Dropping a column safely: first a migration that removes the field from Django's state only, deployed
with the code that no longer uses it; the physical drop comes in a later release.

```python
migrations.SeparateDatabaseAndState(
    state_operations=[migrations.RemoveField("user", "fullname")],
    database_operations=[],                  # column stays until the contract release
)
```

- `python manage.py sqlmigrate shop 0043` prints the SQL; `python manage.py lintmigrations` runs
  django-migration-linter.
- Data backfills belong in a management command, not `RunPython` inside the schema migration.

## Prisma Migrate

```bash
npx prisma migrate dev --create-only --name orders_customer_idx   # generate, do not apply
# edit prisma/migrations/<ts>_orders_customer_idx/migration.sql:
#   CREATE INDEX CONCURRENTLY IF NOT EXISTS "orders_customer_id_idx" ON "orders" ("customer_id");
npx prisma migrate deploy                                         # CI/CD and production
```

Keep the CONCURRENTLY statement as the only statement in its migration and rehearse on staging: whether
the file runs inside a transaction has differed across Prisma versions. `prisma migrate diff` shows the
SQL between two schema states for review.

## Flyway

```text
db/migration/V42__orders_customer_idx.sql
    SET lock_timeout = '2s';
    CREATE INDEX CONCURRENTLY IF NOT EXISTS orders_customer_id_idx ON orders (customer_id);
db/migration/V42__orders_customer_idx.sql.conf
    executeInTransaction=false
```

Mixing transactional and non-transactional statements in one migration needs the `mixed=true` setting;
prefer one non-transactional statement per file instead.

## Liquibase (formatted SQL)

```sql
--liquibase formatted sql
--changeset alice:42 runInTransaction:false
CREATE INDEX CONCURRENTLY IF NOT EXISTS orders_customer_id_idx ON orders (customer_id);
--rollback DROP INDEX CONCURRENTLY IF EXISTS orders_customer_id_idx;
```

If a multi-statement `runInTransaction:false` changeset fails half way, the changelog table is left
inconsistent; keep such changesets to one statement. `liquibase update-sql` prints the SQL.

## Atlas

```sql
-- migrations/20261019120000_orders_customer_idx.sql
-- atlas:txmode none
CREATE INDEX CONCURRENTLY IF NOT EXISTS orders_customer_id_idx ON orders (customer_id);
```

```bash
atlas migrate hash                                     # after editing a generated file
atlas migrate lint --dev-url "docker://postgres/16/dev?search_path=public" --git-base main
atlas migrate apply --url "$DATABASE_URL" --tx-mode file
```

## golang-migrate

```bash
migrate create -ext sql -dir db/migrations -seq orders_customer_idx
# db/migrations/000042_orders_customer_idx.up.sql contains exactly one statement:
#   CREATE INDEX CONCURRENTLY IF NOT EXISTS orders_customer_id_idx ON orders (customer_id);
migrate -path db/migrations \
  -database "postgres://app@db:5432/shop?sslmode=require&x-statement-timeout=900000" up
```

Several statements in one file are sent in one Exec, which PostgreSQL runs as one implicit transaction,
so CONCURRENTLY must be alone in its file.

## sqlx (Rust)

```sql
-- no-transaction
CREATE INDEX CONCURRENTLY IF NOT EXISTS orders_customer_id_idx ON orders (customer_id);
```

The `-- no-transaction` line must be the first line of the migration file.

## Diesel (Rust)

```text
migrations/2026-10-19-120000_orders_customer_idx/up.sql
    CREATE INDEX CONCURRENTLY IF NOT EXISTS orders_customer_id_idx ON orders (customer_id);
migrations/2026-10-19-120000_orders_customer_idx/metadata.toml
    run_in_transaction = false
```

## Rails (strong_migrations)

```ruby
class AddIndexOnOrdersCustomerId < ActiveRecord::Migration[8.0]
  disable_ddl_transaction!
  def change
    add_index :orders, :customer_id, algorithm: :concurrently
  end
end

# dropping a column: first ignore it, deploy, then remove it in a later migration
class Order < ApplicationRecord
  self.ignored_columns += ["legacy_status"]
end
```

`strong_migrations` raises on unsafe operations and suggests the safe variant; wrap a reviewed exception
in `safety_assured { ... }`. Its initializer can set `StrongMigrations.lock_timeout` and
`StrongMigrations.statement_timeout`.

## squawk configuration

```toml
# .squawk.toml
pg_version = "16.0"
assume_in_transaction = true          # most tools wrap files in a transaction
excluded_rules = ["prefer-bigint-over-int"]   # example only; keep exclusions rare and commented
excluded_paths = ["*_legacy_*.sql"]
```

```bash
squawk 'migrations/*.sql'                                   # lint files (globs allowed)
git diff --name-only origin/main -- 'migrations/*.sql' | xargs -r squawk
```

Rule names worth knowing: `require-concurrent-index-creation`, `require-concurrent-index-deletion`,
`ban-concurrent-index-creation-in-transaction`, `constraint-missing-not-valid`,
`adding-foreign-key-constraint`, `adding-not-nullable-field`, `adding-field-with-default`,
`changing-column-type`, `renaming-column`, `renaming-table`, `ban-drop-column`, `disallowed-unique-constraint`,
`require-timeout-settings`, `prefer-robust-stmts`, `prefer-bigint-over-int`, `prefer-text-field`,
`prefer-timestamptz`, `prefer-identity`.
