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

This role is a specialization of the generic `docker` role. The **key difference** is
TLS: the generic role *generates* a self-signed CA and certs per host, whereas a cork
worker *receives* pre-generated, fleet-wide certs from the Ansible controller (see
[TLS material](#tls-material-two-ca-model)). All other behavior — storage quotas, cgroup
limits, user-namespace remapping, the OCI interceptor, the log driver, container egress
firewalling, and docker-reaper — is inherited unchanged.

## TLS material (two-CA model)

cork uses **two** private certificate authorities, both of whose keys stay offline (on
no deployed box):

- **`docker-ca`** secures the mTLS channel between `cmgrd` and each worker's `dockerd`.
  Every worker shares **one** server certificate whose CN/SAN is `academy-docker-worker`
  — `cmgrd` pins that name rather than the dialed IP, so workers can be cloned without
  reprovisioning. `cmgrd` presents the `cmgr` client cert (which lives only on the
  orchestrator, **never** on a worker).
- **`zot-ca`** secures the registry. Workers pull challenge images using a shared,
  read-only `worker` client cert under `/etc/docker/certs.d/<registry>/`.

The six leaf files are produced by `config-examples/gen-docker-certs.sh` in the
`challenge-orchestrator` repo and **staged on the Ansible controller** at
`multihost_docker_cert_src` before running this role. No CA private key and no `cmgr`
identity is ever copied to a worker.

| Controller file (`multihost_docker_cert_src/`) | Deployed to | Purpose |
| --- | --- | --- |
| `docker-ca-cert.pem` | `/root/.docker_certs/docker-ca-cert.pem` | dockerd `--tlscacert` (verify cmgrd's client cert) |
| `docker-server-cert.pem` | `/root/.docker_certs/docker-server-cert.pem` | dockerd `--tlscert` (shared `academy-docker-worker` cert) |
| `docker-server-key.pem` | `/root/.docker_certs/docker-server-key.pem` | dockerd `--tlskey` |
| `zot-ca-cert.pem` | `/etc/docker/certs.d/<registry>/ca.crt` | verify zot's server cert |
| `zot-worker-cert.pem` | `/etc/docker/certs.d/<registry>/client.cert` | zot read-only pull cert |
| `zot-worker-key.pem` | `/etc/docker/certs.d/<registry>/client.key` | zot pull key |

The daemon socket is exposed over TLS on port **2376**; `cmgrd` dials
`tcp://<worker-ip>:2376`. See [settings](#tls-material-settings) below.

## cork-telemetry

`cmgrd` polls `http://<worker>:2136/health` roughly twice a second and expects an HTTP
200 with a JSON body `{"overloaded": <bool>}`; a worker reporting `overloaded: true` is
skipped for new placement. This role installs the `cork-telemetry` binary and a systemd
unit that serves that endpoint. The endpoint is plain HTTP by design — it carries no
secret and needs no TLS — so no certificates are deployed for it.

> **Placeholder download.** CyLabAcademy/cork-telemetry has no public release asset URL
> yet, so `cork_telemetry_download_url` defaults to `REPLACE_ME` and the role will fail
> fast until you set it (or set `cork_telemetry_enabled: no`). Point it at the
> `telemetry` binary asset. See [settings](#cork-telemetry-settings).

## Inherited Docker configuration

The following are configured exactly as in the `docker` role; consult that role's
documentation for the full rationale.

- **Storage quotas** — daemon state on a separate XFS device mounted with `pquota`, so
  volume and container-layer sizes can be capped (`storage_quotas`, `storage_device`).
- **cgroup parent limits** — a `limit_docker.slice` caps combined container CPU/memory to
  80% of the host, with memory + swap accounting enabled.
- **More Docker networks** — the default address-pool subnet size is set so thousands of
  isolated per-instance networks are available. At the default `network_prefix_length` of
  29 each network holds up to 5 containers; lower it to host challenges that run more
  containers than that per instance.
- **User-namespace remapping** — UID 0 in containers maps to an unprivileged host UID
  (`userns_remap_enabled`).
- **OCI runtime** — the [oci-interceptor](https://github.com/picoCTF/oci-interceptor)
  runc wrapper (`oci_interceptor_*`).
- **Log driver** — the `local` driver with a per-container size cap (`logs_max_*`).
- **Firewall** — container egress to the EC2 metadata endpoint (and any extra
  `container_deny_ipv4_cidrs`) is rejected via the `DOCKER-USER` chain.

## Docker resource reaper

[docker-reaper](https://github.com/picoCTF/docker-reaper) is installed and enabled as a
systemd service + timer. By default it runs every minute and does two sweeps: it removes
on-demand cmgr containers and networks (`label=cmgr.dynamic=true`) more than an hour old,
keeping a busy worker clean of finished challenge instances, and then evicts unused images
once the image store's filesystem passes 80% full, down to 70%. Configurable via
[role variables](#docker-reaper-settings).

Image eviction is safe under cork's registry design: an evicted image is at worst a re-pull
from zot on the next placement. Container cleanup also backstops cork itself — a worker
purged with `worker-remove`, or orphaned by a `clean_upgrade` on the orchestrator, leaves its
containers running, and this sweep is what reclaims them.

## Usage

Stage the fleet certs on the controller (once, from `challenge-orchestrator`):

```bash
cd config-examples && ./gen-docker-certs.sh 10.12.34.121   # -> ./docker-certs/
```

Then include the role for your worker hosts:

```yaml
- hosts: workers
  tasks:
    - include_role:
        name: picoctf.ansible_roles.os
    - include_role:
        name: picoctf.ansible_roles.multihost_docker
      vars:
        multihost_docker_cert_src: "../challenge-orchestrator/config-examples/docker-certs"
        multihost_docker_registry: "10.12.34.121:5000"
        storage_device: /dev/nvme1n1
        cork_telemetry_download_url: "https://.../telemetry"   # once published
```

The SSH user must be able to `become` root. `become` is applied by the role, so you do
not need to set it in your play.

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

| Name | Description | Default |
| --- | --- | --- |
| `tls_access` | Whether the Docker daemon is exposed over TLS on 2376. Required for cork. | `true` |
| `tls_cert_path` | On-host directory holding the dockerd server material; `daemon.json` points `--tlscacert`/`--tlscert`/`--tlskey` here. A `/root` subdir keeps it unreadable to a non-root container escapee. | `/root/.docker_certs` |
| `multihost_docker_cert_src` | Path **on the Ansible controller** holding the six leaf files from `gen-docker-certs.sh` (`docker-ca-cert.pem`, `docker-server-cert.pem`, `docker-server-key.pem`, `zot-ca-cert.pem`, `zot-worker-cert.pem`, `zot-worker-key.pem`). | `./docker-certs` |
| `multihost_docker_registry` | zot registry address (`host:port`). Also the `/etc/docker/certs.d/<dir>` name and must match `CMGR_REGISTRY` on the orchestrator. **Placeholder** — the default is not a real registry. | `1.2.3.4:5000` |

### cork-telemetry settings

| Name | Description | Default |
| --- | --- | --- |
| `cork_telemetry_enabled` | Whether to install and run the cork-telemetry health agent. | `yes` |
| `cork_telemetry_version` | Release tag of cork-telemetry (informational; used in messages). | `v0.0.1` |
| `cork_telemetry_download_url` | URL of the `telemetry` binary asset. **Placeholder** `REPLACE_ME` until a public URL exists — the role fails fast if left unset while telemetry is enabled. The download is not checksum-verified. Changing this URL reinstalls the agent: the role records each install's source in `/etc/cork-telemetry/.installed-source` and compares against it, since the agent exposes no version flag. | `REPLACE_ME` |

### Firewall settings

| Name | Description | Default |
| --- | --- | --- |
| `container_deny_ipv4_cidrs` | Traffic to these IPv4 CIDRs from inside any container is rejected. | `["169.254.169.254/32"]` |

ufw is enabled with a **default-allow** policy; the role adds no port restrictions of its own.
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
| `oci_interceptor_flags` | Flags to pass to `oci-interceptor`. | `["--oi-readonly-networking-mounts"]` |

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
| `docker_reaper_interval_secs` | How frequently (in seconds) to run `docker-reaper`. | `60` |
