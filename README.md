# picoCTF Ansible Roles

An [Ansible collection](https://docs.ansible.com/ansible/latest/user_guide/collections_using.html)
containing various roles for configuring platform components and compatible challenge server
backends. All included roles are designed to be idempotent (i.e. can be repeatedly re-applied
without causing issues).

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
        roles:
          - picoctf.ansible_roles.<role_name>
          - role: picoctf.ansible_roles.<role_name>  # use this syntax to override roles' default variables
            vars:
              sample: "value"
    ```

    Note that all roles in this collection already specify `become: yes` to elevate to root as
    necessary, so you do not need to handle that in your playbook.

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

    Note that the specified SSH user must be able to elevate to root [using
    `become`](https://docs.ansible.com/ansible/latest/user_guide/become.html).
