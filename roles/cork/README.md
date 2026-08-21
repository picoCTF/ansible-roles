# cork

## Description

Installs [cork](https://github.com/picoCTF/cmgr) — the multi-host challenge orchestrator
(a fork of cmgr) — on a host. Downloads the `cmgrd` daemon and `cmgrd-cli` client to
`/usr/local/bin`, deploys the orchestrator's TLS material, and optionally runs `cmgrd` as
a systemd service.

cork drives a fleet of worker dockerds over mTLS and pushes/pulls challenge images through
a zot registry. This role is derived from the `cmgr` role but slimmed for cork: it manages
a single `cmgrd` instance (cork provides multi-host support natively, so the cmgr role's
multi-mode and the env-injecting CLI wrapper are dropped) and adds first-class two-CA cert
deployment. `cmgrd-cli` is a thin HTTP client and needs no wrapper — it talks to the daemon
via `CMGRD_SERVER` (default `http://127.0.0.1:4200`).

The `cmgrd` API is exposed over HTTP on port 4200 with **no authentication** — restrict
access with security groups / a private network.

### Prerequisites

The orchestrator builds images on a **local Docker daemon**, so its play must also apply
the [`docker` role](../docker/README.md) (which additionally provides docker-reaper). This
role does not install Docker. Base OS setup (`os`, `atop`, `cloudwatch_agent`) is assumed.

### TLS material (two-CA)

cork holds the `CN=cmgr` **client** identity in both trust domains. Stage the bundle from
`config-examples/gen-docker-certs.sh` on the Ansible controller at `cork_cert_src`; the role
copies the orchestrator's two client sets (never a CA key):

| controller file | destination | purpose |
| --- | --- | --- |
| `docker-ca-cert.pem` | `{{ docker_cert_path }}/ca.pem` | verify worker dockerd server cert |
| `docker-client-cert.pem` | `{{ docker_cert_path }}/cert.pem` | cork → worker dockerds |
| `docker-client-key.pem` | `{{ docker_cert_path }}/key.pem` | |
| `zot-ca-cert.pem` | `/etc/docker/certs.d/<registry>/ca.crt` | verify zot server cert |
| `zot-client-cert.pem` | `/etc/docker/certs.d/<registry>/client.cert` | push (rw) + cmgrd delete |
| `zot-client-key.pem` | `/etc/docker/certs.d/<registry>/client.key` | |

`DOCKER_CERT_PATH` is set for cork's worker connections; the local build daemon uses the
unix socket. The `certs.d` set is used by the local dockerd to push and by cmgrd to delete.

## Role Variables

### Installation options

| Name | Description | Default |
| --- | --- | --- |
| version | cork release version to install (e.g. `vX.Y.Z`), or `latest`. | `latest` |
| upgrade | Whether to upgrade an existing cork installation. Check release notes for breaking changes. | `false` |
| clean_upgrade | With `upgrade`, remove the cmgr database and local build images first, and force reinstall even if the version is unchanged. Prunes all unused local images (`docker image prune --all`). **Destructive:** it runs `rm -rf` over everything in `cmgr_artifact_dir`, which defaults to the same directory as `cmgr_dir` — with the defaults that deletes the challenge tree, not just artifacts. It also does not touch the workers, so every challenge container running on them is orphaned until docker-reaper's sweep reclaims it. | `false` |
| cork_github_url | Release repo to download cork from, e.g. `https://github.com/CyLabAcademy/challenge-orchestrator`. The asset `cmgr_linux_amd64.tar.gz` must contain `cmgrd` + `cmgrd-cli`. The default is a **placeholder** and the role asserts against it, so this must always be set explicitly. | `REPLACE_ME` |

### Certificate deployment

| Name | Description | Default |
| --- | --- | --- |
| cork_deploy_certs | Whether to deploy the two client cert sets from the controller. | `true` |
| cork_cert_src | Path **on the Ansible controller** holding the gen-docker-certs.sh bundle (needs `docker-ca-cert.pem`, `docker-client-cert.pem`, `docker-client-key.pem`, `zot-ca-cert.pem`, `zot-client-cert.pem`, `zot-client-key.pem`). | `./docker-certs` |
| docker_cert_path | On-host `DOCKER_CERT_PATH` — where cork reads the docker-client certs for worker connections. | `/root/.docker_certs` |

### cmgrd service configuration

| Name | Description | Default |
| --- | --- | --- |
| cmgrd_service_enabled | Whether to run `cmgrd` as a systemd service. | `true` |
| cmgr_registry | zot registry address (`host:port`). Sets `CMGR_REGISTRY` and names the `certs.d` directory; must match the workers and how images are tagged. | `1.2.3.4:5000` (placeholder) |
| cmgr_db | Path to the cmgr database file. | `/challenges/cmgr.db` |
| cmgr_dir | Challenge directory (set to `0770`). | `/challenges` |
| cmgr_artifact_dir | Directory for artifact bundles. | `/challenges` |
| cmgr_logging | Sets `CMGR_LOGGING` in the unit, but **cmgrd ignores it** — it hardcodes `INFO`. Kept only so the variable is available if cork wires it up later. | `warn` |
| cmgr_registry_cert_dir | Override for `CMGR_REGISTRY_CERT_DIR` (default is `/etc/docker/certs.d/<registry>`). | unset |
| cmgr_ports | Challenge port range, e.g. `49152-65535`. Consider pairing with the `os` role's `ephemeral_port_range`. | unset |
| cmgr_concurrent_launches | `CMGR_CONCURRENT_LAUNCHES` (1 or 2). | unset (cork default 2) |
| cmgr_prune_age | `CMGR_PRUNE_AGE` for on-demand instances, e.g. `1h`. | unset (cork default 1h) |
| cmgr_db_wal | `CMGR_DB_WAL` (`false`/`off`/`0` to disable SQLite WAL). | unset (cork default on) |
| cmgr_enable_disk_quotas | Set truthy to enable the disk-quota challenge option. | unset |
| cmgr_extra_environment_vars | Extra environment variables for the cmgrd service, as a string map. | `{}` |

### Artifact server configuration

`cmgr_artifact_dir` (above) is also used by the artifact server.

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
        cork_cert_src: "../challenge-orchestrator/config-examples/docker-certs"
        cmgr_registry: "10.12.34.121:5000"
```

## Post-deploy: register the workers

**This role does not register workers, and a successful run does not give you a working fleet.**
Worker membership is runtime state in cmgrd's database, not configuration, so it is applied against
the running daemon:

```shell
$ cmgrd-cli worker-add <private-ip> [public-address]   # once per worker
$ cmgrd-cli worker-list                                # each should read "ok" after ~1s
```

Until at least one worker is registered, cmgrd falls back to **single-host mode** and launches
challenges on the orchestrator's own build daemon. This fallback is silent — nothing logs an error
and the playbook reports success — and it is not health-gated, because the per-worker telemetry
pollers are cork's only health system. Placement is round robin across registered workers, skipping
any reporting overloaded or down.

Worker changes take effect immediately; no `cmgrd` restart is needed. Re-running `worker-add` for an
IP that is already present rebuilds its connection from scratch, which is also the only way to
recover a worker that has been marked `down` (that state is sticky by design).
