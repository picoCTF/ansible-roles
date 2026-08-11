# zot

## Description

Installs the [zot](https://zotregistry.dev/) OCI image registry as the cork fleet's
challenge-image store. Downloads the upstream `zot` binary, deploys a mutual-TLS
`config.json`, the hardened systemd unit, and the registry's server-only certificates,
then runs `zot` as a service.

zot authenticates every client with **mTLS** and authorizes by certificate CommonName:
the orchestrator (`CN=cmgr`) has read/write/delete, workers (`CN=worker`) have read-only,
and anonymous access is denied (empty `defaultPolicy`/`anonymousPolicy`). Because
challenge images embed flags, these policies must stay closed — do not add an anonymous
or default policy.

Base OS setup (`os`, `atop`, `cloudwatch_agent`) is assumed; network exposure is handled
by security groups, so this role configures no firewall. The service runs under systemd
`DynamicUser` (no service account to create) and its image store at
`{{ zot_storage_root }}` is provisioned via `StateDirectory=zot`.

### TLS material

The box holds **server identity only, no client cert**. Stage the bundle from
`config-examples/gen-docker-certs.sh` on the Ansible controller at `zot_cert_src`; the role
copies three files to `/etc/zot/`:

| controller file | destination | purpose |
| --- | --- | --- |
| `zot-ca-cert.pem` | `/etc/zot/zot-ca-cert.pem` | `http.tls.cacert` — verify cmgr/worker client certs |
| `zot-server-cert.pem` | `/etc/zot/zot-server-cert.pem` | `http.tls.cert` |
| `zot-server-key.pem` | `/etc/zot/zot-server-key.pem` | delivered to the service via systemd `LoadCredential` (read at runtime from `/run/credentials/zot.service/`) |

zot trusts **only** the zot CA — place the zot CA (not the docker CA) at `http.tls.cacert`.

## Role Variables

| Name | Description | Default |
| --- | --- | --- |
| zot_version | Upstream zot release tag to install. | `v2.1.18` |
| zot_upgrade | Re-download the binary even if present (for version changes). | `false` |
| zot_checksum | Optional checksum for the download, e.g. `sha256:...`. Empty = unchecked. | `""` |
| zot_service_enabled | Whether to run zot as a systemd service. | `true` |
| zot_address | Bind address. | `0.0.0.0` |
| zot_port | Listen port (string, per zot config). | `"5000"` |
| zot_storage_root | Image store directory (managed by `StateDirectory=zot`). | `/var/lib/zot` |
| zot_log_level | zot log level. | `warning` |
| zot_deploy_certs | Whether to deploy the three server certs from the controller. | `true` |
| zot_cert_src | Path **on the Ansible controller** holding `zot-ca-cert.pem`, `zot-server-cert.pem`, `zot-server-key.pem`. | `./docker-certs` |

`zot_install_path` (`/usr/bin/zot`), `zot_config_dir` (`/etc/zot`), and `zot_download_url`
are internal constants in `vars/main.yml`.

## Usage

```yaml
- hosts: registry
  tasks:
    - include_role:
        name: picoctf.ansible_roles.os
    - include_role:
        name: picoctf.ansible_roles.zot
      vars:
        zot_cert_src: "../challenge-orchestrator/config-examples/docker-certs"
```
