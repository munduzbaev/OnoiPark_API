-- OnoiPark Phase 2 — One-shot KV → normalized tables migration
-- Run AFTER 001_init_schema.sql.
-- Defensive: rows that don't parse or already exist are skipped.
-- Run once; idempotent via ON CONFLICT DO NOTHING.

do $$
declare
  kv_row record;
  v jsonb;
  migrated_parkings int := 0;
  migrated_spots    int := 0;
  migrated_bookings int := 0;
  migrated_sessions int := 0;
  skipped           int := 0;
begin

  -- ----------------------------------------------------------------
  -- 1. Parkings  (key prefix: 'parking:')
  -- ----------------------------------------------------------------
  for kv_row in
    select key, value from public.kv_store where key like 'parking:%'
  loop
    begin
      v := kv_row.value::jsonb;
      insert into public.parkings (
        id, name, address, lat, lng,
        total_spots, price_per_hour, free_minutes, features
      )
      values (
        v->>'id',
        coalesce(v->>'name', v->>'id'),
        v->>'address',
        (v->>'lat')::double precision,
        (v->>'lng')::double precision,
        coalesce((v->>'totalSpots')::int, (v->>'total_spots')::int, 0),
        coalesce((v->>'pricePerHour')::numeric, (v->>'price_per_hour')::numeric, 100),
        coalesce((v->>'freeMinutes')::int, (v->>'free_minutes')::int, 60),
        coalesce(
          array(select jsonb_array_elements_text(v->'features')),
          '{}'::text[]
        )
      )
      on conflict (id) do nothing;
      migrated_parkings := migrated_parkings + 1;
    exception when others then
      skipped := skipped + 1;
      raise notice 'Skipped parking row % — %', kv_row.key, sqlerrm;
    end;
  end loop;

  -- ----------------------------------------------------------------
  -- 2. Spots  (key prefix: 'spots:')
  -- Stored as an array: [{"id":..,"number":..,"status":..,"parkingId":..}]
  -- ----------------------------------------------------------------
  for kv_row in
    select key, value from public.kv_store where key like 'spots:%'
  loop
    begin
      for v in select jsonb_array_elements(kv_row.value::jsonb)
      loop
        insert into public.spots (id, parking_id, number, status)
        values (
          v->>'id',
          coalesce(v->>'parkingId', v->>'parking_id'),
          (v->>'number')::int,
          coalesce(v->>'status', 'available')
        )
        on conflict (id) do nothing;
        migrated_spots := migrated_spots + 1;
      end loop;
    exception when others then
      skipped := skipped + 1;
      raise notice 'Skipped spots row % — %', kv_row.key, sqlerrm;
    end;
  end loop;

  -- ----------------------------------------------------------------
  -- 3. Bookings  (key prefix: 'booking:')
  -- ----------------------------------------------------------------
  for kv_row in
    select key, value from public.kv_store where key like 'booking:%'
  loop
    begin
      v := kv_row.value::jsonb;
      insert into public.bookings (
        id, user_id, parking_id, spot_number, status, created_at, expires_at
      )
      values (
        (v->>'id')::uuid,
        (coalesce(v->>'userId', v->>'user_id'))::uuid,
        coalesce(v->>'parkingId', v->>'parking_id'),
        (v->>'spotNumber')::int,
        coalesce(v->>'status', 'active'),
        coalesce((v->>'createdAt')::timestamptz, now()),
        coalesce((v->>'expiresAt')::timestamptz, now() + interval '15 minutes')
      )
      on conflict (id) do nothing;
      migrated_bookings := migrated_bookings + 1;
    exception when others then
      skipped := skipped + 1;
      raise notice 'Skipped booking row % — %', kv_row.key, sqlerrm;
    end;
  end loop;

  -- ----------------------------------------------------------------
  -- 4. Sessions  (key prefix: 'session:' and 'history:')
  -- ----------------------------------------------------------------
  for kv_row in
    select key, value from public.kv_store
    where key like 'session:%' or key like 'history:%'
  loop
    begin
      v := kv_row.value::jsonb;
      insert into public.parking_sessions (
        id, user_id, parking_id, spot_number,
        status, entered_at, exited_at, cost, created_at
      )
      values (
        (v->>'id')::uuid,
        (coalesce(v->>'userId', v->>'user_id'))::uuid,
        coalesce(v->>'parkingId', v->>'parking_id'),
        (coalesce(v->>'spotNumber', v->>'spot_number', '0'))::int,
        coalesce(
          v->>'status',
          case when kv_row.key like 'history:%' then 'completed' else 'active' end
        ),
        (coalesce(v->>'startTime', v->>'entered_at', v->>'createdAt'))::timestamptz,
        (coalesce(v->>'endTime', v->>'exited_at'))::timestamptz,
        coalesce((v->>'cost')::numeric, 0),
        coalesce((v->>'createdAt')::timestamptz, now())
      )
      on conflict (id) do nothing;
      migrated_sessions := migrated_sessions + 1;
    exception when others then
      skipped := skipped + 1;
      raise notice 'Skipped session row % — %', kv_row.key, sqlerrm;
    end;
  end loop;

  raise notice '=== Migration complete ===';
  raise notice 'Parkings migrated:  %', migrated_parkings;
  raise notice 'Spots migrated:     %', migrated_spots;
  raise notice 'Bookings migrated:  %', migrated_bookings;
  raise notice 'Sessions migrated:  %', migrated_sessions;
  raise notice 'Rows skipped:       %', skipped;

end $$;
