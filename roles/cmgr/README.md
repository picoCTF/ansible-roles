# cmgr

## Description

Installs the [cmgr](https://github.com/ArmyCyberInstitute/cmgr) CTF challenge manager on a host.
Optionally, the `cmgrd` HTTP daemon can be configured to automatically run as a service with
specified settings.

Note that cmgr requires access to a [Docker
daemon](https://docs.docker.com/get-started/overview/#the-docker-daemon). We highly recommend using
the provided [docker role](../docker/README.md) to configure Docker Engine, as it optimizes the
daemon settings for use with challenge managers like cmgr.

`cmgr` and `cmgrd` will be installed to `/usr/bin` and should be available on the default `PATH`.

If enabled, a systemd unit `cmgrd.service` will be added which automatically runs `cmgrd` using the
specified configuration.

## Role Variables

### Installation options

| Name | Description | Default |
| --- | --- | --- |
| version | cmgr release version to install (e.g. `vX.Y.Z`). Can also be set to `latest` to automatically find the newest version. | `latest` |
| upgrade | Whether to upgrade an existing cmgr installation. Note that cmgr version upgrades may include breaking changes. Always check the cmgr release notes before enabling this option. | `false` |
| download_example_challenges | Whether to download the provided example challenges when installing cmgr. | `false`
| example_challenge_dir | Destination directory for downloaded example challenges. Will be deleted and recreated upon (re)installation. | `/challenges/examples/`

### cmgrd service configuration

Note that any variables specified here apply only to the instance of `cmgrd` automatically started
by `cmgrd.service`. When invoking `cmgr` manually, you may need to specify [environment
variables](https://github.com/ArmyCyberInstitute/cmgr#configuration) accordingly. However, if using
the default configuration, simply invoking `cmgr` from the `/challenges` directory is sufficient.

| Name | Description | Default |
| --- | --- | --- |
| cmgrd_service_enabled | Whether to automatically run `cmgrd` as a systemd service. | `true` |
| cmgrd_db | Path to cmgr database file | `/challenges/cmgr.db` |
| cmgrd_dir | Directory containing challenges | `/challenges` |
| cmgrd_artifact_dir | Directory for storing artifact bundles | `/challenges` |
| cmgrd_logging | Logging verbosity | `warn` |
| cmgrd_interface | Interface to which published challenge ports are bound | `0.0.0.0` |
| cmgrd_registry | Docker registry for frozen challenges | unset |
| cmgrd_registry_user | Username to use when authenticating with `cmgrd_registry` | unset |
| cmgrd_registry_token | Password/token to use when authenticating with `cmgrd_registry` | unset |
