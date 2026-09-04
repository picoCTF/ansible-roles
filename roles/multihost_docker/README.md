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
