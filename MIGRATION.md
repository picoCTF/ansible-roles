# Migration notes

These roles are not versioned, so this file carries what a changelog would not: changes
that need an operator to **do something** — drain a host, upgrade a package, set a
variable — rather than just re-run the role. Re-running a role and getting the new
behaviour for free does not belong here.

One section per feature, newest first. Each says what changed, who it affects, and what
you have to do.

---

## Aggregate container cgroup ceilings

**Affects** `multihost_docker`, `docker` · **Action required: drain the host first**

`limit_docker.slice` is now sized as *total RAM minus a measured host reserve* instead of
a flat percentage of RAM. The Docker control plane lives in `system.slice`, outside the
slice, and grows with container count, so a percentage cap could grant the slice more
memory than the machine could spare — on a 2 GiB worker it overcommitted by ~400 MiB and
the global OOM killer fired before the slice reached its own limit, sometimes taking
`dockerd`.

**Drain before applying.** Re-running the role lowers `MemoryMax` live via
`systemctl set-property`, and writing `memory.max` below current usage OOM-kills running
containers.

The container ceiling drops, by a lot on small hosts and barely at all on large ones:

| RAM | old `MemoryMax` (80%) | new | change |
| --- | --- | --- | --- |
| 4 GiB | 3083 MiB | 2627 MiB | −456 MiB |
| 8 GiB | 6349 MiB | 6032 MiB | −317 MiB |
| 16 GiB | 12788 MiB | 12737 MiB | −51 MiB |

Also landing with it, none needing operator action: `CPUWeight=20` so the host keeps
scheduler priority, `MemoryMin`/`MemoryLow` reserves on `system.slice` and `user.slice`,
`TasksMax` from `kernel.threads-max`, `MemorySwapMax=0`, and a boot unit that recomputes
every ceiling against the running kernel so a resized instance stays correct without a
re-run. `MemoryHigh` and `IOWeight` were removed deliberately — see the role READMEs.

If a worker is sized for far fewer containers than its RAM implies, pin
`container_slice_target_containers` rather than letting it derive from RAM; that shrinks
the reserve and hands the memory back to containers.

## Sizing a worker to its challenge mix

**Affects** `multihost_docker`, `docker` · **Action required: none, but read before choosing an
instance type**

### Memory is the constraint. CPU is not.

Measured on a loaded 2 GiB / 2 vCPU worker: five containers consumed **3395 CPU-seconds over a
week of uptime** — 0.28% of the box — and the slice was throttled for **0.1 s** against its 160%
quota. Another worker showed 6.1 s of throttling over six days. The CPU ceiling has never come
close to binding on any worker measured.

**Do not size instances from load average.** That same worker reported a load of 4.14 on two
cores while using 0.28% of them. Linux counts uninterruptible sleep in the load average, and on
these workers that is memory-reclaim stall rather than runnable work — the same box reported
12.7% memory pressure (`memory.pressure` avg300). Load here tracks memory starvation, so reading
it as CPU demand over-provisions cores and under-provisions RAM, which is exactly backwards.

Choose an instance for its memory and take whatever CPU comes with it.

### Container memory scales with activity, not with challenge type

Per-container `memory.current` means measured across the fleet:

| worker state | mean | notes |
| --- | --- | --- |
| idle | 17.7 – 19.3 MiB | quiet hours, containers parked |
| light | 88.6 MiB | a few challenges open |
| busy | 174.9 MiB | under active use; largest single container 457 MiB |

A 10x spread on one fleet. The consequence: **the slice holds a fixed amount of memory, and
container count is that memory divided by whatever the mean happens to be.** A 16 GiB worker has
been observed running ~300 containers (implying a ~42 MiB mixed mean), and would hold roughly 85
if every one were busy. Both are the same worker doing its job.

There is therefore no container count to design for — only a memory budget.

### When to pin `container_slice_target_containers`

Capacity is derived from RAM assuming a `container_slice_min_mean_container_mb` mean, which is
deliberately a low floor. That is right when a worker runs many small containers and wasteful
when it runs few large ones, because the shim reserve is `6 MiB x capacity` whether those
containers exist or not.

The arithmetic is simple — `MemoryMax = MemTotal - (OS + dockerd + user) - (6 x capacity)` — so
**every container of over-estimate costs the slice 6 MiB.**

