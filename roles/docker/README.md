# docker

## Description

Installs [Docker Engine](https://docs.docker.com/engine/) on a host and configures various settings
in order to provide an optimal experience for challenge servers and
[webshell](https://github.com/picoCTF/webshell) toolbox hosts.

The Docker configuration changes made by default include:

### TLS Docker socket access

The Docker daemon socket is [exposed over
TLS](https://docs.docker.com/engine/security/protect-access/#use-tls-https-to-protect-the-docker-daemon-socket)
on port 2376. This is useful for challenge backends like
[Hacksport](https://github.com/picoCTF/hacksport), which require external access to the Docker
daemon. It is also useful for running webshell toolbox containers on a separate host from the
launcher, as recommended.

The variable `tls_sans` must be specified as a list of all [Subject Alternative
Names](https://en.wikipedia.org/wiki/Subject_Alternative_Name) from which the socket should be
accessible. By default, the generated TLS client certificates are fetched to the host running
Ansible. See [below](#tls-docker-socket-access-settings) for a full list of configurable options.

### Storage quotas

The Docker daemon state is stored on a separate device, which is formatted with the
[XFS](https://en.wikipedia.org/wiki/XFS) filesystem. By mounting this filesystem with the [`pquota`
mount
option](https://access.redhat.com/documentation/en-us/red_hat_enterprise_linux/7/html/storage_administration_guide/xfsquota)
and using the [overlay2 storage
driver](https://docs.docker.com/engine/reference/commandline/dockerd/#daemon-storage-driver), we can
enforce size limits for [Docker volumes](https://github.com/moby/moby/pull/41330) (useful for
webshell home directories) and the [writable layers of
containers](https://github.com/moby/moby/pull/24771) (useful for preventing abusive disk usage in
both challenge and webshell containers).

The variable `storage_device` must be specified as the path of the block device to be formatted as
XFS and used to store the Docker state. This behavior can be disabled, in which case Docker graph
storage will be stored in `/var/lib/docker` as usual, and storage quotas will not be available.
However, this is **highly discouraged** in any situation where untrusted users may obtain access to
the filesystem, as a malicious user will easily be able to fill the disk and render the machine
inoperable.

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

### Increased number of available Docker networks

[By default](https://github.com/docker/docker.github.io/issues/8663), Docker networks are created
with fairly large subnet sizes (/16 for the first 16, then /20) which allow thousands of containers
to be connected. However, this limits the total number of simultaneous Docker networks to 32.

When running challenge instances or webshell toolbox containers, we want each instance to be on its
own isolated network. Only having 32 total networks would be extremely limiting, but fortunately it
is possible to reduce the subnet size of newly created Docker networks. In this role, we set this
size to /29 by default, which allows for thousands of Docker networks with up to 5 containers each.

If you are planning to host any challenges which require more than 5 containers, this subnet prefix
size must be lowered. See [below](#docker-network-settings) for more details.

### User namespace remapping

While appropriate security options should always be specified when running containers to limit the
possibility of container escapes, there is always the potential that a malicious user inside a
container will gain access to the host.

Typically, is especially problematic when the user is already root (UID 0) inside the container (the default for most images), as UIDs are shared between containers and the host.

To minimize the potential impact of a container escape, by default this role enables [user namespace
remapping](https://docs.docker.com/engine/security/userns-remap/). This means that UID 0 inside
running containers is mapped to an arbitrary UID with no privileges on the host. If a user manages
to escape from a container in which they were root, they will find themselves to be a random
unprivileged user on the host.

There are a few [limitations](https://docs.docker.com/engine/security/userns-remap/#user-namespace-known-limitations) when user namespace remapping is enabled, including:

- Containers cannot share the host PID or network namespaces
- Files inside host-mounted volumes will have incorrect ownership unless manually changed

These should not be relevant to challenge or webshell toolbox containers.

While not recommended, this functionality can be [disabled](#user-namespace-settings) if necessary.
Note that any existing image layers and Docker volumes will become inaccessible when user namespace
remapping is toggled on or off.

### OCI runtime

By default, the [OCI interceptor](https://github.com/picoCTF/oci-interceptor) runtime wrapper is
used along with runc. This can be used to work around limitations in Docker's native
resource-limiting capabilities.

### Log driver

As
[recommended](https://docs.docker.com/config/containers/logging/configure/#supported-logging-drivers)
in the Docker documentation, the daemon is configured to use the `local` log driver. Unlike the
default `json-file` driver, this driver places a cap on the maximum size of log files stored per
container.

This is important for interactive containers, as otherwise malicious users can easily exhaust the
Docker graph storage volume by generating excessive logs.

We've chosen to retain a fixed amount of logs per container rather than disabling logging entirely,
as it is often useful to examine the logs of challenge containers in order to diagnose problems. The
amount of log output retained (30m across 3 files) is somewhat reduced from the `local` driver's
[defaults](https://docs.docker.com/config/containers/logging/local/#options) but should still be
sufficient for the majority of use cases. The amount of output retained is customizable using the
variables [listed below](#logging-settings).

### Firewall rules

Access to the [EC2 metadata endpoint](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-instance-metadata.html) is blocked from all Docker containers by default.

This is [configurable](#firewall-settings), and additional IPs can be blocked if desired.

## Docker resource reaper

[docker-reaper](https://github.com/picoCTF/oci-interceptor) is integrated as a systemd service. By default, it will run every minute, removing any on-demand cmgr containers and networks which are more than an hour old. This can be disabled or customized via [role variables](#docker-reaper-settings).

## Role Variables

### General settings

| Name | Description | Default |
| --- | --- | --- |
| `docker_group_users` | Adds these users to the `docker` group, granting them access to the daemon without `sudo`. | `[]` |
| `upgrade` | Whether to upgrade Docker packages if already installed | `false` |

### TLS Docker socket access settings

| Name | Description | Default |
| --- | --- | --- |
| `tls_access` | Whether the Docker daemon should be externally accessible over TLS | `true` |
| `tls_expiration_days` | Validity period (in days) for generated TLS certs | `3650` |
| `tls_sans` | Subject Alternative Names to include in the generated server certificate.<br><br>Note: this can be modified without affecting the CA or client certificate, as long as they are still valid. | `["DNS:localhost", "IP:127.0.0.1", "DNS:host.docker.internal"]` |
| `tls_renew_certs` | Whether to generate new CA and client certs if they have expired | `false` |
| `tls_fetch_certs` | Whether to fetch generated client certs to the host running Ansible | `true` |
| `tls_fetched_cert_path` | Where fetched client certs will be stored on the host running Ansible | `./fetched/certs/` |

### Storage quota settings

| Name | Description | Default |
| --- | --- | --- |
| `storage_quotas` | Whether to enable storage quotas by storing the Docker daemon state in an XFS filesystem. <br><br>Note that when using container storage quotas, `oci_interceptor_flags` should probably include `--oi-readonly-networking-mounts` (and is included by default). Otherwise, it is still possible to exhaust the host graph storage by writing to `/etc/hosts`, `/etc/hostname`, or `/etc/resolv.conf` inside a container. | `true` |
| `storage_device` | The block device to format and mount as an XFS filesystem. | `/dev/nvme1n1` |

### Docker network settings

| Name | Description | Default |
| --- | --- | --- |
| `network_ip_pools` | Available IP ranges for Docker network creation. Determines the total number of available networks, along with `network_prefix_length`. | `["192.168.0.0/16"]` |
| `network_prefix_length` | Number of prefix bits to use when creating Docker networks. This determines the number of containers (2^(32-*n*)-3) that can join the network and impacts the total number of available networks.<br><br>The default, `29`, allows 5 containers per network and should be appropriate for most challenge servers. However, this value must be lowered to host challenges with more than 5 running containers per network. | `29` |

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
| `oci_interceptor_flags` | Flags to pass to `oci-interceptor`. Must be a **list**; they are rendered shell-quoted into an exec'ing wrapper script (`/usr/local/bin/oci-interceptor-runtime`) rather than into `daemon.json` `runtimeArgs`. Docker generates its own non-exec wrapper for any runtime with a non-empty `runtimeArgs`, which then sits between the containerd shim and the runtime and leaks a containerd shim whenever a runtime call is cancelled. | `["--oi-readonly-networking-mounts"]` |

### Logging settings

| Name | Description | Default |
| --- | --- | --- |
| `logs_max_size` | Maximum size of an individual container log file. | `10m` |
| `logs_max_files` | Maximum number of log files to retain per container. If rolling the logs creates excess files, the oldest are deleted. | `3` |

### Firewall settings

| Name | Description | Default |
| --- | --- | --- |
| `container_deny_ipv4_cidrs` | Traffic to these IPv4 CIDRs from inside any container is rejected. | `["169.254.169.254/32"]` |
| `container_deny_ipv6_cidrs` | The same for IPv6. Only honoured on the nftables backend; the role fails if it is non-empty on the iptables one, which has no `ip6tables` `DOCKER-USER` chain. | `[]` |
| `docker_firewall_backend` | Which firewall dockerd programs: `nftables` or `iptables`. Defaults to `iptables` here, unlike `multihost_docker` -- see below. | `iptables` |

ufw is enabled with a **default-allow** policy; the role adds no port restrictions of its own.

#### Choosing a firewall backend

`iptables` is the default for this role, deliberately. `nftables` measured roughly **7x the
launch throughput** on the challenge worker fleet — dockerd's per-container rule batches
serialise on the iptables lock — which is why `multihost_docker` defaults to it. That gain is
specific to hosts launching containers in bulk; this role also serves webshell toolbox hosts,
and switching backends forces a Docker 29 upgrade that `docker_version_pin_map` deliberately
holds back from. Set `docker_firewall_backend: nftables` to opt in, and note:

* **It needs Docker >= 29.6.0** (`docker_nftables_min_version`), above what
  `docker_version_pin_map` pins for this role (28.5.2). The backend arrived in 29.0.0, but
  29.0–29.5 link `libnftables` and abort the daemon once a netlink socket gets a file descriptor
  over 1024 ([moby#52873](https://github.com/moby/moby/issues/52873)), which containers on
  user-defined networks reach in normal use; 29.6.0 execs the `nft` binary instead
  ([moby#52886](https://github.com/moby/moby/pull/52886)). **28.x accepts the setting and silently
  goes on programming iptables**, so the role asserts the installed version rather than trusting the
  configuration. Opting in therefore means raising the pin too.
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

#### Rolling this onto an existing host

With this role's defaults nothing here forces a Docker upgrade: `docker_firewall_backend`
is `iptables`, so the version guard is skipped and an existing 28.5.2 host applies cleanly.

If you opt into `nftables`, the guard fails on any host already running Docker below
`docker_nftables_min_version` -- deliberately, since the alternative is configuring a
backend the daemon silently ignores while ufw's forward policy drops all container egress.
With `docker_pin_version: false` and `upgrade: no` the unpinned install is `state: present`
against an already-installed package, so an existing host never moves off the version it
has and the guard then fails. Two ways forward:

* **Raise `docker_version_pin_map` to 29.6.0 and set `docker_pin_version: true`**, which
  installs the newer daemon (with `allow_downgrade`) before the guard runs, so one play
  upgrades and then passes. Read the note on that variable first -- the sub-29 hold is
  deliberate and its original reason was not recorded.
* **`upgrade: yes`** takes whatever the repository currently offers.

Upgrading Docker restarts the daemon, which stops running containers (`live-restore` is not
enabled), so this belongs in the same drain window as applying the role.
#### docker-reaper settings

| Name | Description | Default |
| --- | --- | --- |
| `docker_reaper_enabled` | Whether to run `docker-reaper` as a scheduled systemd service. | `yes` |
| `docker_reaper_version` | The version of `docker-reaper` to run. | `latest` |
| `docker_reaper_upgrade` | Whether to upgrade `docker-reaper` if already installed. | `no` |
| `docker_reaper_command` | Command-line arguments to pass to `docker-reaper`. | `containers --filter label=cmgr.dynamic=true --min-age 60m --reap-networks` |
| `docker_reaper_interval_secs` | How frequently (in seconds) to run the specified `docker-reaper` command. | `60` |
