# Mathematical model

Units: energy J internally, kWh at the carbon step (1 kWh = 3.6 MJ); CI in gCO2e/kWh; carbon in g.

## Execution carbon

    C_exec(j, r) = Σ_t  P_j [kW] · Δt [h] · CI_{r,t} [g/kWh]

## Migration carbon (measured model)

    E_phase(S) = a_phase · S + b_phase          phase ∈ {checkpoint, transfer, restore}, S in GB
    E_network(S) = S · η                        η = kWh/GB (0.06 default, EXP-04 sensitivity)

    C_mig(S, CI_src, CI_dst) = kWh(E_ckpt) · CI_src + kWh(E_xfer) · CI_src
                             + E_network · ½(CI_src + CI_dst) + kWh(E_restore) · CI_dst

`a`, `b` per phase come from `MigrationCostModel.fit()` on profiler output (least squares,
R² reported). Downtime is fitted the same way: `d(S) = d_gb · S + d_0` seconds.

## Carbon Payback Period

    rate_r  = P_j · CI_r                                   [g/h]
    CPP     = C_mig / (rate_src − rate_dst)                [h]      (∞ if destination not cleaner)
    MOVE  ⇔ remaining_h > CPP  ⇔ saved − C_mig > 0

Plan example: C_mig = 500 g, 600 g/h → 100 g/h ⇒ CPP = 1 h.

## Temporal shift (WAIT)

For a deferrable job of d slots, release e, deadline D:

    start* = argmin_{s ∈ [e, D−d]} Σ_{t=s}^{s+d−1} CI_{r,t}      (contiguous window)

WAIT if start* > e, else run now. Combined with regions: minimise
`P·Σ CI_{r,t} + C_mig(origin→r at start*)` over (r, start*).

## SLA

    r allowed ⇔ RTT(user_region, r) ≤ SLA_j       (hard constraint; web services)

## MILP (`cao/decision/milp.py`)

Sets J, R, T. Variables exist only inside each job's window [release, deadline).
`x_{j,r,t} ∈ {0,1}` (executes), `l_{j,r,t} ∈ {0,1}` (state resides), `dep_{j,r,t}, arr_{j,r,t} ∈ [0,1]`
(state left / arrived at r between t−1 and t), `q_{j,r,t} ∈ [0,1]` (start/resume without an
arrival), `u_j ≥ 0` (unmet slots).

    C_departure(S, CI_src) = kWh(E_ckpt + E_xfer)·CI_src + ½ E_network·CI_src
    C_arrival(S, CI_dst)   = kWh(E_restore)·CI_dst        + ½ E_network·CI_dst
    (one move = one departure + one arrival = C_mig(S, CI_src, CI_dst) exactly)

    min  Σ x·P_j·Δt·CI_{r,t}  +  Σ dep·C_departure + arr·C_arrival  +  Σ q·kWh(E_ckpt+E_restore)·CI_{r,t}
         + λ_deadline Σ u_j  +  ε Σ (t+1)·x

    s.t. Σ_r l_{j,r,t} = 1                          state lives in exactly one region
         x_{j,r,t} ≤ l_{j,r,t}                       run only where the state is
         Σ_{r,t} x_{j,r,t} + u_j = remaining_slots_j
         x = 0 outside [release_j, deadline_j) and outside SLA-feasible regions
         dep_{j,r,t} ≥ l_{j,r,t−1} − l_{j,r,t};  arr_{j,r,t} ≥ l_{j,r,t} − l_{j,r,t−1}
             (at t = release the constant current residence plays l_{j,r,t−1})
         q_{j,r,t} ≥ x_{j,r,t} − x_{j,r,t−1} − arr_{j,r,t}
         always-on services: Σ_r x_{j,r,t} = 1 ∀t
         non-preemptible jobs: single contiguous block (start variables)
         Σ_j cpu_j · x_{j,r,t} ≤ capacity_r

`ε` (1e-3 g) breaks ties towards finishing early; `λ_deadline` = 1e4 g per unmet slot dominates
any per-slot carbon (≤ ~250 g) so deadlines are soft in form but hard in effect. Solved with CBC
via PuLP (0.5 % relative gap, time limit); a dense tick (20 concurrent jobs, 5 regions, 24 slots)
takes a few seconds on a laptop, sparse ticks well under a second. `dep`/`arr`/`q` are
continuous: with binary `l`, `x` they are tight at the optimum because their costs are positive.

Decoding the first slot: not running & later slot planned → WAIT; running elsewhere → MOVE;
same region but a greener feasible region exists → REFUSE (with payback numbers); else HOLD.
