# docker_builder

Configures the Docker host that **builds** cork's challenge images — the
cork orchestrator, and nothing else. Workers use `multihost_docker`.

This is a thin profile over the `docker` role rather than a third copy of it: it
includes that role with a handful of settings changed, so installation, storage,
firewall and cgroup configuration all stay in one place. Certificates are the
exception: with TLS off, `certs.yml` is skipped entirely and the builder has
none.

## Why the builder is not a worker

The orchestrator inherited the plain `docker` role, whose defaults are shaped for
a host that runs untrusted challenge containers. Three of those defaults are
wrong here, and one thing it never had is now needed.

Override these through the `docker_builder_*` variables in `defaults/main.yml`,
never through the docker-role names in the left column: the profile passes those
at include scope, which beats anything you set in group_vars, host_vars or play
vars. See "Two precedence traps" below.

| Setting (`docker` role name) | `docker` role default | Here | Why |
|---|---|---|---|
| `oci_interceptor_enabled` | yes | **no** | The runtime shim constrains challenge containers. The builder runs none, so enabling it only installs a wrapper as dockerd's default runtime with nothing to enforce. |
| `docker_reaper_enabled` | yes | **no** | See below — this is the one worth reading. |
| `userns_remap_enabled` | yes | **no** | Shifts ownership of the data-root and every build's filesystem for no gain, on a volume shared with the challenge checkout, database and artifacts. |
| `tls_access` | yes | **no** | `cmgrd` reaches this daemon over the local unix socket. There is no remote client to authenticate. Note `multihost_docker` has no such variable — it configures certificates unconditionally — so this row has no worker counterpart. |
| `builder_gc_enabled` | no | **yes** | The new part. See below. Override with `docker_builder_gc_enabled`. |

### docker-reaper

It does nothing here. The `docker` role installs exactly one reaper unit, whose
command is `containers --filter label=cmgr.dynamic=true --min-age 60m
--reap-networks`. The only container the builder ever runs is cork's artifact
extraction container, which carries no labels, so the sweep matches nothing and
the timer is pure overhead. That is the whole reason to switch it off.

The reason not to switch it back on is the *image* sweep, which the builder has
never run: `docker_reaper_images_command` exists only in `multihost_docker`, on
workers. Adding one here would be actively unsafe, not merely wasteful. It runs
asynchronously on a timer with no coordination with cork, and removes with
`noprune: false` so untagged parents cascade — it could evict an image in the
window between cork building it and cork pushing it. Disk on the builder is
bounded by the GC policy below plus cork's own retention and purge-after-push,
all of which are synchronous with the build path.

### The BuildKit GC policy

cork now builds with BuildKit, whose layer cache lives in its own store. That is
the whole point: under the classic builder the cache *was* untagged images, so
reclaiming image space destroyed the cache and the next build re-ran every
`apt-get install` in the fleet. The two are now separable — but nothing bounds
the cache unless this policy does, since `docker image prune` does not touch it
and `docker builder prune` is manual.

### Sizing it for a volume that is mostly not docker

This is the part to understand before raising any of the numbers. The storage
mount is shared with the challenge checkout, the database and the artifact
bundles, and on a populated deployment those can take **most of the volume
before docker stores anything at all**. What is left for the image store and
this cache *together* is a fraction of the disk, not the whole of it.

The default is a **25 GB ceiling** with a 2 GB floor, yielding whenever the
volume drops below 10 GB free. That is one policy entry, and it is the total —
BuildKit evaluates entries in order and each one's limits apply to the records
*it* selects, so an entry with no filter selects everything.

25 GB sounds generous until you look at what is actually in a build cache.
Measured on one built from four small example challenges:

```
615.0 MB   exec /bin/sh -c apt-get update && apt-get install -...
225.5 MB   pulled from docker.io/library/ubuntu:24.04@sha256:...
117.4 MB   exec /bin/sh -c apt-get update && apt-get install -...
```

A **base image is itself a cache record**, and a single shared `apt` layer can be
most of a gigabyte for trivial challenges. A fleet with dozens of distinct bases
and toolchain layers of a gigabyte or two runs into tens of gigabytes before
anything interesting is cached. A ceiling under that thrashes, and thrashing is
not cheap: evicting a base means re-pulling it from the registry and re-running
every shared install — the exposure pinning exists to remove.

There is deliberately **no `type==source.local` entry**. One used to cap build
contexts, and it was removed because it matched nothing: a real cork build cache
holds only `regular` records. cork hands BuildKit a fresh context tar per build
and BuildKit does not retain it as a cache record.

The image store is not governed here at all — cork's retention, its
purge-after-push and `update --prune-old` bound that, which is what leaves room
for a cache this size. **Without `--prune-old`, every rebuild orphans the
generation it displaces in the registry, permanently.** The builder's own copies
are dropped after the push by default, so the orphan accumulates in zot rather
than here — which is easy to miss precisely because the builder looks clean.

