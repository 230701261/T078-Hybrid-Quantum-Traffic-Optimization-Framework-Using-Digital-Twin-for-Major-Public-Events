-- ====================================================================
-- SUPABASE / POSTGRESQL MIGRATION: QUANTUM TRAFFIC DIGITAL TWIN
-- Version: 1.0.0
-- ====================================================================

-- 1. Simulations Table
create table if not exists simulations (
    id text primary key,
    name text not null,
    scenario text not null default 'normal_day',
    status text not null default 'running',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists idx_simulations_status on simulations(status);

-- 2. Scenarios Table
create table if not exists scenarios (
    id text primary key,
    simulation_id text references simulations(id) on delete set null,
    name text not null,
    weather text not null default 'Clear',
    total_vehicles integer not null default 0,
    vip_active boolean not null default false,
    construction_active boolean not null default false,
    crowd_surge boolean not null default false,
    parking_overflow boolean not null default false,
    metadata jsonb default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create index if not exists idx_scenarios_simulation on scenarios(simulation_id);

-- 3. Optimization Runs Table
create table if not exists optimization_runs (
    id uuid primary key default gen_random_uuid(),
    message_id text unique,
    simulation_id text not null,
    scenario_id text not null,
    optimizer text not null, -- 'Quantum' (QAOA) or 'Classical'
    bitstring varchar(18) not null,
    status text not null default 'created',
    objective_value double precision,
    runtime_seconds double precision,
    error_message text,
    applied_to_sumo boolean not null default false,
    applied_at timestamptz,
    created_at timestamptz not null default now(),
    completed_at timestamptz,
    constraint optimization_runs_status_chk
        check (status in ('created', 'queued', 'running', 'completed', 'applied', 'failed'))
);

create index if not exists idx_optimization_runs_simulation on optimization_runs(simulation_id);
create index if not exists idx_optimization_runs_scenario on optimization_runs(scenario_id);
create index if not exists idx_optimization_runs_status on optimization_runs(status);

-- 4. Traffic Actions Table (Extracted decisions from bitstring)
create table if not exists traffic_actions (
    id uuid primary key default gen_random_uuid(),
    optimization_run_id uuid not null references optimization_runs(id) on delete cascade,
    action_type text not null, -- 'route_diversion', 'signal_extension', 'temporary_restriction'
    logical_target text not null, -- Quantum target name (e.g. 'Anna Salai', 'J1')
    canonical_target text not null, -- Digital Twin target (e.g. 'corridor_mount_road', 'junction_nw')
    sumo_target_id text not null, -- Real SUMO target (e.g. 'E_WEST_1', 'J_NW')
    enabled boolean not null default true,
    old_value double precision,
    new_value double precision,
    delta_value double precision,
    demand double precision,
    capacity double precision,
    pressure double precision,
    overflow double precision,
    rerouted double precision,
    remaining_queue double precision,
    created_at timestamptz not null default now()
);

create index if not exists idx_traffic_actions_run on traffic_actions(optimization_run_id);
create index if not exists idx_traffic_actions_type on traffic_actions(action_type);

-- 5. Optimization Benefits Table
create table if not exists optimization_benefits (
    id uuid primary key default gen_random_uuid(),
    optimization_run_id uuid not null references optimization_runs(id) on delete cascade,
    travel_time_saved_minutes double precision not null default 0.0,
    queue_reduction_percent double precision not null default 0.0,
    energy_or_fuel_saved_percent double precision default 0.0,
    created_at timestamptz not null default now()
);

create index if not exists idx_optimization_benefits_run on optimization_benefits(optimization_run_id);

-- 6. Optimization Results Table (JSONB for quantum state vectors & QUBO matrices)
create table if not exists optimization_results (
    id uuid primary key default gen_random_uuid(),
    optimization_run_id uuid not null references optimization_runs(id) on delete cascade,
    qaoa_result jsonb,
    qubo_result jsonb,
    sumo_input_snapshot jsonb,
    metadata jsonb default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create index if not exists idx_optimization_results_run on optimization_results(optimization_run_id);
