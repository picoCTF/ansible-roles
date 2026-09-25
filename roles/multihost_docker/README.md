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

### Container resource limits

All challenge containers run inside the `limit_docker.slice` cgroup, which bounds their
combined CPU, memory and task consumption. **Requires the unified (cgroup v2) hierarchy** --
the role asserts on it, because `CPUWeight`, `MemorySwapMax`, `MemoryMin` and `MemoryLow`
are all v2-only and systemd would silently ignore them on v1. Both supported releases
(jammy, noble) are unified by default.

Three properties of the arrangement drive how it is configured:

- **The Docker control plane is not in the slice.** `dockerd`, `containerd` and one
  `containerd-shim-runc-v2` per running container live in `system.slice`. The per-container term
  (measured at 5.13 MiB each) means the host's own footprint grows with container count, so the slice is
  sized as *total RAM minus a computed host reserve* rather than as a flat percentage. A
  percentage cap grants the slice more memory than the machine can spare on small
  instances; the global OOM killer then fires before the slice reaches its own `MemoryMax`,
  and it selects by RSS, so the victim can be `dockerd` rather than a challenge.
- **A cap is not a reservation.** `CPUQuota` bounds aggregate container bandwidth but gives
  the host no scheduler priority, so `CPUWeight` and memory reserves on `system.slice` *and*
  `user.slice` are what actually keep a loaded worker reachable. Interactive ssh sessions
  live in `user.slice`, which the `system.slice` reserve does not cover.
- **`memory.min` does not reserve unused headroom.** It protects only the pages a cgroup is
  actually using; anything unused stays fully available to every other cgroup. Sizing it to
  the real working set therefore costs no capacity, and it -- not the best-effort
  `memory.low` -- is the part that survives sustained pressure.

Ceilings are computed at deploy time and recomputed at boot by
`docker_cgroup_quota.service`, which applies the same formula against the running kernel so
a resized instance stays correct without re-running Ansible. That script never exits
without applying something: runtime drop-ins do not survive a reboot, so bailing out would
leave the previous deploy's on-disk ceilings in force, which after a downsize are sized for
the larger instance.

> **Drain a worker before re-applying this role to it.** Changing any sizing variable lowers
> `MemoryMax` live via `systemctl set-property`, and writing `memory.max` below current
> usage OOM-kills running challenge containers.

