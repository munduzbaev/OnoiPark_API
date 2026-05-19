-- OnoiPark Phase 2 — Initial schema
-- Run via Supabase SQL editor. Script is idempotent (IF NOT EXISTS everywhere).

-- Profile metadata that doesn't fit in auth.users.user_metadata
create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  plate_number text unique not null,
  phone_number text not null,
  name text,
  role text not null default 'driver',  -- 'driver' | 'admin' | 'scanner'
  notification_settings jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);
create index if not exists profiles_plate_idx on public.profiles(plate_number);

create table if not exists public.parkings (
  id text primary key,
  name text not null,
  address text,
  lat double precision,
  lng double precision,
  total_spots int not null,
  price_per_hour numeric not null default 100,
  free_minutes int not null default 60,
  features text[] not null default '{}',
  created_at timestamptz not null default now()
);

create table if not exists public.spots (
  id text primary key,
  parking_id text not null references public.parkings(id) on delete cascade,
  number int not null,
  status text not null default 'available',  -- 'available' | 'booked' | 'occupied'
  booked_by uuid references auth.users(id) on delete set null,
  unique (parking_id, number)
);
create index if not exists spots_parking_idx on public.spots(parking_id);

create table if not exists public.bookings (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  parking_id text not null references public.parkings(id),
  spot_number int not null,
  status text not null default 'active',  -- 'active' | 'completed' | 'cancelled' | 'expired'
  created_at timestamptz not null default now(),
  expires_at timestamptz not null
);
create index if not exists bookings_user_idx on public.bookings(user_id);
create index if not exists bookings_status_idx on public.bookings(status);

create table if not exists public.parking_sessions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references auth.users(id) on delete set null,
  parking_id text references public.parkings(id),
  spot_number int,
  status text not null default 'waiting',  -- 'waiting' | 'active' | 'exiting' | 'completed'
  entered_at timestamptz,
  exited_at timestamptz,
  cost numeric not null default 0,
  created_at timestamptz not null default now()
);
create index if not exists sessions_user_idx on public.parking_sessions(user_id);
create index if not exists sessions_status_idx on public.parking_sessions(status);

-- One-shot QR nonces — prevents replay attacks
create table if not exists public.qr_nonces (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  used boolean not null default false,
  used_at timestamptz,
  created_at timestamptz not null default now(),
  expires_at timestamptz not null
);
create index if not exists qr_nonces_user_idx on public.qr_nonces(user_id, used);

-- Enable Realtime on parking_sessions so the local Python bridge can react
do $$
begin
  if not exists (
    select 1 from pg_publication_tables
    where pubname = 'supabase_realtime'
    and schemaname = 'public'
    and tablename = 'parking_sessions'
  ) then
    alter publication supabase_realtime add table public.parking_sessions;
  end if;
end $$;
