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

The variable `tls_sans` must be specified as a list of all [Subject Alternative
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

### cgroup parent limits and memory accounting

The Docker daemon is configured to use a custom cgroup parent for all spawned containers. This
cgroup limits the combined CPU and memory available to all Docker containers to 90% of the system's
total resources in order to ensure that essential services like `sshd` and `atop` can continue to
run regardless of the resources used by running containers.

The memory cgroup and swap accounting [are
enabled](https://docs.docker.com/engine/install/linux-postinstall/#your-kernel-does-not-support-cgroup-swap-limit-capabilities)
in order to support the limits enforced by this parent cgroup. This also enables per-container
[memory and swap limits](https://docs.docker.com/config/containers/resource_constraints/#memory).

### Increased number of available Docker networks

[By default](https://github.com/docker/docker.github.io/issues/8663), Docker networks are created
with fairly large subnet sizes (/16 for the first 16, then /20) which allow thousands of containers
to be connected. However, this limits the total number of simultaneous Docker networks to 32.

When running challenge instances or webshell toolbox containers, we want each instance to be on its
own isolated network. Only having 32 total networks would be extremely limiting, but fortunately it
is possible to reduce the subnet size of newly created Docker networks. In this role, we set this
size to /29 by default, which allows for up to ~140,000 simultaneous Docker networks of up to 5
containers each (when using the default address pools).

If you are planning to host any challenges which require more than 5 containers, this subnet prefix
size must be lowered. See [below](#docker-network-settings) for more details.

### User namespace remapping

While appropriate security options should always be specified when running containers to limit the
possibility of container escapes, there is always the potential that a malicious user inside a
container will gain access to the host.

Typically, is especially problematic when the user is already root (UID 0) inside the container (the default for most images), as UIDs are shared between containers and the host.

To minimize the potential impact of a container escape, by default this role enables [user namespace
remapping](https://docs.docker.com/engine/security/userns-remap/). This means that UID 0 inside
running containers is mapped to an arbitrary UID with no privileges on the host. If a user manages
to escape from a container in which they were root, they will find themselves to be a random
unprivileged user on the host.

There are a few [limitations](https://docs.docker.com/engine/security/userns-remap/#user-namespace-known-limitations) when user namespace remapping is enabled, including:

- Containers cannot share the host PID or network namespaces
- Files inside host-mounted volumes will have incorrect ownership unless manually changed

These should not be relevant to challenge or webshell toolbox containers.

While not recommended, this functionality can be [disabled](#user-namespace-settings) if necessary.
Note that any existing image layers and Docker volumes will become inaccessible when user namespace
remapping is toggled on or off.

### OCI runtime

By default, the [OCI interceptor](https://github.com/picoCTF/oci-interceptor) runtime wrapper is
used along with runc. This can be used to work around limitations in Docker's native
resource-limiting capabilities.

### Log driver

As
[recommended](https://docs.docker.com/config/containers/logging/configure/#supported-logging-drivers)
in the Docker documentation, the daemon is configured to use the `local` log driver. Unlike the
default `json-file` driver, this driver places a cap on the maximum size of log files stored per
container.

This is important for interactive containers, as otherwise malicious users can easily exhaust the
Docker graph storage volume by generating excessive logs.

We've chosen to retain a fixed amount of logs per container rather than disabling logging entirely,
as it is often useful to examine the logs of challenge containers in order to diagnose problems. The
amount of log output retained (30m across 3 files) is somewhat reduced from the `local` driver's
[defaults](https://docs.docker.com/config/containers/logging/local/#options) but should still be
sufficient for the majority of use cases. The amount of output retained is customizable using the
variables [listed below](#logging-settings).

### Outbound access for custom Docker networks

Though not enabled by default, a setting is provided which prevents outbound network access from
containers on custom Docker bridge networks, such as
[cmgr](https://github.com/ArmyCyberInstitute/cmgr) challenges or
[webshell](https://github.com/picoCTF/webshell) toolbox containers. This can provide additional
security by ensuring that players cannot send malicious traffic from challenge servers or webshell
toolbox hosts.

When enabled, container-to-container connections inside the network and inbound connections via
published ports are unaffected. In addition, it is possible to specify an allowlist of IPs or CIDRs
that will remain accessible by containers on custom networks. See
[below](#custom-network-outbound-access-settings) for a list of configuration variables.

## Role Variables

### General settings

| Name | Description | Default |
| --- | --- | --- |
| `docker_group_users` | Adds these users to the `docker` group, granting them access to the daemon without `sudo`. | `[]` |
| `upgrade` | Whether to upgrade Docker packages if already installed | `false` |

### TLS Docker socket access settings

| Name | Description | Default |
| --- | --- | --- |
| `tls_access` | Whether the Docker daemon should be externally accessible over TLS | `true` |
| `tls_expiration_days` | Validity period (in days) for generated TLS certs | `365` |
| `tls_sans` | Subject Alternative Names to include in the generated server certificate.<br><br>Note: this can be modified without affecting the CA or client certificate, as long as they are still valid. | `["DNS:localhost", "IP:127.0.0.1", "DNS:host.docker.internal"]` |
| `tls_renew_certs` | Whether to generate new CA and client certs if they have expired | `false` |
| `tls_fetch_certs` | Whether to fetch generated client certs to the host running Ansible | `true` |
| `tls_fetched_cert_path` | Where fetched client certs will be stored on the host running Ansible | `./fetched/certs/` |

### Storage quota settings

| Name | Description | Default |
| --- | --- | --- |
| `storage_quotas` | Whether to enable storage quotas by storing the Docker daemon state in an XFS filesystem. | `true` |
| `storage_device` | The block device to format and mount as an XFS filesystem. | `/dev/nvme1n1` |

### Docker network settings

| Name | Description | Default |
| --- | --- | --- |
| `network_ip_pools` | Available IP ranges for Docker network creation. Determines the total number of available networks, along with `network_prefix_length`. | `["172.17.0.0/12", "192.168.0.0/16"]` |
| `network_prefix_length` | Number of prefix bits to use when creating Docker networks. This determines the number of containers (2^(32-*n*)-3) that can join the network and impacts the total number of available networks.<br><br>The default, `29`, allows 5 containers per network and should be appropriate for most challenge servers. However, this value must be lowered to host challenges with more than 5 running containers per network. | `29` |

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
| `oci_interceptor_flags` | Flags to pass to `oci-interceptor`. | `[]` |

### Logging settings

| Name | Description | Default |
| --- | --- | --- |
| `logs_max_size` | Maximum size of an individual container log file. | `10m` |
| `logs_max_files` | Maximum number of log files to retain per container. If rolling the logs creates excess files, the oldest are deleted. | `3` |

### Custom network outbound access settings

| Name | Configuration | Default |
| --- | --- | --- |
| `custom_networks_outbound_access_blocked` | If enabled, external outbound network traffic will be blocked for containers on custom Docker bridge networks. Temporary containers used during `docker build` and containers without a custom network are unaffected. | `false` |
| `custom_networks_allowed_ips` | A list of IPv4 addresses (or CIDRs) to be allowlisted when `custom_networks_outbound_access_blocked` is enabled. | `[]` |
