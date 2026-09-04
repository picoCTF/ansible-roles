# zot

## Description

Installs the [zot](https://zotregistry.dev/) OCI image registry as the cork fleet's
challenge-image store. Downloads the upstream `zot` binary, deploys a mutual-TLS
`config.json`, a hardened systemd unit, and the registry's server-only certificates, then
runs `zot` as a service.

Base OS setup (`os`, `atop`, `cloudwatch_agent`) is assumed; network exposure is handled
by security groups, so this role configures no firewall.

### Service account and image store

zot runs as a dedicated system user (`zot_user`, created by the role) that owns the image
store at `zot_storage_root`. The store is the only writable path inside the unit's sandbox.

Set `zot_storage_device` to keep the store on its own volume: the role formats the device as
XFS, mounts it at `zot_storage_root`, and grows the filesystem if the volume was enlarged, so
the root filesystem only has to hold the OS and the zot binary. Left unset, the store lives on
the root filesystem.

Earlier versions of this role ran zot under systemd `DynamicUser` with `StateDirectory=zot`,
which leaves `zot_storage_root` as a symlink into `/var/lib/private`. The role migrates such a
host by stopping zot and removing the symlink before mounting. Images already under
`/var/lib/private/zot` are not moved, and cork does not detect a registry that lost them: it
only pushes at build time. Repopulate by pushing the current tags from the orchestrator's
build daemon, which keeps every image it built, or by forcing a rebuild.

### TLS material

The box holds **server identity only, no client cert**. The
role copies `zot-ca-cert.pem`, `zot-server-cert.pem`, and `zot-server-key.pem` to
`/etc/zot/`. Note that only the CA and server certs are read from disk at runtime — the
key is handed to the service via systemd `LoadCredential` and read from
`/run/credentials/zot.service/`.

## Role Variables

| Name | Description | Default |
| --- | --- | --- |
| zot_version | Upstream zot release tag to install. | `v2.1.18` |
| zot_checksum | Optional checksum for the download, e.g. `sha256:...`. Empty = unverified. Upstream publishes `checksums.sha256.txt` in each release. | `""` |
| zot_service_enabled | Whether to run zot as a systemd service. | `true` |
| zot_address | Bind address. | `0.0.0.0` |
| zot_port | Listen port (string, per zot config). | `"5000"` |
| zot_user | System user zot runs as; owns the image store. Created by the role. | `zot` |
| zot_storage_root | Image store directory. Mount point for `zot_storage_device` when that is set. | `/var/lib/zot` |
| zot_storage_device | Block device to format as XFS and mount at `zot_storage_root`, e.g. an EBS volume by id. Unset keeps the store on the root filesystem. | unset |
| zot_log_level | zot log level. | `warning` |
| zot_deploy_certs | Whether to deploy the three server certs from the controller. | `true` |
| zot_cert_src | Path **on the Ansible controller** holding `zot-ca-cert.pem`, `zot-server-cert.pem`, `zot-server-key.pem`. | `./docker-certs` |

`zot_install_path` (`/usr/bin/zot`), `zot_config_dir` (`/etc/zot`), `zot_binary_filename`,
`zot_download_url`, and `zot_install_marker` are internal constants in `vars/main.yml`.
Because `zot_download_url` is in `vars/` rather than `defaults/`, it cannot be overridden
to point at a mirror or an air-gapped artifact store.

Changing `zot_version` is all that is needed to move between releases, in either
direction. zot exposes no version flag, so the role records each install's download URL in
`/etc/zot/.installed-source` and reinstalls whenever that no longer matches — removing the
marker forces a reinstall on the next run.

## Usage

```yaml
- hosts: registry
  tasks:
    - include_role:
        name: picoctf.ansible_roles.os
    - include_role:
        name: picoctf.ansible_roles.zot
      vars:
        zot_cert_src: "./docker-certs"
        zot_storage_device: /dev/disk/by-id/nvme-Amazon_Elastic_Block_Store_vol0123456789abcdef0
```
