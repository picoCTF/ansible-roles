# OS

## Description

Various OS-level tweaks suitable for hosts used as long-running picoCTF platform components like
challenge servers or webshell toolbox servers.

Like all other roles in this collection, this currently targets contemporary Ubuntu releases only.

### Limited maximum journald size

This role
[limits](https://www.freedesktop.org/software/systemd/man/journald.conf.html#SystemMaxUse=) the
maximum size of the `journald` journal to less than the 4GB default cap, in order to prevent logged
events such as SSH connections or the launching of Docker containers from exhausting a small root
storage device at runtime.

## Role Variables

| Name | Description | Default |
| --- | --- | --- |
| `journald_max_size` | Maximum size of retained journald logs. Applies to both volatile and persistent log storage. | `500M` |
