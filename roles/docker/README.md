# docker

Installs [Docker Engine](https://docs.docker.com/engine/) on a host.

## Role Variables

| Name | Description | Default |
| --- | --- | --- |
| `docker_group_users` | Adds these users to the `docker` group, granting them access to the daemon without `sudo`. | `[]` |
| `upgrade` | Whether to upgrade Docker if already installed | false |
