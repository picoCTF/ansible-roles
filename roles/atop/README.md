# atop monitoring

Installs [`atop`](https://github.com/Atoptool/atop) on a host and configures it to log process metrics (at a 60s granularity, by default).

This enables investigation of historical process behavior in the case of unexpectedly high CPU or memory usage, which can be useful if players manage to exploit a challenge or escape from a container.

## Role Variables

| Name | Description | Default |
| --- | --- | --- |
| `log_interval_secs` | How frequently atop should log the system state (in seconds) | 60 |
| `log_retention_days` | How long logs should be stored (in days) | 28 |
