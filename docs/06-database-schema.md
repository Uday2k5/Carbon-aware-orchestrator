# SQLite schema (`results/cao.sqlite`, `cao.db.Database`)

| table | columns | written by |
| --- | --- | --- |
| `carbon_intensity` | timestamp (UTC iso), region, ci_g_per_kwh, source — PK(timestamp, region) | `cao carbon fetch/synth --store` |
| `migration_measurements` | timestamp, state_gb, bytes_state, checkpoint_s/j, transfer_s/j, bytes_transferred, restore_s/j, transport, energy_method, repeat | `cao profile --store` |
| `energy_samples` | timestamp, job_id, region, joules, seconds, method | controller / Kepler |
| `decisions` | timestamp, job_id, action, from_region, target_region, resume_at_h, saved_g, migration_g, payback_h, remaining_h, reason, mode, applied | controller |
| `migrations` | timestamp, job_id, from_region, to_region, state_gb, checkpoint_s, reschedule_s, total_s, success, detail(json) | controller `migrate()` |
| `sim_results` | timestamp, experiment, policy, forecast, total_g, exec_g, migration_g, migrations, deadline_violations, sla_violation_slots, regret_g, params(json) | experiments (optional) |

CSV mirrors of everything live in `results/` and `data/processed/` for notebooks.
