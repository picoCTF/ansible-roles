# Migration notes

These roles are not versioned, so this file carries what a changelog would not: changes
that need an operator to **do something** — drain a host, upgrade a package, set a
variable — rather than just re-run the role. Re-running a role and getting the new
behaviour for free does not belong here.

One section per feature, newest first. Each says what changed, who it affects, and what
you have to do.

---

## The cork orchestrator moves to `docker_builder`

**Affects** `docker`, `cork` · **Action required: change the play, expect a dockerd restart**

The cork orchestrator has been using the plain `docker` role, whose defaults are
shaped for a host running untrusted challenge containers. Three of them are wrong on a
builder, and one thing it needs did not exist. The new `docker_builder` role is a profile
over `docker` — same installation, storage, firewall and cgroups — that turns the OCI
runtime shim off, turns docker-reaper off, drops TLS and userns-remap, and adds a
**BuildKit build cache GC policy**. Dropping TLS means `certs.yml` is skipped entirely, so
no certificates are configured on the builder at all; `cmgrd` reaches the daemon over the
local unix socket.

The GC policy is the substantive part. cork now builds with BuildKit, whose cache lives in
its own store rather than as untagged images. That is what makes reclaiming disk and
keeping the shared `apt`/`pip` layers separable goals instead of the same knob — but it
also means nothing bounds the cache unless a policy does, since `docker image prune` does
not touch it.

**In the play**, replace the role on the orchestrator host:

```yaml
- include_role:
    name: picoctf.ansible_roles.docker_builder   # was: picoctf.ansible_roles.docker
  vars:
    docker_group_users: ["ubuntu"]
    storage_mount_point: /mnt/data
    storage_device: /dev/disk/by-id/...   # a stable by-id symlink, not /dev/nvme1n1
```

`tls_access: no` and `userns_remap_enabled: no` can come out of the play — they are the
role's defaults now.

**One inherited fix rides along, and it can move `daemon.json` on a host that
is not a builder.** `daemon.json.j2` gated `tls_access`, `storage_quotas`,
`userns_remap_enabled` and `oci_interceptor_enabled` on bare truthiness while
the tasks that act on them used `| bool`. A host that supplies one of those as
the *string* `"no"` (a quoted value in group_vars, or `-e name=no` on the command
line -- the `key=value` form of `--extra-vars` always yields a string, though its
JSON and `@file` forms preserve types) therefore had the feature written into
`daemon.json` while the tasks implementing it were skipped. The template now
uses `| bool` in both places, so such a host renders differently and the restart
handler fires. The change is one-way -- the template can only emit less than it
did -- and a host using real YAML booleans, which is all of them unless someone
overrode with a string, renders byte-identically. **Grep your inventory for
quoted or `--extra-vars` forms of those four names before running this**; a
`userns_remap_enabled: "no"` host will restart dockerd into a different
data-root layout, and a `storage_quotas: "no"` one will restart it onto
`/var/lib/docker`, leaving everything on the mounted volume invisible.

**Expect a restart.** `daemon.json` gains a `builder` block and loses the
`default-runtime`, so the handler restarts dockerd. Do it when nothing is mid-build; a
build interrupted this way just needs re-running, but a `cmgrd` update pass does not
recover on its own.

**docker-reaper's units are not removed.** Disabling it in the role stops the tasks from
running, but the `docker_reaper.service` and `.timer` already installed on the host stay
and keep firing. Stop and disable them by hand once:

```
sudo systemctl disable --now docker_reaper.timer docker_reaper.service
```

**The policy needs Docker 28 or newer, and the play fails if it is not.** Enabling GC
asserts docker-ce >= `builder_gc_min_docker_version` (28.0.0). An older daemon does not
reject `reservedSpace`/`maxUsedSpace`/`minFreeSpace` — it ignores them, leaving GC on with
entries that constrain nothing — so this is caught rather than left to be discovered as a
full disk. A host below that either takes a Docker upgrade or the older
`defaultKeepStorage`/`keepStorage` spelling. Only hosts moved to `docker_builder` are
affected; the assert is skipped everywhere GC is off.

**Watch the filter shape if you edit the policy.** dockerd accepts at most one value per
GC policy entry's filter and *refuses to start* on more — the form BuildKit's own upstream
documentation uses is a three-value filter. The `docker` role asserts the shape and the
count before writing the file, so a mistake fails the play rather than the daemon.

**Pass the play's variables as `include_role` vars, exactly as shown.** `storage_mount_point`
is a role *var* in the `docker` role, so moving it into group_vars silently reverts both
the mount point and the data-root to `/mnt/docker-data` — the volume is still mounted and
still used, just not where the play says. And invoke the role with `include_role` rather than a `roles:` list entry: bare
keys on such an entry are role params, which outrank the profile and quietly restore the
worker defaults it exists to change. Both traps are spelled out in the role's README.

**Nothing changes on a host that does not build.** The `builder.gc` block is rendered only
when `builder_gc_enabled` is set, and the template's whitespace control is deliberate: with
GC off, `daemon.json` comes out byte-identical to what it was before the block existed, so
the template task does not report changed and the handler does not restart dockerd. That is
checked by rendering the template at `HEAD` and in the working tree under the role's own
defaults and diffing — worth keeping, since two stray blank lines would otherwise restart
every challenge server in `playbook.yml` for a feature none of them use.

The legacy single-host deployment is untouched for the same reason: it runs the separate
`cmgr` role, which installs upstream `picoCTF/cmgr` and has no base-pinning to configure.

Separately, the `cork` role now sets `CMGR_BASE_PINS` to `<CMGR_DIR>/base-pins.json`
instead of leaving cmgrd's default of `<CMGR_DIR>/.base-pins.json`. The point is the
missing dot: the pins are meant to be **committed to the challenge repository**, versioned
with the Dockerfiles they pin, so a base bump is a reviewable diff and a rebuilt
orchestrator comes back pinned. Generate the file once with `cmgrd-cli pin-refresh` and
commit it. On a host where `pin-refresh` has already been run, move the dotfile to the new
name. **This one does restart cmgrd**: the unit file gains a line, and `service.yml`
restarts on any unit change. Persistent instances come back on their own; an update pass in
flight does not, so apply it between passes.

**Rebuild passes want the fleet in maintenance.** Not a role change, but it belongs with
this one: cork serializes updates against each other and nothing stops the platform from
requesting launches of a build while that build is being replaced. A launch in flight can
collide with the update's teardown of the instances it displaces and fail the update.
There is no gate inside cork for this.

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
