# OS

## Description

Various OS-level settings suitable for hosts used as picoCTF platform components like challenge
servers or webshell toolbox servers.

Like all other roles in this collection, this currently targets contemporary Ubuntu releases only.

### Limited maximum journald size

This role
[limits](https://www.freedesktop.org/software/systemd/man/journald.conf.html#SystemMaxUse=) the
maximum size of the `journald` journal to less than the 4GB default cap, in order to prevent logged
events such as SSH connections or the launching of Docker containers from exhausting a small root
storage device at runtime.

### Custom ephemeral port range

The operating system's ephemeral port range (`/proc/sys/net/ipv4/ip_local_port_range`) can be
customized. This may be useful in order to make sure that the ephemeral port range does not conflict
with application-specific port assignments, such as [`cmgr_port_range`](../cmgr/README.md).

## Role Variables

| Name | Description | Default |
| --- | --- | --- |
| `upgrade_packages` | Run `apt-get update && apt-get upgrade` when this role is run. Be careful when running this, as packages used by other roles may be affected. Note that (unless manually disabled), Ubuntu already automatically installs essential security updates via `unattended-upgrades`. | `false` |
| `journald_max_size` | Maximum size of retained journald logs. Applies to both volatile and persistent log storage. | `500M` |
| `ephemeral_port_range` | Custom ephemeral port range for the operating system, e.g. `32768-60999`. Note that **the host will restart** if this value is changed, to ensure that all services read the new range. | unset |
