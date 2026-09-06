# cork

## Description

Installs [cork](https://github.com/CyLabAcademy/challenge-orchestrator) — the multi-host
challenge orchestrator on a host. Downloads the `cmgrd` daemon and `cmgrd-cli` client to
`/usr/local/bin`, deploys the orchestrator's TLS material, and runs `cmgrd` and
`cmgr-artifact-server` as systemd services.

This role is derived from the cmgr role. See the
[challenge-orchestrator README](https://github.com/CyLabAcademy/challenge-orchestrator).

### Prerequisites

The orchestrator builds images on a **local Docker daemon**, so its play must also apply
the [`docker` role](../docker/README.md) (which additionally provides docker-reaper). This
role does not install Docker. Base OS setup (`os`, `atop`, `cloudwatch_agent`) is assumed.

### TLS material

- `docker-{ca-cert,client-cert,client-key}.pem` → `{{ docker_cert_path }}/{ca,cert,key}.pem`,
  used for cork's connections to the worker daemons.
- `zot-{ca-cert,client-cert,client-key}.pem` → `/etc/docker/certs.d/<registry>/{ca.crt,client.cert,client.key}`,
  used by the local dockerd to push and by cmgrd to delete tags.

The local build daemon itself is reached over the unix socket, so it needs no certificates.

## Role Variables

### Installation options

| Name | Description | Default |
| --- | --- | --- |
| version | cork release version to install (e.g. `vX.Y.Z`), or `latest`. | `latest` |
| upgrade | Whether to upgrade an existing cork installation. | `false` |
| clean_upgrade | With `upgrade`, remove the cmgr database and local build images first, and force reinstall even if the version is unchanged. **Destructive:** it runs `rm -rf` over everything in `cmgr_artifact_dir`, which defaults to the same directory as `cmgr_dir` — with the defaults that deletes the challenge tree, not just artifacts. It also does not touch the workers, so challenge containers running there are orphaned until docker-reaper reclaims them. | `false` |
| cork_github_url | Release repo to download cork from. The asset `cmgr_linux_amd64.tar.gz` must contain `cmgrd` + `cmgrd-cli`. | `https://github.com/CyLabAcademy/challenge-orchestrator` |

### Certificate deployment

| Name | Description | Default |
| --- | --- | --- |
| cork_deploy_certs | Whether to deploy the two client cert sets from the controller. | `true` |
| cork_cert_src | Path **on the Ansible controller** holding the six bundle files listed above. | `./docker-certs` |
| docker_cert_path | On-host `DOCKER_CERT_PATH`. | `/root/.docker_certs` |

### cmgrd service configuration

`cmgrd` always runs as a systemd service. Each variable below sets the matching `CMGR_*`
environment variable in the unit; see cork's README for what each one does. Those left
unset are omitted from the unit entirely, so cork's own defaults apply.

| Name | Description | Default |
| --- | --- | --- |
| cmgr_registry | `CMGR_REGISTRY`. Also names the `certs.d` directory, so it must match the workers and how images are tagged. The default is a **placeholder** the role asserts against, so this must always be set. | `REPLACE_ME:5000` |
| cmgr_db | `CMGR_DB`. | `/challenges/cmgr.db` |
| cmgr_dir | `CMGR_DIR`. Created `0770`. | `/challenges` |
| cmgr_artifact_dir | `CMGR_ARTIFACT_DIR`. Also used by the artifact server. | `/challenges` |
| cmgr_logging | Sets `CMGR_LOGGING`, but **cmgrd ignores it** — it hardcodes `INFO`. | `warn` |
| cmgr_registry_cert_dir | `CMGR_REGISTRY_CERT_DIR`. | unset |
| cmgr_ports | `CMGR_PORTS`, e.g. `49152-65535`. Consider pairing with the `os` role's `ephemeral_port_range`. | unset |
| cmgr_concurrent_launches | `CMGR_CONCURRENT_LAUNCHES` (1 or 2). | unset |
| cmgr_prune_age | `CMGR_PRUNE_AGE`. Must not exceed the `multihost_docker` role's container sweep age (currently `30m`); a longer value leaves cmgrd serving instances whose containers docker-reaper has already removed. Nothing validates the pair. | `30m` |
| cmgr_db_wal | `CMGR_DB_WAL` (`false`/`off`/`0` to disable). | unset |
| cmgr_enable_disk_quotas | `CMGR_ENABLE_DISK_QUOTAS`. | unset |
| cmgr_extra_environment_vars | Extra environment variables for the cmgrd service, as a string map. | `{}` |

`CMGR_INTERFACE`, `CMGR_REGISTRY_USER`, and `CMGR_REGISTRY_TOKEN` are deliberately not
set because cork ignores all of them.

### Artifact server configuration

| Name | Description | Default |
| --- | --- | --- |
| artifact_server_version | cmgr-artifact-server release version, or `latest`. | `latest` |
| artifact_server_upgrade | Whether to upgrade an existing cmgr-artifact-server. | `false` |
| artifact_server_service_enabled | Whether to run `cmgr-artifact-server` as a systemd service. | `true` |
| artifact_server_backend | Artifact server backend. | `selfhosted` |
| artifact_server_other_options | Extra command-line options for `cmgr-artifact-server`. | unset |
| artifact_server_extra_environment_vars | Extra environment variables for the artifact server, as a string map. | `{}` |
| artifact_server_github_url | Repo to download `cmgr-artifact-server` from. | `https://github.com/picoCTF/cmgr-artifact-server` |

## Usage

```yaml
- hosts: orchestrator
  tasks:
    - include_role:
        name: picoctf.ansible_roles.os
    - include_role:
        name: picoctf.ansible_roles.docker   # local build daemon + docker-reaper
    - include_role:
        name: picoctf.ansible_roles.cork
      vars:
        cork_github_url: "https://github.com/CyLabAcademy/challenge-orchestrator"
        cork_cert_src: "./docker-certs"
        cmgr_registry: "1.2.3.4:5000"
```

## Post-deploy: register the workers

You must manually register the workers on cork. Otherwise, it will attempt to run images on its own box!

```shell
$ cmgrd-cli worker-add <private-ip> [public-address]   # once per worker
$ cmgrd-cli worker-list
```
