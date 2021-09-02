# docker

Installs [Docker Engine](https://docs.docker.com/engine/) on a host.

## Role Variables

| Name | Description | Default |
| --- | --- | --- |
| `docker_group_users` | Adds these users to the `docker` group, granting them access to the daemon without `sudo`. | [] |
| `upgrade` | Whether to upgrade packages if already installed | false |
| `tls_access` | Whether the Docker daemon should be externally accessible over TLS | true |
| `tls_expiration_days` | Validity period (in days) for generated TLS certs | 365 |
| `tls_SANs` | Subject Alternative Names to include in the generated server certificate. | ["DNS:localhost", "IP:127.0.0.1", "DNS:host.docker.internal"] |
| `tls_renew_certs` | Whether to generate new CA and client certs if they have expired | false |
| `tls_fetch_certs` | Whether to fetch generated client certs to the host running Ansible | true |
| `tls_fetched_cert_path` | Where fetched client certs will be stored on the host running Ansible | ./fetched/certs/ |
