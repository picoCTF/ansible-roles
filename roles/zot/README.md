# zot

## Description

Installs the [zot](https://zotregistry.dev/) OCI image registry as the cork fleet's
challenge-image store. Downloads the upstream `zot` binary, deploys a mutual-TLS
`config.json`, a hardened systemd unit, and the registry's server-only certificates, then
runs `zot` as a service.

The deployed `config.json` mirrors `config-examples/zot/config.json` in the
[challenge-orchestrator](https://github.com/CyLabAcademy/challenge-orchestrator) repo,
which is where the registry's access-control design is documented. In short: mTLS only,
identity taken from the client certificate's CommonName, and both `defaultPolicy` and
`anonymousPolicy` empty. **Challenge images embed flags — those two policies must stay
empty.**

Base OS setup (`os`, `atop`, `cloudwatch_agent`) is assumed; network exposure is handled
by security groups, so this role configures no firewall. The service runs under systemd
`DynamicUser` (no service account to create) and its image store is provisioned via
`StateDirectory=zot`. No `storage.gc*` keys are set, so zot's inline GC defaults apply.

### TLS material

The box holds **server identity only, no client cert**. Stage the bundle produced by
`config-examples/gen-docker-certs.sh` on the Ansible controller at `zot_cert_src`; the
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
| zot_storage_root | Image store directory. **Effectively fixed:** the unit hardcodes `StateDirectory=zot` and runs under `ProtectSystem=strict`, so any other value leaves zot unable to write its store. | `/var/lib/zot` |
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
```
