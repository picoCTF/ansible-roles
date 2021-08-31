# atop

Installs [`atop`](https://github.com/Atoptool/atop) on a host and configures it to log process metrics (at a 60s granularity, by default).

This enables investigation of historical process behavior in the case of unexpectedly high CPU or memory usage, which can be useful if players manage to exploit a challenge or escape from a container.

To view logged metrics in atop, specify a log file using the `-r` flag:

```shell
$ atop -r /var/log/atop/atop_YYYYMMDD
```

then use the `t` and `T` commands to step forwards and backwards in time. See `atop --help` for a
listing of additional flags to modify the output. Some flags which may be particularly useful are:

- `-c` to include command line information for each process
- `-v` to view parent process IDs and other ID info (mutually exclusive with `-c`)
- `-m` to replace CPU usage % with memory usage %
- `-C` to sort by CPU usage (the default, unless `-m` is provided)
- `-M` to sort by memory usage

## Role Variables

| Name | Description | Default |
| --- | --- | --- |
| `log_interval_secs` | How frequently atop should log the system state (in seconds) | 60 |
| `log_retention_days` | How long logs should be stored (in days) | 28 |
| `upgrade` | Whether to upgrade atop if already installed | false |
