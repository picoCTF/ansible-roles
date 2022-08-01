# picoCTF Ansible Roles

An [Ansible collection](https://docs.ansible.com/ansible/latest/user_guide/collections_using.html)
containing various roles for configuring picoCTF platform components and challenge server backends.

In most cases, all included roles are designed to be idempotent when re-run with the same
configuration.

However, some roles include variables which can cause non-idempotent behavior (upgrading packages,
regenerating certificates, etc.) if set to non-default values. Check each role's README file for a
full description of configurable variables.

Note that as of this writing, all roles have only been tested on x86_64 Ubuntu 20.04 LTS hosts,
though they may be portable to other platforms with minor changes.

## Included Roles

| Name | Description |
| --- | --- |
| [os](./roles/os/README.md) | Tweaks OS configuration to better support long-running servers. |
| [atop](./roles/atop/README.md) | Configures atop to regularly log process metrics. |
| [docker](./roles/docker/README.md) | Configures Docker Engine with ideal settings for platform components. |
| [cmgr](./roles/cmgr/README.md) | Installs cmgr and optionally configures a cmgrd server. |
| [actions_runner](./roles/actions_runner/README.md) | Installs the self-hosted GitHub Actions runner. |
| [cloudwatch_agent](./roles/cloudwatch_agent/README.md) | Installs and configures the AWS CloudWatch Agent. |

## Quick Start

1. Install the collection:

    ```shell
    $ ansible-galaxy collection install -f .
    ```

1. Write a [playbook](https://docs.ansible.com/ansible/latest/user_guide/index.html#writing-tasks-plays-and-playbooks) mapping desired roles to your hosts, e.g.:

    ```yaml
    # example_playbook.yml
    ---
    - hosts: all  # or a group from your Ansible inventory
      tasks:
        - include_role:
            name: picoctf.ansible_roles.<role_name>
          vars:
            sample: "value"
    ```

    Note that all roles in this collection already specify `become: yes` to elevate to root as
    necessary, so you do not need to handle that in your playbook.

    We recommend using `include_role` tasks rather than a top-level `roles:` section so that
    variables can be scoped to roles rather than the entire play.

1. Run the playbook:

    ```shell
    $ ansible-playbook example_playbook.yml
    ```

    If you don't want to define an [inventory
    file](https://docs.ansible.com/ansible/latest/user_guide/intro_inventory.html#intro-inventory),
    you can pass a host's SSH connection information directly to `ansible-playbook`:

    ```shell
    $ ansible-playbook -i sample-hostname.com, -u ubuntu --private-key /path/to/key_file
    ```

    Please note the trailing comma if specifying a single hostname using the `-i` flag. This is
    required so that Ansible parses the argument as a list of hosts rather than the path to an
    inventory file.

    Also note that the specified SSH user must be able to elevate to root [using
    `become`](https://docs.ansible.com/ansible/latest/user_guide/become.html).

## Development

A Vagrantfile is included to create a sample VM for testing roles.

1. Create the VM: `vagrant up`
1. Create a playbook:

    ```yaml
    # example-playbook.yml
    - hosts: all
      tasks:
        - include_role:
            name: picoctf.ansible_roles.os
        - include_role:
            name: picoctf.ansible_roles.docker
          vars:
            tls_access: no
            storage_device: /dev/sdc
        - include_role:
            name: picoctf.ansible_roles.cmgr
    ```

1. Reinstall the collection locally and run the playbook against the VM: `ansible-galaxy collection install -f . && ansible-playbook -i 127.0.0.1:$(vagrant ssh-config 2> /dev/null  | grep Port | awk '{print $NF}'), --private-key=$(vagrant ssh-config 2> /dev/null  | grep IdentityFile | awk '{print $NF}') -u=vagrant example-playbook.yml`
1. If necessary, SSH into the VM to see the results: `vagrant ssh`
