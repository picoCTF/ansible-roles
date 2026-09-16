# cork

## Description

Installs [cork](https://github.com/CyLabAcademy/challenge-orchestrator) on a host, as
either half of a deployment:

- an **orchestrator** — `corkd` and its CLI `cork`, serving instances on its workers;
- a **build plane** — `cork-build` and the artifact server, building every image and
  handing the finished builds to the orchestrators. The
  [`cork_build`](../cork_build/README.md) role is the profile that selects this; use it
  rather than setting the flags by hand.

The two halves are the split in
[issue #18](https://github.com/CyLabAcademy/challenge-orchestrator/issues/18): one build
plane, one shared registry, one orchestrator per event, and each orchestrator's own
workers. A one-box deployment is this role's default — `cork_build_plane: local`, where
`corkd` builds on its own docker daemon and runs what it builds.

### Prerequisites

An orchestrator on an external build plane needs **no docker daemon**. It drives the
worker daemons over TLS and reaches the registry itself, so its play needs `os` and
`atop` and nothing else.

A host that builds — a build plane, or a one-box deployment — needs
[`docker_builder`](../docker_builder/README.md), which is the `docker` role with the
builder's settings.

### Binaries

The release tarball is `cork_linux_<arch>.tar.gz` and carries `corkd`, `cork` and
`cork-build`, plus `cmgrd` and `cmgrd-cli` as symlinks for installers written before the
rename. This role installs the current names only, and picks the asset by
`ansible_facts['architecture']`, so a Graviton host gets the arm64 build.

`cork-build` is installed as `cork-build_bin`, with a generated wrapper at `cork-build`
carrying its environment — the same shape the `cmgr` role used for its CLI, and for the
same reason: it is a command rather than a daemon, so its settings cannot live in a unit
file. The wrapper owns the name on `PATH`.

### TLS material

cork holds the `CN=cmgr` client identity in two trust domains and is given whichever ones
its host acts in:

- `docker-{ca-cert,client-cert,client-key}.pem` → `{{ docker_cert_path }}/{ca,cert,key}.pem`,
  for cork's connections to the worker daemons. **Orchestrator only.**
- `zot-{ca-cert,client-cert,client-key}.pem` →
  `/etc/docker/certs.d/<registry>/{ca.crt,client.cert,client.key}`, for the registry.
  **Both halves**: a build plane pushes, and an orchestrator checks that every tag it is
  handed exists and untags what it retires — with no docker daemon of its own to do
  either.

The identity is still `CN=cmgr` on purpose. That name is a deployed certificate and zot's
access policy rather than a spelling, so renaming it would mean reissuing the fleet's PKI.

## Role Variables

### Which half this host is

| Name | Description | Default |
| --- | --- | --- |
| cork_build_plane | `CORK_BUILD_PLANE`: `local` (this host builds from the tree in `cork_dir`) or `external` (a build plane builds and hands the finished builds over). An external daemon ignores `CORK_DIR`, `CORK_ARTIFACT_DIR`, `CORK_BASE_PINS`, `CORK_PURGE_AFTER_PUSH` and `DOCKER_HOST`, and names each one it finds set — so this role omits them there. | `local` |
| cork_daemon_enabled | Whether `corkd` is installed and run. Off on a build plane, which serves nothing. | `yes` |
| cork_builder_enabled | Whether `cork-build` and its wrapper are installed. On only on a build plane. | `no` |

### Installation

| Name | Description | Default |
| --- | --- | --- |
| cork_version | cork release to install (e.g. `vX.Y.Z`), or `latest`. | `latest` |
| cork_upgrade | Whether to upgrade an existing installation. | `no` |
| cork_clean_upgrade | With `cork_upgrade`, remove the database and artifact tarballs first and force a reinstall. **Destructive, and worse on a build plane:** that database records which build id each artifact bundle is named by, and an orchestrator has adopted those ids, so clearing it makes every later hand-over conflict with rows the orchestrator already holds. It also runs `rm -rf` over everything in `cork_artifact_dir`, which the defaults keep clear of the tree — a deployment that points both at one directory loses the checkout along with the bundles. | `no` |
| cork_github_url | Release repo. | `https://github.com/CyLabAcademy/challenge-orchestrator` |

### Certificates

| Name | Description | Default |
| --- | --- | --- |
| cork_deploy_certs | Whether to deploy any certificates from the controller. | `yes` |
| cork_deploy_docker_certs | The docker-ca set (cork → workers). | `{{ cork_daemon_enabled }}` |
| cork_deploy_registry_certs | The zot-ca set (cork → registry). Derived, so a one-box deployment with no `cork_registry` asks for none. | `cork_registry is set` |
| cork_cert_src | Path **on the Ansible controller** holding the bundle files. | `./docker-certs` |
| docker_cert_path | On-host `DOCKER_CERT_PATH`. | `/root/.docker_certs` |

### Settings

Each variable below sets the matching `CORK_*` environment variable — in `corkd.service`
for the daemon, and in the `cork-build` wrapper on a build plane. Those left unset are
omitted entirely, so cork's own defaults apply. Cork still reads the pre-rename `CMGR_*`
names when the new ones are unset, but names each one it finds at startup, so this role
writes only the current spellings.

| Name | Description | Default |
| --- | --- | --- |
| cork_registry | `CORK_REGISTRY`. Also names the `certs.d` directory and the registry images are tagged with, so every host in a deployment must agree on it. The default is a **placeholder**, which the role asserts against wherever a registry is required — a build plane, which pushes, and an external daemon, which checks and untags. A one-box deployment may set this to `null`: it builds and runs on one daemon, so there is nothing to push to. | `REPLACE_ME:5000` |
| cork_db | `CORK_DB`. Outside the tree deliberately: on a build plane `cork_dir` is a git checkout, and this database is the one thing that must not be lost, since an orchestrator records each build under the id this plane gave it. | `/cork/cork.db` |
| cork_dir | `CORK_DIR`. Created `0770` where this host builds; an external daemon gets none. | `/cork/challenges` |
| cork_artifact_dir | `CORK_ARTIFACT_DIR`, and the artifact server's `CMGR_ARTIFACT_DIR` — the wrapper and the unit export both names from this one value, because the artifact server reads the old spelling and always will. Build plane only. | `/cork/artifacts` |
| cork_logging | `CORK_LOGGING`: `debug`, `info`, `warn`, `error` or `disabled`. `corkd` has no flag for it, so this is the only way to raise an orchestrator's logging. **Note:** cork only began reading it with the build plane split, so a deployment upgrading from before that has been logging at INFO whatever this said, and goes quiet when the upgrade lands. | `warn` |
| cork_registry_cert_dir | `CORK_REGISTRY_CERT_DIR`. | unset |
| cork_purge_after_push | `CORK_PURGE_AFTER_PUSH`. Drops the builder's local copy of each image once it is pushed. **The `docker_builder` GC policy depends on this** — BuildKit may only evict cache records nothing references, so images retained here pin the cache and no `maxUsedSpace` value bounds the volume. Omitted on an external daemon. | `yes` |
| cork_ports | `CORK_PORTS`, e.g. `49152-65535`. Consider pairing with the `os` role's `ephemeral_port_range`. | unset |
| cork_concurrent_launches | `CORK_CONCURRENT_LAUNCHES` (1–16; no gain measured past 2). | unset |
| cork_prune_age | `CORK_PRUNE_AGE`. Must not exceed `multihost_docker`'s container sweep age (currently `30m`); a longer value leaves corkd serving instances whose containers docker-reaper has already removed. Nothing validates the pair. | `30m` |
| cork_db_wal | `CORK_DB_WAL`. Unset means cork's own default, which is **WAL on** — this is only the knob for turning it off. Rendered as `on`/`off`, since cork compares case-sensitively against `false`/`0`/`off` and a literal `false` in a play would reach the unit as `False` and be ignored. | unset (WAL on) |
| cork_enable_disk_quotas | `CORK_ENABLE_DISK_QUOTAS`. | unset |
| cork_base_pins | `CORK_BASE_PINS`, the base image digest pin file. Set to the corpus root so it is **committed to the challenge repository** and versioned with the Dockerfiles it pins — losing the pins is not a no-op, since an empty map fingerprints differently and every challenge's next rebuild produces a differently tagged image. Nothing creates the file; `cork-build pin-refresh` writes it. Omitted on an external daemon, which answers 409 to the pin endpoints. | `<cork_dir>/base-pins.json` |
| cork_extra_environment_vars | Extra environment variables, as a string map. | `{}` |

`CORK_INTERFACE`, `CORK_REGISTRY_USER` and `CORK_REGISTRY_TOKEN` are deliberately not set,
because cork ignores all of them.

### Destinations (build plane only)

| Name | Description | Default |
| --- | --- | --- |
| cork_destinations | Map of destination name → orchestrator address, rendered to the `CORK_DESTINATIONS` file. A schema's `destination:` resolves against it, so a typo is refused here rather than dialled. **Use internal addresses:** the cork API carries no authentication, and a security group that admits the build plane admits it on the private network only. | `{}` |
| cork_destinations_path | Where that file is written. | `/etc/cork/destinations.yml` |

### Artifact server

| Name | Description | Default |
| --- | --- | --- |
| artifact_server_enabled | Whether `cmgr-artifact-server` is installed **and** run. It publishes what a build plane writes, so an orchestrator on an external plane gets neither the binary nor the unit. | `{{ cork_build_plane != 'external' }}` |
| artifact_server_version | Release to install, or `latest`. Note that `latest` installs only when the binary is **absent** — an already-provisioned host needs one pass with `artifact_server_upgrade: yes`. | `latest` |
| artifact_server_upgrade | Whether to upgrade an existing installation. | `no` |
| artifact_server_min_version | Floor asserted on a build plane. **v3.0.0 is required there:** a plane writes one subdirectory per destination, and only v3 treats those as namespaces (it looks for the `.cork-artifact-namespace` marker `cork-build` leaves in each). v2 ignores every subdirectory, so it publishes nothing at all and says nothing — an artifact directory with no builds in its root looks exactly like a host that has not built yet. | `3.0.0` |
| artifact_server_backend | `selfhosted` or `s3`. | `selfhosted` |
| artifact_server_other_options | Extra command-line options. | unset |
| artifact_server_extra_environment_vars | Extra environment variables, as a string map. | `{}` |
| artifact_server_github_url | Release repo. | `https://github.com/picoCTF/cmgr-artifact-server` |

## Usage

An orchestrator fed by a build plane:

```yaml
- hosts: orchestrator
  tasks:
    - include_role:
        name: picoctf.ansible_roles.cork
      vars:
        cork_build_plane: external
        cork_registry: "registry.example.internal:5000"
        cork_cert_src: "./docker-certs"
        cork_db: /var/lib/cork/cork.db
```

A one-box deployment, which is this role's default shape. No registry, because it builds
and runs on the same daemon, and no certificates, because there is no worker to
authenticate to and no registry to present a client certificate to:

```yaml
- hosts: classroom
  tasks:
    - include_role:
        name: picoctf.ansible_roles.docker_builder
    - include_role:
        name: picoctf.ansible_roles.cork
      vars:
        cork_registry: null
        cork_deploy_certs: no
```

## Post-deploy: register the workers

Workers are registered by hand, or the orchestrator tries to run images on its own box —
and on an external build plane there is no docker daemon to run them on, so a launch with
no worker registered fails instead.

```shell
$ cork worker-add <private-ip> [public-address]   # once per worker
$ cork worker-list
```
