# multihost_docker

## Description

Provisions a **cork worker** (the docker-server side of the multi-host challenge
orchestrator). It installs [Docker Engine](https://docs.docker.com/engine/) with the
same challenge-hosting hardening as the `docker` role, then wires the box into a cork
fleet: the remote Docker daemon is exposed over mTLS for the orchestrator (`cmgrd`) to
drive, the box holds read-only pull credentials for the fleet's
[zot](https://zotregistry.dev/) registry, and the
[cork-telemetry](https://github.com/CyLabAcademy/cork-telemetry) health agent runs so
`cmgrd` can gauge worker load.

Once applied, the host is a ready target for `worker-add <ip>` on the orchestrator.

This role is a specialization of the generic [`docker` role](../docker/README.md).

## TLS material

- `docker-{ca-cert,server-cert,server-key}.pem` → `{{ tls_cert_path }}/`, serving the
  daemon socket over TLS on **2376**, which is where `cmgrd` dials.
- `zot-{ca-cert,worker-cert,worker-key}.pem` → `/etc/docker/certs.d/<registry>/`, the
  read-only pull credentials for the registry.

## cork-telemetry

Installs the [cork-telemetry](https://github.com/CyLabAcademy/cork-telemetry) binary from its
GitHub release, plus a systemd unit serving the health endpoint `cmgrd` polls to gauge worker
load.

## Docker resource reaper

[docker-reaper](https://github.com/picoCTF/docker-reaper) is installed and enabled as a
systemd service + timer.

## Usage

```yaml
- hosts: workers
  tasks:
    - include_role:
        name: picoctf.ansible_roles.os
    - include_role:
        name: picoctf.ansible_roles.multihost_docker
      vars:
        multihost_docker_cert_src: "./docker-certs"
        multihost_docker_registry: "1.2.3.4:5000"
        storage_device: /dev/nvme1n1
```

## Role Variables

### General settings

| Name | Description | Default |
| --- | --- | --- |
| `docker_group_users` | Adds these users to the `docker` group, granting daemon access without `sudo`. | `[]` |
| `upgrade` | Whether to upgrade Docker packages if already installed. | `false` |
| `docker_pin_version` | Pin `docker-ce`/`docker-ce-cli` to the version in `vars/main.yml`'s `docker_version_pin_map` and hold them, instead of tracking the repo. The map covers only `jammy` and `noble` — enabling this on any other release fails. | `false` |

This role gathers facts (`ansible_processor_nproc`, `ansible_facts['distribution_release']`), so
plays including it must not set `gather_facts: no`.

### TLS material settings

The daemon always listens on tcp 2376 with mutual TLS alongside the unix socket. cork dials workers over
TLS unconditionally, so there is no option to disable it.

| Name | Description | Default |
| --- | --- | --- |
| `tls_cert_path` | On-host directory holding the dockerd server material; `daemon.json` points `--tlscacert`/`--tlscert`/`--tlskey` here. A `/root` subdir keeps it unreadable to a non-root container escapee. | `/root/.docker_certs` |
| `multihost_docker_cert_src` | Path **on the Ansible controller** holding the six leaf files from `gen-docker-certs.sh` (`docker-ca-cert.pem`, `docker-server-cert.pem`, `docker-server-key.pem`, `zot-ca-cert.pem`, `zot-worker-cert.pem`, `zot-worker-key.pem`). | `./docker-certs` |
| `multihost_docker_registry` | zot registry address (`host:port`). Also the `/etc/docker/certs.d/<dir>` name and must match `CMGR_REGISTRY` on the orchestrator. The default is a **placeholder** the role asserts against, so this must always be set. | `REPLACE_ME:5000` |

### cork-telemetry settings

| Name | Description | Default |
| --- | --- | --- |
| `cork_telemetry_enabled` | Whether to install and run the cork-telemetry health agent. | `yes` |
| `cork_telemetry_version` | The version of `cork-telemetry` to install. | `latest` |
| `cork_telemetry_upgrade` | Whether to upgrade `cork-telemetry` if already installed. The agent has no version flag, so the role cannot detect drift on its own — pinning a different `cork_telemetry_version` only takes effect with this set. | `no` |
| `cork_telemetry_github_url` | GitHub repo to download `cork-telemetry` from. | `https://github.com/CyLabAcademy/cork-telemetry` |

### OCI runtime wrapper

`dockerd` is configured with `oci-interceptor` as its `default-runtime`, but it points at
a wrapper script this role deploys (`/usr/local/bin/oci-interceptor-runtime`, from
`templates/oci_interceptor_runtime.sh.j2`) rather than at the binary,
and `daemon.json` carries **no** `runtimeArgs`. This is deliberate and load-bearing.

Docker generates its own wrapper for any runtime with a non-empty `runtimeArgs`, and that
generated wrapper does not `exec`:

```sh
#!/bin/sh
/usr/local/bin/oci-interceptor --flags $@
```

It therefore stays in the process tree between the containerd shim and the real runtime.
containerd invokes the runtime through go-runc, which builds commands with Go's
`exec.CommandContext`; a cancelled or timed-out call delivers SIGKILL to the direct child
only — that shell — orphaning `runc` beneath it. For a `runc delete` the task is then
never deleted and its `containerd-shim-runc-v2` never shuts down, leaking roughly 5 MiB
per occurrence until the host is rebooted. On a small worker that accumulates into
host-wide OOM kills.

Our wrapper `exec`s, which removes Docker's generated layer. Note that this is only half
the fix: the interceptor itself spawning rather than exec'ing `runc` is a second,
independent non-exec layer, so the chain from shim to `runc` is a single process **only
once oci-interceptor >= `oci_interceptor_min_version` is installed**. Below that the role
warns on every apply, and shims keep leaking. Set the
interceptor's flags via `oci_interceptor_flags` as usual — they are rendered into the
wrapper (shell-quoted) rather than into `daemon.json`.

**Do not move the flags back into `daemon.json` `runtimeArgs`.** The regression is silent:
containers keep working and the leak only surfaces as memory pressure days later. An
absent or empty `runtimeArgs` produces no generated wrapper; a non-empty one does.

Note that changing either file restarts `dockerd`, which stops running containers
(`live-restore` is not enabled). Drain a worker before applying.

### Firewall settings

| Name | Description | Default |
| --- | --- | --- |
| `container_deny_ipv4_cidrs` | Traffic to these IPv4 CIDRs from inside any container is rejected. | `["169.254.169.254/32"]` |
| `container_deny_ipv6_cidrs` | The same for IPv6. Only honoured on the nftables backend; the role fails if it is non-empty on the iptables one, which has no `ip6tables` `DOCKER-USER` chain. | `[]` |
| `docker_firewall_backend` | Which firewall dockerd programs: `nftables` or `iptables`. | `nftables` |

ufw is enabled with a **default-allow** policy; the role adds no port restrictions of its own.

#### Choosing a firewall backend

`nftables` measured roughly **7x the launch throughput** of `iptables` on this fleet's workload —
dockerd's per-container rule batches serialise on the iptables lock — so it is the default. It is
not a drop-in swap, though. Set `docker_firewall_backend: iptables` to fall back, and note:

* **It needs Docker >= 29.6.0** (`docker_nftables_min_version`), which is what
  `docker_version_pin_map` pins. The backend arrived in 29.0.0, but
  29.0–29.5 link `libnftables` and abort the daemon once a netlink socket gets a file descriptor
  over 1024 ([moby#52873](https://github.com/moby/moby/issues/52873)), which containers on
  user-defined networks reach in normal use; 29.6.0 execs the `nft` binary instead
  ([moby#52886](https://github.com/moby/moby/pull/52886)). **28.x accepts the setting and silently
  goes on programming iptables**, so the role asserts the installed version rather than trusting the
  configuration. `docker_version_pin_map` pins 29.6.0.
* **Docker does not enable `net.ipv4.ip_forward` in this mode.** The role sets it; on the iptables
  backend Docker sets it itself.
* **There is no `DOCKER-USER` chain.** Docker 29 in nftables mode creates `table ip docker-bridges`
  and `table ip6 docker-bridges` and nothing else, so `container_deny_*` cannot be inserted the way
  it is on the iptables backend. On this backend the role owns
  `/etc/nftables.d/container-egress.nft` — a `table inet container_egress` hooked into `forward` at
  priority -300, well before anything Docker registers — loaded by
  `container-egress-filter.service`. It needs no ordering against `docker.service` and survives
  Docker restarts and network creation untouched.

  Switching backends moves those rules for you, in both directions: the nftables branch also strips
  the `DOCKER-USER` lines out of `/etc/ufw/after.rules`, because on this backend
  `iptables-restore` cannot find that chain and **every subsequent `ufw reload` fails**, taking
  whatever else ufw is carrying with it.
* **Flip it on a fresh instance, not a live one.** Docker programs the backend it is configured for
  and does not tidy up after the one it was using before, so a host converted in place keeps its old
  `DOCKER`/`DOCKER-ISOLATION` iptables chains, still matching, while the new nftables rules are
  added alongside. The role does not flush them: guessing which iptables rules belong to Docker on a
  host that also runs ufw is not something to automate. Reboot the instance after the switch, or
  roll the fleet — on an autoscaled fleet, replacement is the normal path anyway.

Verify a worker took the backend with `docker info | grep -i firewall` (expect
`Firewall Backend: nftables`), that its egress denials are loaded with
`nft list table inet container_egress`, and that `iptables -S DOCKER-USER` reports no such chain.

The dockerd (2376) and telemetry (2136) ports are exposed on all interfaces — restrict reachability
with security groups. dockerd requires mTLS, but the telemetry endpoint is unauthenticated
plain HTTP.

### Storage quota settings

| Name | Description | Default |
| --- | --- | --- |
| `storage_quotas` | Whether to enable storage quotas by storing daemon state on an XFS filesystem. | `true` |
| `storage_device` | The block device to format and mount as XFS. | `/dev/nvme1n1` |

### Docker network settings

| Name | Description | Default |
| --- | --- | --- |
| `network_ip_pools` | Available IP ranges for Docker network creation. | `["192.168.0.0/16"]` |
| `network_prefix_length` | Prefix bits for new Docker networks; determines containers-per-network (2^(32-*n*)-3) and the total network count. The default, `29`, allows 5 containers per network. This value must be lowered to host challenges with more than 5 running containers per instance. | `29` |

### User namespace settings

| Name | Description | Default |
| --- | --- | --- |
| `userns_remap_enabled` | Whether to enable user namespace remapping. | `true` |

### OCI runtime settings

| Name | Description | Default |
| --- | --- | --- |
| `oci_interceptor_enabled` | Whether to use the `oci-interceptor` runtime wrapper. | `true` |
| `oci_interceptor_version` | Version of `oci-interceptor` to install. | `latest` |
| `oci_interceptor_upgrade` | Whether to upgrade `oci-interceptor` if already installed. | `false` |
| `oci_interceptor_flags` | Flags to pass to `oci-interceptor`. Must be a **list**; they are rendered shell-quoted into the runtime wrapper rather than into `daemon.json`. | `["--oi-readonly-networking-mounts"]` |
| `oci_interceptor_min_version` | Lowest oci-interceptor version that `exec`s the runtime rather than spawning it. Below this the role warns on every apply: the runtime wrapper alone does not stop shims leaking. Not enforced, since an older binary otherwise works. | `0.3.0` |

### Logging settings

| Name | Description | Default |
| --- | --- | --- |
| `logs_max_size` | Maximum size of an individual container log file. | `10m` |
| `logs_max_files` | Maximum number of log files to retain per container. | `3` |

### docker-reaper settings

| Name | Description | Default |
| --- | --- | --- |
| `docker_reaper_enabled` | Whether to run `docker-reaper` as a scheduled systemd service. | `yes` |
| `docker_reaper_version` | The version of `docker-reaper` to run. | `latest` |
| `docker_reaper_upgrade` | Whether to upgrade `docker-reaper` if already installed. | `no` |
| `docker_reaper_command` | Container/network sweep arguments. Runs as the unit's first `ExecStart`. | `containers --filter label=cmgr.dynamic=true --min-age 60m --reap-networks` |
| `docker_reaper_images_command` | Image sweep arguments, run as a second `ExecStart` after the container sweep. Requires docker-reaper ≥ v1.2.0, which introduced the `images` subcommand. | `images --threshold 80 --target 70` |
| `docker_reaper_shims_command` | Orphaned containerd shim sweep, run as a third `ExecStart` after the image sweep. Signals processes as root, so it is worth understanding before enabling: a shim is only signalled once its container is absent from the daemon's full container list. Requires docker-reaper ≥ `docker_reaper_shims_min_version`; omitted with a warning on older binaries. Empty string disables. | `shims --min-age 5m` |
| `docker_reaper_shims_min_version` | Lowest docker-reaper version providing the `shims` subcommand. Below this the third `ExecStart` is omitted, because an unknown subcommand would fail the unit on every timer tick. | `1.3.0` |
| `docker_reaper_interval_secs` | How frequently (in seconds) to run `docker-reaper`. | `60` |
