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