**`minFreeSpace` has to be reachable.** It is a backstop on the filesystem, not on
docker's share. Set above what the disk can actually reach once the corpus,
artifacts and image store have taken their part, GC prunes the cache down to
`reservedSpace` on every pass and still never satisfies it — at which point the
feature looks broken rather than conservative. Check the default against what a deployment really has
free, and lower it rather than assume the headroom is there.

`docker system df` and `docker buildx du` on a converged builder are what these
should be re-derived from; the figures above are budget arithmetic plus a
24-challenge measurement, not a fleet-scale one.

**One value per filter.** dockerd parses this policy at startup and refuses to
start on a filter carrying more than one value:

```
error initializing buildkit: error creating buildkit instance:
filters expect only one value
```

BuildKit's own documented default policy uses a three-value filter, so copying it
from upstream documentation takes the daemon down. Split it into one entry per
value. The `docker` role asserts this before it writes `daemon.json`, so the
failure surfaces as an ansible error rather than a dead daemon.

## What this role deliberately does not change

- **The container cgroup ceilings** (`limit_docker.slice`). The `docker` role
  applies them unconditionally, and their sizing is worker-shaped: a per-container
  shim reserve, a CPU quota of 80% per core, and a scheduler weight of 20 that
  makes containers yield to `system.slice`. On a host whose entire job is
  building, builds are the workload being deprioritized. This is left inherited
  rather than guessed at — it has not been measured on a builder, and the
  variables (`container_slice_cpu_percent_per_core`, `container_slice_cpu_weight`,
  `container_slice_target_containers`) are settable from the play if it turns out
  to matter.
- **`storage-driver: overlay2`**, which is inherited and must stay. On the
  containerd image store a *pulled* image cannot serve as a build cache source,
  which silently removes the shared layers this whole arrangement exists to keep.
- **The container egress denies** (the instance metadata endpoint). A build
  should not reach IMDS any more than a challenge should.

## Two precedence traps

Both are silent, both report a green play, and neither is anything ansible can
be made to do differently.

**Override through `docker_builder_*`, not the docker-role names.** The profile
passes the docker-role names as `include_role` params, which beat role defaults,
group_vars, host_vars, play vars, `include_vars` and `set_fact`. (These are
include params, not task vars: a genuine task var loses to `set_fact`, and these
do not.) So
`tls_access: yes` in `host_vars/` does nothing here; `docker_builder_tls_access:
yes` is the knob. Note that three of these are not simply the docker-role name with a prefix --
a segment is dropped: `docker_builder_reaper_enabled` feeds
`docker_reaper_enabled`, `docker_builder_gc_enabled` feeds `builder_gc_enabled`,
and `docker_builder_gc_policy` feeds `builder_gc_policy`.

**Invoke with `include_role`, or nest under `vars:`.** Role params (precedence
20) outrank task vars, and a bare key on a `roles:` list entry is a role param:

```yaml
roles:
  - role: picoctf.ansible_roles.docker_builder
    docker_reaper_enabled: yes     # a role param -- DEFEATS the profile
```
```yaml
roles:
  - role: picoctf.ansible_roles.docker_builder
    vars:
      docker_reaper_enabled: yes   # a role var -- the profile still wins
```

The first form matters when converting a host that previously ran the plain
`docker` role: any docker-role keys already sitting on that entry silently
survive the swap. `--extra-vars` (precedence 22) beats the profile the same way.
Neither is a supported way to configure this role — reach for the
`docker_builder_*` variable instead, which is the only form that works from
group_vars, host_vars or play vars.

A related trap belongs to the `docker` role rather than this one, but this role
is what hands you a play containing it: **`storage_mount_point` is a role *var*,
not a default**, so it only takes effect when passed the way the snippet below
passes it. Moved into group_vars it is silently ignored and both the mount and the
data-root fall back to `/mnt/docker-data`. The volume is still mounted and
dockerd still lands on it — `storage.yml` runs before `config.yml` and uses the
same variable for both — so nothing breaks; the storage is simply not where the
play says it is, which is its own kind of problem on a host whose disk budget is
the point. `docker_group_users` and `storage_device` are role defaults and keep
working from group_vars, so two of the three still apply and nothing looks
wrong.

## Usage

```yaml
- include_role:
    name: picoctf.ansible_roles.docker_builder
  vars:
    docker_group_users: ["ubuntu"]
    storage_mount_point: /mnt/data
    storage_device: /dev/disk/by-id/...   # a stable by-id symlink, not /dev/nvme1n1
```

Variables of the `docker` role are passed straight through. The builder profile
itself is overridable through the `docker_builder_*` variables in
`defaults/main.yml`.

Pair it with the `cork` role's `cmgr_base_pins`, which puts the base image digest
pins at the corpus root so they are committed with the challenges they pin. See
`BUILDER.md` in the challenge-orchestrator repository for what the builder does
with them.