* **Many small containers**, the common case: leave it `null`. The derived capacity ran 1.4x the
  observed peak on a 16 GiB worker, which is appropriate headroom.
* **Few large containers**: pin it. A loaded 2 GiB worker running five challenges at a 175 MiB
  mean had capacity derived at 33, reserving 198 MiB of shim budget to serve 30 MiB of actual
  shims. Pinning to 8 returns 150 MiB to the slice on a box that had 578 MiB free.

Pin from an **observed peak concurrent container count** plus margin, never from a memory-derived
estimate. Under-pinning is the dangerous direction: the reserve then covers fewer shims than
actually exist, and the shortfall lands on the host rather than inside the slice.

### Practical floor

A worker whose challenges run ~175 MiB apiece needs roughly `175 x concurrent` plus the ~700 MiB
flat host reserve plus `6 x concurrent`. Five such challenges want ~1.6 GiB before the OS gets
anything, which is why 2 GiB workers OOM-kill under load no matter how the slice is tuned — that
is an instance-size problem, not a configuration one.

**4 GiB is the sensible minimum.** 8 GiB buys roughly 2.3x the concurrent challenges rather than
2x, because the flat part of the host reserve is amortised over more containers: at a 175 MiB
mean a 4 GiB worker sustains ~17 and an 8 GiB worker ~40.

## cgroup v1 support dropped

**Affects** `multihost_docker`, `docker` · **Action required: none on jammy/noble**

The roles now assert on the unified (v2) hierarchy and fail rather than silently ignoring
`CPUWeight`, `MemorySwapMax`, `MemoryMin` and `MemoryLow`, which are all v2-only. Both
supported releases are unified by default.

This removed the GRUB `cgroup_enable=memory swapaccount=1` task **and the reboot it
triggered on every worker's first run** — those are v1 parameters and were no-ops on
jammy and noble, so the role was rebooting hosts to apply nothing.

## ufw no longer drops forwarded container traffic (nftables backend)

**Affects** `multihost_docker`, `docker` when `docker_firewall_backend: nftables`
· **Action required: none, but know the scope**

On the nftables backend Docker's rules live in `table ip docker-bridges` while ufw's
`FORWARD` policy of DROP stays in `table ip filter`, so ufw silently killed **all**
container egress. The roles now set ufw's routed policy to allow on that backend.

Note the scope: this is ufw's **global** routed policy, not a docker-scoped rule — ufw has
no stable handle for Docker's bridges, since a user-defined network's `br-<id>` interface
is created at runtime. Fine on a single-purpose host; a host that also routes for
something else (second NIC, VPN) wants a narrower rule instead.

Container egress denials are unaffected — they are enforced by the role's own
`table inet container_egress`, not by ufw's default.

## nftables firewall backend

**Affects** `multihost_docker` (default) · `docker` (opt-in)
· **Action required: a Docker upgrade, if you opt in**

`multihost_docker` defaults to the nftables backend, which measured ~7x the launch
throughput of iptables on the challenge worker fleet. It requires **Docker >= 29.6.0** and
the roles assert on the installed version, because 28.x accepts
`"firewall-backend": "nftables"` and silently goes on programming iptables, while 29.0–29.5
abort the daemon on a netlink socket with a file descriptor over 1024 (moby#52873).

**An existing worker on 28.5.2 will fail that assert.** With `docker_pin_version: false`
and `upgrade: no` the unpinned install is `state: present` against an already-installed
package, so the host never moves and the guard then fails. Set `docker_pin_version: true`
to install the pinned 29.6.0 in the same play, or `upgrade: yes`, or fall back with
`docker_firewall_backend: iptables` to decouple this from the cgroup work above. The
upgrade restarts `dockerd`, so it belongs in the same drain window.

`docker` deliberately stays on `iptables` and keeps its sub-29 pin: it also serves webshell
toolbox hosts, and the 28.5.2 hold was intentional (`last < 29`). Opting that role into
nftables means raising `docker_version_pin_map` too — read the note on that variable first.

## `net.ipv4.ip_forward` set explicitly

**Affects** `docker` when `docker_firewall_backend: nftables` · **Action required: none**

Docker enables IPv4 forwarding itself only on the iptables backend. On nftables, a host
that never had it set does not merely lose container egress — `dockerd` exits 1 while
creating the default bridge and the service never starts. `multihost_docker` already set
the sysctl; `docker` now does too.
