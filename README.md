# picoCTF Ansible Roles

An [Ansible collection](https://docs.ansible.com/ansible/latest/user_guide/collections_using.html)
containing various roles for configuring platform components and compatible challenge server
backends. All included roles are designed to be idempotent (i.e. repeatedly applicable without side
effects) when the configured variables are unchanged. However, some roles do define variables which
may cause non-idempotent behavior (upgrading packages, regenerating certificates, etc.) if set to
non-default values. Check each role's README file for a full description of configurable variables.

Note that as of this writing, all roles have only been tested on amd64 Ubuntu 20.04 LTS hosts,
though they may work on other platforms with minor changes.

## Quick Start

1. Install the collection:

    ```shell
    $ ansible-galaxy install picoctf.ansible_roles
    ```

1. Write a [playbook](https://docs.ansible.com/ansible/latest/user_guide/index.html#writing-tasks-plays-and-playbooks) mapping desired roles to your hosts:

    ```yaml
    # sample_playbook.yml
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

    In our example playbook, we use `include_role` tasks rather than a top-level `roles:` section so
    that variables can be scoped to roles rather than the entire play.

1. Run the playbook:

    ```shell
    $ ansible-playbook sample_playbook.yml
    ```

    If you don't want to define an [inventory
    file](https://docs.ansible.com/ansible/latest/user_guide/intro_inventory.html#intro-inventory),
    you can pass a host's SSH connection information directly to `ansible-playbook`:

    ```shell
    $ ansible-playbook -i sample-hostname.com, -u ubuntu --private-key /path/to/key_file
    ```

    Please note the trailing comma if specifying a single hostname using the `-i` flag. This is
    required so that Ansible parses the argument as a list of hosts, rather than the path to an
    inventory file.

    Also note that the specified SSH user must be able to elevate to root [using
    `become`](https://docs.ansible.com/ansible/latest/user_guide/become.html).
