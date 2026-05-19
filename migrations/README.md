# Migrations

## How to run

1. Open your Supabase project → **SQL Editor**.
2. Copy-paste the contents of **`001_init_schema.sql`** and click **Run**.
3. Copy-paste the contents of **`002_migrate_kv_to_tables.sql`** and click **Run**.

Run `001` first — `002` depends on the tables it creates.

Both scripts are idempotent: running them a second time is safe.

After migration the KV table (`kv_store`) is left in place but is no longer read from by the API.

## Rollback (development only)

```sql
drop table if exists public.qr_nonces cascade;
drop table if exists public.parking_sessions cascade;
drop table if exists public.bookings cascade;
drop table if exists public.spots cascade;
drop table if exists public.parkings cascade;
drop table if exists public.profiles cascade;
```

**Never run rollback on production** — it will delete all parking history and user profiles.
