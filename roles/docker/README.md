# docker

## Description

Installs [Docker Engine](https://docs.docker.com/engine/) on a host and configures various settings
in order to provide an optimal experience for challenge servers and
[webshell](https://github.com/picoCTF/webshell) toolbox hosts.

The Docker configuration changes made by default include:

### TLS Docker socket access

The Docker daemon socket is [exposed over
TLS](https://docs.docker.com/engine/security/protect-access/#use-tls-https-to-protect-the-docker-daemon-socket)
on port 2376. This is useful for challenge backends like
[Hacksport](https://github.com/picoCTF/hacksport), which require external access to the Docker
daemon. It is also useful for running webshell toolbox containers on a separate host from the
launcher, as recommended.

The variable `tls_SANs` must be specified as a list of all [Subject Alternative
Names](https://en.wikipedia.org/wiki/Subject_Alternative_Name) from which the socket should be
accessible. By default, the generated TLS client certificates are fetched to the host running
Ansible. See [below](#tls-docker-socket-access-settings) for a full list of configurable options.

### Storage quotas

The Docker daemon state is stored on a separate device, which is formatted with the
[XFS](https://en.wikipedia.org/wiki/XFS) filesystem. By mounting this filesystem with the [`pquota`
mount
option](https://access.redhat.com/documentation/en-us/red_hat_enterprise_linux/7/html/storage_administration_guide/xfsquota)
and using the [overlay2 storage
driver](https://docs.docker.com/engine/reference/commandline/dockerd/#daemon-storage-driver), we can
enforce size limits for [Docker volumes](https://github.com/moby/moby/pull/41330) (useful for
webshell home directories) and the [writable layers of
containers](https://github.com/moby/moby/pull/24771) (useful for preventing abusive disk usage in
both challenge and webshell containers).

The variable `storage_device` must be specified as the path of the block device to be formatted as
XFS and used to store the Docker state. This behavior can be disabled, in which case Docker graph
storage will be stored in `/var/lib/docker` as usual, and storage quotas will not be available.
However, this is **highly discouraged** in any situation where untrusted users may obtain access to
the filesystem, as a malicious user will easily be able to fill the disk and render the machine
inoperable.

### Default cgroup parent and memory accounting

The Docker daemon is configured to use a custom cgroup parent for all spawned containers. This
cgroup limits the CPU and memory resources available to all Docker containers to 90% of the system's
total resources to ensure that essential services like `sshd` and `atop` can still run regardless of
the resources used by running containers.

Memory and swap accounting [is
enabled](https://docs.docker.com/engine/install/linux-postinstall/#your-kernel-does-not-support-cgroup-swap-limit-capabilities)
in order to support the limits enforced by this parent cgroup. This also enables per-container
[memory and swap limits](https://docs.docker.com/config/containers/resource_constraints/#memory).

## Role Variables

### General settings

| Name | Description | Default |
| --- | --- | --- |
| `docker_group_users` | Adds these users to the `docker` group, granting them access to the daemon without `sudo`. | [] |
| `upgrade` | Whether to upgrade packages if already installed | false |

### TLS Docker socket access settings

| Name | Description | Default |
| --- | --- | --- |
| `tls_access` | Whether the Docker daemon should be externally accessible over TLS | true |
| `tls_expiration_days` | Validity period (in days) for generated TLS certs | 365 |
| `tls_SANs` | Subject Alternative Names to include in the generated server certificate. | ["DNS:localhost", "IP:127.0.0.1", "DNS:host.docker.internal"] |
| `tls_renew_certs` | Whether to generate new CA and client certs if they have expired | false |
| `tls_fetch_certs` | Whether to fetch generated client certs to the host running Ansible | true |
| `tls_fetched_cert_path` | Where fetched client certs will be stored on the host running Ansible | ./fetched/certs/ |

### Storage quota settings

| Name | Description | Default |
| --- | --- | --- |
| `storage_quotas` | Whether to enable storage quotas by storing the Docker daemon state in an XFS filesystem. | true |
| `storage_name` | The block device to format and mount as an XFS filesystem. | `/dev/nvme1n1` |