| Name | Description | Default |
| --- | --- | --- |
| `container_slice_target_containers` | Container capacity this worker is sized for; drives the memory reserve. Leave `null` to derive it from RAM. A pinned value is **not** recomputed if the instance is resized. | `null` |
| `container_slice_min_mean_container_mb` | The lowest **mean** container footprint the shim reserve survives. Not a per-container limit and never a cgroup setting; it only decides how many shims to reserve host memory for. Set it below the smallest mean you expect -- see below. | `30` |
| `container_slice_os_reserve_mb` | Base OS footprint outside Docker (systemd, journald, sshd, and any fleet agents). | `256` |
| `container_slice_dockerd_reserve_mb` | `dockerd` + `containerd` themselves, excluding per-container shims. Measured at 264 MiB on a worker up 10 weeks; dockerd grows with uptime, so do not size this from a freshly booted host. | `320` |
| `container_slice_user_reserve_mb` | Interactive login sessions in `user.slice`. | `128` |
| `container_slice_host_mb_per_container` | Host-side memory each running container costs *outside* the slice (its containerd-shim plus dockerd's per-container state). Measured at 5.13 MiB. | `6` |
| `container_slice_min_mb` | Floor below which the boot script clamps and warns rather than honouring the reserve. | `256` |
| `container_slice_cpu_percent_per_core` | Per-core CPU percentage granted to the slice in aggregate. | `80` |
| `container_slice_cpu_weight` | Slice `CPUWeight`, against `system.slice` and `user.slice` at the default `100`. Lower means containers yield to `sshd` and `dockerd` under contention. | `20` |
| `container_slice_swap_max` | Slice `MemorySwapMax`. `0` prefers killing one container over thrashing the host. | `0` |
| `container_slice_tasks_max_pct` | Aggregate `TasksMax`, as a percentage of `kernel.threads-max`. Deliberately **not** derived from container count, so it is insensitive to the container mix -- see below. | `50` |
| `system_slice_memory_min_mb` | Hard floor for `system.slice`. | `256` |
| `user_slice_memory_min_mb` | Hard floor for `user.slice`, so an admin's ssh session survives a loaded worker. | `64` |

`system_slice_memory_low_mb` and `user_slice_memory_low_mb` are **derived** from the host
reserve rather than set flat, so the soft floors track instance size and container count
instead of contradicting them.

Derived sizing at the defaults:

| RAM | vCPU | Containers budgeted | Host reserve | Slice `MemoryMax` | `system.slice` `MemoryLow` | `CPUQuota` |
| --- | --- | --- | --- | --- | --- | --- |
| 2 GiB | 2 | 33 | 902 MiB | 1004 MiB | 774 MiB | 160% |
| 4 GiB | 2 | 89 | 1238 MiB | 2683 MiB | 1110 MiB | 160% |
| 8 GiB | 2 | 199 | 1898 MiB | 5970 MiB | 1770 MiB | 160% |
| 16 GiB | 4 | 422 | 3236 MiB | 12664 MiB | 3108 MiB | 320% |

`TasksMax` is 50% of the host's `kernel.threads-max` in every case.

#### What the host reserve is made of

Only one term scales. The OS footprint is flat at every instance size -- a live
worker measured 244 MiB of non-Docker `system.slice` units (anon + kernel), and nothing about a
larger instance makes Ubuntu bigger. `dockerd` + `containerd` are likewise
treated as flat (measured 264 MiB excluding shims, on a worker up 10 weeks); their growth with
container, network and endpoint count is sublinear and is absorbed by the
headroom in `container_slice_dockerd_reserve_mb` rather than modelled.

Everything else is the per-container host cost. Measured on Docker 29.8 /
containerd 2.3 by launching 20 containers and reading cgroup deltas:
`containerd.service` grew **4.36 MiB per container** (the shim) and
`docker.service` grew **0.77 MiB per container**, so **5.13 MiB total**. The `6`
default covers that with headroom for dockerd's larger per-container state when
each instance also gets its own network.

Measure with cgroup accounting, not RSS: those same 20 shims showed a mean
`VmRSS` of 10.75 MiB, because RSS counts their shared binary and libraries once
per process while the cgroup charges shared pages once.

| RAM | OS | dockerd | per-container term | `system.slice` `MemoryLow` | per-container share |
| --- | --- | --- | --- | --- | --- |
| 2 GiB | 256 | 320 | 198 MiB | 774 MiB | 26% |
| 4 GiB | 256 | 320 | 534 MiB | 1110 MiB | 48% |
| 8 GiB | 256 | 320 | 1194 MiB | 1770 MiB | 67% |
| 16 GiB | 256 | 320 | 2532 MiB | 3108 MiB | 81% |

So a 16 GiB worker's 3.0 GiB `MemoryLow` is 81% shims and 8% Ubuntu. Note that
`memory.low` protects only pages the slice is *actually* using -- an over-generous
value costs nothing on its own. The part that does cost is the reserve's effect
on `MemoryMax`, and it is sized for the maximum container count: run 50 large
challenges on a 16 GiB worker instead of 437 small ones and roughly 1.9 GiB is
reserved for shims that never exist.

#### Sizing the shim reserve on a heterogeneous challenge set

The "shims budgeted" column is the *only* thing
`container_slice_min_mean_container_mb` controls. It is not a per-container
limit, it does not cap how many containers may run, and nothing enforces it. It
decides how much host memory is set aside for shims, which live in
`system.slice` outside every container cgroup and cost ~5 MiB each regardless of
what they wrap.

Working the arithmetic through gives a clean result: **the reserve is sufficient
exactly when the fleet's actual mean container size is at or above
`container_slice_min_mean_container_mb`.** The variable is a *floor on the mean*,
not an estimate of it.

That is what makes an asymmetric challenge set tractable. A `socat` one-liner
beside a full service stack is fine -- the spread does not matter, only the mean
does, and you need a lower bound on it rather than an accurate figure.

Below the floor the shortfall grows fast. On a 4 GiB worker budgeting for a
50 MiB mean:

| Actual mean | Containers that fit | Shims they cost | Shims budgeted | Shortfall |
| --- | --- | --- | --- | --- |
| 100 MiB | 31 | 155 MiB | 305 MiB | -150 MiB (spare) |
| 50 MiB | 62 | 310 MiB | 305 MiB | ~0 |
| 25 MiB | 124 | 620 MiB | 305 MiB | **+315 MiB** |
| 10 MiB | 310 | 1550 MiB | 305 MiB | **+1245 MiB** |

The failure is asymmetric, so set the floor *below* the smallest mean you expect
rather than at the mean you observe: undershooting costs a little container
memory, overshooting costs the worker. A live picoCTF worker measured a ~48 MiB
mean, so the `30` default carries roughly 40% headroom for a shift toward
smaller challenges.

Nothing bounds instance *count*, so a mean below the floor overruns the host
reserve while the slice's own `MemoryMax` is still far from binding. Pin
`container_slice_target_containers` where the real capacity is known; a
count-aware admission signal in the orchestrator is the durable fix.

Placing the shims *inside* `limit_docker.slice` would remove the floor, the
reserve's per-container term and the over-reservation in one go. Two routes were
examined and **both are rejected**; the reserve is what remains.

containerd's own `ShimCgroup` option cannot do it: it lives under
`plugins.'io.containerd.cri.v1.runtime'`, Docker does not use the CRI plugin
(`disabled_plugins = ["cri"]`), and setting it left shims in
`/system.slice/containerd.service` unchanged (Docker 29.8 / containerd 2.3).

Nesting does work mechanically -- `containerd.service` honours `Slice=` and every
shim it spawns follows it, so a common parent over both would let the kernel
enforce the combined total and delete the capacity estimate entirely.
**Do not adopt it.** When that parent fills, the kernel kills the largest process
in the subtree, and containerd itself (57-70 MiB) is the size of a large
container -- losing it takes down every container on the worker at once, which is
a far worse failure than the overcommit this role exists to prevent.
`OOMScoreAdjust=-1000` on `containerd.service` would in principle make it and its
shims ineligible, since `oom_score_adj` is inherited, but that trades a bounded
and predictable over-reservation for an unverified guard against a total-worker
outage. The reserve costs memory; this costs the worker.

#### What is deliberately not set

- **No `MemoryHigh`.** `memory.high` throttles *every* task in the cgroup, not the one that
  overran, and with `MemorySwapMax=0` and anon-heavy challenge workloads reclaim has
  nothing to free, so the penalty saturates and every container on the worker stalls in
  allocation. Reaching `MemoryMax` reclaims and then OOM-kills inside the slice, which is
  the intended outcome: lose one challenge, not the worker.

  Measured on a 300 MiB test slice with an unbounded allocator ("hog") and a steady
  small-allocation workload ("victim") sharing it:

  | | `MemoryHigh=250M` + `MemoryMax=300M` | `MemoryMax=300M` only |
  | --- | --- | --- |
  | `memory.events` `high` (throttles) | **49049** | 0 |
  | `memory.events` `oom_kill` | **0** | 2 |
  | hog | survived untouched | killed (`Result=oom-kill`) |
  | victim | **never finished** | completed, 0.7 ms worst stall |

  With `MemoryHigh` the offender was never killed and the innocent workload was throttled
  to death. Without it the offender dies and its neighbour is unaffected.
- **No `IOWeight`.** cgroup v2 `io.weight` is honoured only by BFQ or a configured
  blk-iocost, and Ubuntu cloud images default to `none`/`mq-deadline`, so setting it would
  look like protection while doing nothing. `IOAccounting` is kept because it populates
  `io.stat` and the IO columns of `systemd-cgtop` regardless of scheduler, which is how a
  disk-saturation stall gets diagnosed. Absolute throttling
  (`IOReadBandwidthMax`/`IOWriteBandwidthMax`) works on any scheduler but needs per-device,
  per-instance-type tuning.

#### Measured behaviour

Applied to a clean Ubuntu 24.04 VM (16 GiB, 12 vCPU, Docker 29.8, containerd 2.3,
cgroup v2) and verified against the kernel, not just systemd:

- Every ceiling landed exactly as computed -- `cpu.max` `960000 100000`,
  `memory.max` 12841 MiB, `memory.swap.max` 0, `pids.max` 56506, `cpu.weight` 20,
  plus `memory.min`/`memory.low` on both `system.slice` and `user.slice`.
- Containers land in `/limit_docker.slice/docker-<id>.scope` while their shims
  stay in `/system.slice/containerd.service` -- the premise the whole host
  reserve rests on.
- A runaway container was OOM-killed inside the slice (`memory.events`
  `oom_kill 1`, container `OOMKilled=true`, exit 137) while a neighbouring
  container in the same slice kept running with all-zero `memory.events` of its
  own, and the host stayed at load 0.13 with 15 GiB available.

The last point is the behaviour the whole design is for: lose one challenge, not
the worker.

#### Why `TasksMax` is not sized the same way

`TasksMax` is a fraction of `kernel.threads-max`, deliberately *not* derived from
container count times a per-container average. It expresses the only invariant
that matters to the host: no combination of containers may exhaust thread
capacity -- a property of the kernel, not of the container mix. A count-derived
ceiling breaks in both directions on a heterogeneous set: a stack-heavy mix trips
it and *legitimate* challenges fail to fork, while a socat-heavy mix leaves it
uselessly loose. Bounding an individual challenge is the `pidslimit` container
option's job.

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
* **Docker does not enable `net.ipv4.ip_forward` in this mode**, and the failure is not a
  degraded one: dockerd exits 1 while creating the default bridge ("IPv4 forwarding is
  disabled") and the service never comes up. The role sets the sysctl; on the iptables backend
  Docker sets it itself.
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


#### Rolling this onto an existing worker

The version guard above fails on a worker already running Docker below
`docker_nftables_min_version`, which is the fleet's current state (28.5.2). That is
deliberate -- the alternative is configuring an nftables backend the daemon will
silently ignore while ufw's forward policy drops all container egress -- but it does
mean the role will not apply to an existing worker unchanged.

With the defaults (`docker_pin_version: false`, `upgrade: no`) the unpinned install is
`state: present` against an already-installed package, so an existing host never moves
off the version it has and the guard then fails. New hosts are unaffected: they take
the repository's current version, which satisfies the minimum. Three ways forward:

* **`docker_pin_version: true`** installs the pinned version (with `allow_downgrade`)
  before the guard runs, so one play upgrades the daemon and then passes. This is the
  intended path, and it is what pins the fleet to a known Docker rather than to
  whatever the repository happened to offer on provisioning day.
* **`upgrade: yes`** takes whatever the repository currently offers.
* **`docker_firewall_backend: iptables`** skips the guard entirely and leaves the host
  on the iptables backend, with `container_deny_*` enforced through ufw's `after.rules`
  as before. Use this to decouple the cgroup work from the Docker upgrade.

Upgrading Docker restarts the daemon, which stops running containers (`live-restore`
is not enabled), so this belongs in the same drain window as applying the role.
### Storage quota settings

| Name | Description | Default |
| --- | --- | --- |
| `storage_quotas` | Whether to enable storage quotas by storing daemon state on an XFS filesystem. | `true` |
| `storage_device` | The block device to format as XFS. fstab mounts by `storage_label` rather than by this, but it is still required on every run: it formats a new volume, it is what the label is read from to decide whether a relabel is needed, and it is what the grow task resizes. **A stale or renumbered value is not detected** — if it names a different disk than the one mounted at `storage_mount_point`, the label can be written to the wrong volume. See [Baking a worker image](#baking-a-worker-image) for the two commands that check it. | `/dev/nvme1n1` |
| `storage_mount_options` | fstab options for the volume — a whole-value override, not a list to append to, and nothing validates it. Keep all three: `pquota` is the point of the volume, `nofail` keeps an unresolvable label from failing `local-fs.target` and taking the boot with it, and the device timeout bounds the wait before it gives up. Dropping `pquota` is silent; dropping `nofail` surfaces only at the next reboot. | `pquota,nofail,x-systemd.device-timeout=30s` |
| `storage_label` | Filesystem label of that volume, and what fstab mounts. A label is part of the filesystem, so it survives a snapshot where a device path does not — see [Baking a worker image](#baking-a-worker-image). | `docker-data` |

`docker.service` gets a `RequiresMountsFor` drop-in for the mount. Without it, a
volume that fails to mount leaves dockerd running on a directory of the same
name on the root volume — a fraction of the space, no project quotas, and no
error anywhere. The dependency turns that into a clean refusal to start.

The fstab entry carries `nofail`, which is what keeps that refusal proportionate:
without it an unresolvable label fails `local-fs.target` and the instance boots
into emergency mode instead, where sshd never starts and there is no way in to
find out why.

Turning `storage_quotas` off on a host that had it on is a one-way door in one
direction only: the drop-in and `data-root` are removed and dockerd goes back to
`/var/lib/docker`, but the fstab entry and the mount are left alone — the role
skips its storage tasks entirely when quotas are off, so it never sees them. The
volume stays mounted and populated while nothing uses it. Unmount and remove the
fstab line by hand if you actually want it gone.

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
| `docker_reaper_version` | The version of `docker-reaper` to run. It must be at least the role's floor, `docker_reaper_min_version` in `vars/main.yml` (1.4.0, the oldest release with every flag the unit passes): an older installed binary is replaced whatever `docker_reaper_upgrade` says, and if the version that would be installed is older still, the play fails before it changes anything on the host. | `latest` |
| `docker_reaper_upgrade` | Whether to upgrade `docker-reaper` if already installed. | `no` |
| `docker_reaper_command` | Container/network sweep arguments. Runs as the unit's first `ExecStart`. Must not outlive `cmgr_prune_age` in the `cork` role, or cmgrd keeps serving instances whose containers are already gone. | `containers --filter label=cmgr.dynamic=true --min-age 30m --reap-networks` |
| `docker_reaper_images_command` | Image sweep arguments, run as a second `ExecStart` after the container sweep. `--disk-path` names the data volume (`/var/lib/docker` with `storage_quotas` off) so the reaper does not ask dockerd for it with a `/info` call every run. `--min-size` puts images that would free less behind every larger candidate: removing an image stalls every container create and image pull on the worker until its files are deleted, so each removal should free something worth that. | `images --threshold 89 --target 84 --min-size 100MiB --disk-path /mnt/docker-data` |
| `docker_reaper_shims_command` | Orphaned containerd shim sweep, run as a third `ExecStart` after the image sweep. Signals processes as root, so it is worth understanding before enabling: a shim is only signalled once its container is absent from the daemon's full container list. The role adds `--data-root`, so the sweep asks dockerd for its container list only when a shim's container has no directory on disk. Empty string disables. | `shims --min-age 5m` |
| `docker_reaper_images_lru` | Evict cached images least recently used first rather than largest first. The container sweep gets `--record-image-use` and the image sweep `--lru`, sharing a record in the unit's `StateDirectory` (`/var/lib/docker-reaper`). The record costs no extra daemon call; see docker-reaper's README. The role appends these flags, and `--data-root` to the shim sweep; an override that already carries one is fine, as a repeated flag keeps its last value. | `yes` |
| `docker_reaper_interval_secs` | How frequently (in seconds) to run `docker-reaper`. | `60` |

## Baking a worker image

An autoscaled worker cannot be provisioned by this role: it has to boot ready,
which means an image taken from a host this role has already finished with. The
fleet's dockerd certificates are issued for one shared name
(`SAN DNS:academy-docker-worker`) precisely so that workers can be cloned
without reprovisioning, and nothing else in this role writes a per-host
identity.

Two things do carry identity, and both must be dealt with before imaging.

**The data volume.** `CreateImage` snapshots every attached volume, so an image
taken from a provisioned worker already carries a formatted, labelled, `pquota`
XFS volume — with the challenge image cache warm, which is worth having. What
does *not* survive is the device path: AWS builds
`/dev/disk/by-id/nvme-Amazon_Elastic_Block_Store_vol<id>` from the volume ID,
and a snapshot restore produces a new volume with a new ID. That is why fstab
names `LABEL=`. A worker provisioned before this role wrote labels is
relabelled in place on the next run; nothing is reformatted and no data moves.

This role is applied to the **base** worker, never to a clone. A clone is an AMI
launch, and changing one means updating the base and re-imaging rather than
running Ansible against a running replica — which is why `storage_device` may
still name a volume-ID path even though nothing mounts by it: the base keeps its
volume, and only the image copies move.

**Docker's own state.** The volume being snapshotted *is* dockerd's data-root, so
it carries more than the image cache: containers and their logs, libnetwork's
IPAM database, and the daemon's `engine-id`. A clone taken from a live fleet
member boots restoring another worker's containers and networks — cork tears down
instances it has no record of, so every clone pays that inside its ready window,
and anything not labelled `cmgr.dynamic=true` is outside the reaper's filter and
stays for good. Quiesce first, which also means the snapshot is taken of a
filesystem nothing is writing to:

```sh
ROOT=$(docker info --format '{{.DockerRootDir}}')   # NOT storage_mount_point, see below
: "${ROOT:?docker info failed - do this before stopping the daemon}"
docker ps -aq | xargs -r docker rm -fv              # -v, or their anonymous volumes stay
docker volume prune -af                             # -a, or named volumes stay
docker network prune -f
sudo systemctl stop docker docker.socket
sudo rm -f "$ROOT/engine-id"                        # else every clone reports one daemon ID
sudo rm -f "$ROOT/network/files/local-kv.db"        # libnetwork's IPAM allocations
```

Take the root from `docker info` rather than assuming `/mnt/docker-data`: with
`userns_remap_enabled` on — the default for a worker — dockerd appends the
remapped `<uid>.<gid>` to it, so the files live a directory deeper. `rm -f` on a
path that does not exist exits 0 silently, so guessing wrong here looks exactly
like success.

`docker rm` leaves anonymous volumes behind without `-v`, and `docker network
prune` only removes unused *networks* — the IPAM database and the daemon ID are
files, and both have to go after the daemon stops or it rewrites them on the way
out. Docker regenerates each on next start.

**Everything the OS assigns per host.** Scrub before imaging:

```sh
sudo rm -f /etc/ssh/ssh_host_*          # else every clone shares one host key
sudo truncate -s 0 /etc/machine-id      # truncate, do not delete
sudo hostnamectl set-hostname localhost # the os role set this one
sudo cloud-init clean --logs            # required, and must come last
```

`cloud-init clean` is not optional and the order matters. It is what removes
`data/previous-hostname` and `data/set-hostname` under the cloud dir, which is
what makes `cc_set_hostname` treat the clone as changed and name it from the
datasource on first boot. Skip it, or run it before the `hostnamectl` line, and
every clone comes up called `localhost` — a state the validation below is written
to catch, because "differs from the source" would not.

**What the image carries.** The TLS material under `tls_cert_path` and
`/etc/docker/certs.d/` is deliberately *not* scrubbed — provisioning it on first
boot is the work an image exists to skip. An image therefore carries private key
material, and should be handled accordingly: keep it and its snapshots private,
and treat re-issuing the certificates as a re-bake of the base rather than
something that can be done on a running replica.

Then validate one instance launched from the image, outside any scaling group:

```sh
# the fstab line must name the label AND carry nofail; nothing else can check
# nofail, because libmount never passes it to the kernel
grep -E '^LABEL=docker-data\s+/mnt/docker-data\s+xfs\s+\S*\bnofail\b' /etc/fstab

findmnt -no SOURCE,FSTYPE,OPTIONS /mnt/docker-data   # device, xfs, prjquota
sudo blkid -c /dev/null -o device -t LABEL=docker-data  # exactly one device, and
findmnt -no SOURCE /mnt/docker-data                     # it must be this one
# -p prints an empty value and exits 0 for a unit that does not exist or failed
# to load, so grep for the path rather than reading the output
systemctl show docker.service -p RequiresMountsFor | grep -q /mnt/docker-data
docker info --format '{{.DockerRootDir}}'            # under /mnt/docker-data
docker images                                        # cache came over in the snapshot

# a machine-id that is 32 hex characters, not merely different from the source
[ "$(cat /etc/machine-id | tr -d -c '[:xdigit:]' | wc -c)" = 32 ] && echo ok
hostname                                             # not localhost, not the source's

curl -s localhost:2136/health                        # {"overloaded":false}
```

Several of those replace checks that could not fail, and the reasons are worth
knowing because the same traps recur:

- `findmnt` prints the resolved device and never `LABEL=`, so only the fstab
  line shows how the volume got mounted. And `nofail` is a libmount userspace
  option that never reaches the kernel, so it can never appear in `findmnt`
  output — the anchored `grep` is the only thing that can catch its loss.
- `docker info | grep 'Docker Root Dir'` on its own proves nothing: it prints the
  *configured* path whether or not anything is mounted there, which is the silent
  failure the drop-in exists to catch. It is worth running only next to the
  `findmnt` line above, which says whether anything is actually mounted.
- A `hostname`/`machine-id` "differs from the source" check cannot fail once the
  scrub has emptied both on the source. Test the shape instead: a valid
  machine-id is 32 hex characters, and a clone still named `localhost` is the
  broken case even though it does differ.
- `curl` answering `{"overloaded":false}` says the telemetry agent is up, not
  that Docker is: it reads only `/proc` and will answer happily on a worker whose
  dockerd refused to start.

Finally, from the orchestrator, the check that proves the premise:

```sh
sudo sed -i '/academy-docker-worker/d' /etc/hosts      # drop any earlier bake's entry
echo '<new-worker-ip> academy-docker-worker' | sudo tee -a /etc/hosts
sudo env DOCKER_CERT_PATH=/root/.docker_certs \
  docker -H tcp://academy-docker-worker:2376 --tlsverify info
sudo sed -i '/academy-docker-worker/d' /etc/hosts
```

Delete the entry before *and* after, and note that a leftover one is worse than
it looks: Ubuntu's `/etc/host.conf` sets `multi on`, and the Docker CLI is a Go
binary that collects *every* matching line and dials them with fallback. So a
stale entry from an earlier bake does not merely shadow the new worker — this
check can pass by falling through to the old one even when the new worker's
dockerd is completely dead. That is the single failure mode the check exists to
rule out, so leaving the entry behind inverts it.

`DOCKER_CERT_PATH` is needed because a bare `--tlsverify` reads `~/.docker`,
which is empty for the login user; the orchestrator's client material is staged
under `/root/.docker_certs`.

By name, not by IP: the certificate is issued for the name, and the Docker CLI
has no flag to verify against a different one, so dialling the address fails on
the certificate however healthy the worker is. If it validates against a host
that was never individually provisioned, the image is clonable.
