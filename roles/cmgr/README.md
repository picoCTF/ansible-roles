# cmgr

## Description

Installs the [cmgr](https://github.com/picoCTF/cmgr) CTF challenge manager on a host.
Optionally, the `cmgrd` HTTP daemon can be configured to automatically run as a service with
specified settings.

Note that cmgr requires access to a [Docker
daemon](https://docs.docker.com/get-started/overview/#the-docker-daemon). We highly recommend using
the provided [docker role](../docker/README.md) to configure Docker Engine, as it optimizes the
daemon settings for use with challenge managers like cmgr.

`cmgr` and `cmgrd` will be installed to `/usr/local/bin` and should be available on the default
`PATH`.

If enabled, a systemd unit `cmgrd.service` will be added which automatically runs `cmgrd` using the
specified configuration. The `cmgrd` API is exposed over HTTP on port 4200 and does not support
authentication. It is your responsibility to restrict access to this port.

[cmgr-artifact-server](https://github.com/picoCTF/cmgr-artifact-server) can also be configured as a
systemd service to automatically handle the distribution of build artifacts.

## Role Variables

### Installation options

| Name | Description | Default |
| --- | --- | --- |
| version | cmgr release version to install (e.g. `vX.Y.Z`). Can also be set to `latest` to automatically find the newest version. | `latest` |
| upgrade | Whether to upgrade an existing cmgr installation. Note that version upgrades may include breaking changes. Always check the release notes before enabling this option. | `false` |
| clean_upgrade | If enabled along with `upgrade`, will attempt to remove any existing cmgr database, artifact tarballs, containers, and images prior to upgrading cmgr. Useful if upgrading to a cmgr version with an incompatible database schema. Unlike `upgrade` alone, forces reinstallation even when specified cmgr version has not changed. When attempting to remove existing containers, networks, and images, any environment variables set via `cmgr_extra_environment_vars` (see below) will be applied, in order to work as expected with remote Docker daemons. Note also that images are removed by running `docker image prune --all`, which removes all unused images on the target daemon. Take care when using this feature if cmgr shares a Docker daemon with other applications. The frozen challenge registry (if specified) is not affected. | `false` |
| download_example_challenges | Whether to download the provided example challenges when installing cmgr. | `false` |
| example_challenge_dir | Destination directory for downloaded example challenges. Will be deleted and recreated upon (re)installation. This variable only takes effect during installation and upgrades. | `/challenges/examples/` |
| wrapper_enabled | Wraps the `cmgr` binary with a script that automatically sets any necessary [environment variables](https://github.com/ArmyCyberInstitute/cmgr#configuration) to match the [`cmgrd` service configuration](#cmgrd-service-configuration). This variable only takes effect during installation and upgrades. | `true` |
| cmgr_github_url | GitHub repo to download `cmgr` from. Can be used to install a forked `cmgr` version, but the repo must have a semver-compliant tagged release for compatibility with the `version` option. | `https://github.com/picoCTF/cmgr` |

### cmgrd service configuration

Note that if the `wrapper_enabled` option is set to false, the variables specified here apply only
to the instance of `cmgrd` automatically started by `cmgrd.service`. In that case, you may need to
manually set the equivalent [environment variables](https://github.com/ArmyCyberInstitute/cmgr#configuration)
when calling `cmgr`.

| Name | Description | Default |
| --- | --- | --- |
| cmgrd_service_enabled | Whether to automatically run `cmgrd` as a systemd service. | `true` |
| cmgr_db | Path to cmgr database file | `/challenges/cmgr.db` |
| cmgr_dir | Directory containing challenges. Will be set to `0770` permissions (root access only) | `/challenges` |
| cmgr_artifact_dir | Directory for storing artifact bundles | `/challenges` |
| cmgr_logging | Logging verbosity | `warn` |
| cmgr_interface | Interface to which published challenge ports are bound | `0.0.0.0` |
| cmgr_registry | Docker registry for frozen challenges | unset |
| cmgr_registry_user | Username to use when authenticating with `cmgr_registry` | unset |
| cmgr_registry_token | Password/token to use when authenticating with `cmgr_registry` | unset |
| cmgr_ports | Specifc range of ports (e.g. `49152-65535`) to use for hosting challenge containers. Assumes that cmgr(d) has exclusive control of these ports. If unspecified, containers will use random ephemeral ports and will become out-of-sync with the cmgr database if restarted. Consider using in conjunction with the [`OS` role's](../os/README.md) `ephemeral_port_range` variable to avoid potential conflicts. | unset |
| cmgr_enable_disk_quotas | Set to `true` to enable to enable the use of the [`diskquota`](https://github.com/ArmyCyberInstitute/cmgr#configuration) challenge option. | unset |
| cmgr_extra_environment_vars | Extra environment variables to set for the cmgrd service, as a map of string to string. | `{}` |

### Artifact server configuration

The `cmgr_artifact_dir` variable defined above is also used for the artifact server.

| Name | Description | Default |
| --- | --- | --- |
| artifact_server_version | cmgr-artifact-server release version to install (e.g. `vX.Y.Z`). Can also be set to `latest` to automatically find the newest version. | `latest` |
| artifact_server_upgrade | Whether to upgrade an existing cmgr-artifact-server installation. Note that version upgrades may include breaking changes. Always check the release notes before enabling this option. | `false` |
| artifact_server_service_enabled | Whether to automatically run `cmgr-artifact-server` as a systemd service. | `true` |
| artifact_server_backend | Artifact server backend to use. | `selfhosted` |
| artifact_server_other_options | Additional command-line options to pass to `cmgr-artifact-server`, e.g. `--backend-opt some=value --log-level debug`. | unset |
| artifact_server_extra_environment_vars | Extra environment variables to set for the cmgrd-artifact-server service, as a map of string to string. | `{}` |
| artifact_server_github_url | GitHub repo to download `cmgr-artifact-server` from. Can be used to install a forked `cmgr-artifact-server` version, but the repo must have a semver-compliant tagged release for compatibility with the `artifact_server_version` option. | `https://github.com/picoCTF/cmgr-artifact-server` |

### Multi mode

This mode allows multiple instances of `cmgrd` (and `cmgr_artifact_server`) to run on the same host.
This is designed to facilitate dividing a pool of challenges across multiple remote Docker Engine hosts (by running a unique set of schemas on each cmgrd / Docker Engine pair).

When multi mode is enabled, the following are suffixed by instance name:

- cmgrd systemd services, e.g. `cmgr_foo.service`.
- cmgr-artifact-server systemd services, e.g. `cmgr_artifact_server_foo.service`.
- cmgr wrapper scripts, e.g. `cmgr_foo`.

Most configuration variables are shared between all instances and function as normal, with a few exceptions documented below:

- `wrapper_enabled`: Always enabled. Suffixed wrapper scripts are necessary to disambiguate between cmgr instances.
- `cmgr_db`: A suffix will be added to each instance's database file, e.g. `cmgr_foo.db`.
- `cmgr_artifact_dir`: Subdirectories will be created for each instance.
- `cmgr_extra_environment_vars`: Ignored. Specify per-instance using `multi_mode_config`.
- `artifact_server_other_options`: Ignored. Specify per-instance using `multi_mode_config`.
- `artifact_server_extra_environment_vars`: Ignored. Specify per-instance using `multi_mode_config`.

Note that multi mode will only function correctly if each cmgr instance is configured to use a distinct remote Docker engine (by specifying `DOCKER_HOST`, `DOCKER_TLS_VERIFY`, and `DOCKER_CERT_PATH` in `cmgr_extra_environment_vars`).

| Name | Description | Default |
| --- | --- | --- |
| multi_mode_enabled | Run multiple instances of `cmgrd` and `cmgr_artifact_server` based on the `multi_mode_configuration` object. | `false` |
| multi_mode_config | Nested mapping containing per-instance configuration. See example value below. | `{}` |
| multi_mode_include_unsuffixed | Also run the standard, unsuffixed `cmgrd` and `cmgr_artifact_server` services, even when multi mode is enabled. Can be used to convert an existing deployment to a multi-instance server. | `false` |

#### Example `multi_mode_config` value

```yaml
multi_mode_config:
  foo:
    cmgrd_port: 4202
    cmgr_extra_environment_vars: {
      "DOCKER_HOST": "tcp://foo.docker.host:2376",
      "DOCKER_TLS_VERIFY": "true",
      "DOCKER_CERT_PATH": "/mnt/data/foo-certs",
    }
    artifact_server_other_options: "-o address=0.0.0.0:4203"
    artifact_server_extra_environment_vars: {
      "variable": "foo"
    }
  bar:
    cmgrd_port: 4204
    cmgr_extra_environment_vars: {
      "DOCKER_HOST": "tcp://bar.docker.host:2376",
      "DOCKER_TLS_VERIFY": "true",
      "DOCKER_CERT_PATH": "/mnt/data/bar-certs",
    }
    artifact_server_other_options: "-o address=0.0.0.0:4205"
    artifact_server_extra_environment_vars: {
      "variable": "foo"
    }
```
