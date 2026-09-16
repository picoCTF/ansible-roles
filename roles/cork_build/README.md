# cork_build

Configures a host as cork's **build plane**: the one machine that holds the challenge
tree, builds and pushes every image, hands the finished builds to the orchestrators, and
publishes their artifact bundles.

This is a thin profile over the [`cork`](../cork/README.md) role rather than a second copy
of it — the same relationship [`docker_builder`](../docker_builder/README.md) has with
`docker`. It includes that role with the half of it a build plane runs.

## What a build plane is

One per deployment, and the control point for every schema operation. Everything flows one
way: the operator acts here, this host pushes images to the shared registry and hands
builds to an orchestrator over `PUT /challenges/<id>`, and the orchestrator's workers pull
and serve. Nothing reports back, which is why each side checks rather than asks — the
orchestrator recomputes every identity it is handed and looks every tag up in the registry
rather than trusting what sent them.

What it does **not** do is run anything. Every schema is converged here with its builds on
demand, which launches no instance, and the instance count a schema really asks for travels
in the hand-over for the orchestrator to converge to.

See [BUILDER.md](https://github.com/CyLabAcademy/challenge-orchestrator/blob/main/BUILDER.md)
for the operator's side of this: which command means what, why a schema may only be served
by one orchestrator, and what recovering a lost plane database takes.

## What it changes

| Setting (`cork` role name) | `cork` default | Here | Why |
|---|---|---|---|
| `cork_daemon_enabled` | yes | **no** | Nothing is served here, so there is no `corkd` and no unit. |
| `cork_builder_enabled` | no | **yes** | `cork-build`, and the wrapper carrying its environment. |
| `artifact_server_enabled` | derived | **yes** | Bundles are written here and published from here; cork itself serves no artifacts. |
| `cork_deploy_docker_certs` | derived | **no** | The docker-ca set authenticates cork to the worker daemons. This host drives none — it hands builds to an orchestrator, which does. It gets the zot set only. |

Override through the `cork_build_*` variables in `defaults/main.yml`, never through the
`cork`-role names in the left column: the profile passes those at include scope, which
beats anything set in group_vars, host_vars or play vars. See the precedence traps in
`tasks/main.yml` — they are the same two `docker_builder` documents, and both are silent.

It also installs **git and git-lfs**, because the tree here is a checkout and its artifacts
are LFS objects: a clone that pulls no LFS content builds successfully and produces
challenges whose downloads are 130-byte pointer files.

| Name | Description | Default |
| --- | --- | --- |
| cork_build_daemon_enabled | Run `corkd` here as well. | `no` |
| cork_build_builder_enabled | Install `cork-build` and its wrapper. | `yes` |
| cork_build_artifact_server_enabled | Run `cmgr-artifact-server` here. | `yes` |
| cork_build_deploy_docker_certs | Deploy the docker-ca client set. | `no` |
| cork_build_install_git | Install git and git-lfs. | `yes` |

## What it does not do

**Clone the challenge repository.** That repository is private, its credentials are not
ansible's to hold, and which revision is deployed is a deploy decision rather than a
provisioning one. This role creates `cork_dir` and leaves the checkout to whatever puts
the revision there.

**Build anything.** `cork-build` is a command an operator or a deploy job runs; this role
only makes running it possible.

## Two things to know before operating one

**The database is not disposable.** An orchestrator records each build under the id this
plane gave it, because that is the id the artifact bundle is named by. A plane re-derived
from an empty database draws new ids, and its hand-over is then refused. Keep `cork_db`
for as long as any schema it built is being served, and back up the volume it is on.

**The artifact server must be v3.0.0 or newer.** A plane writes one subdirectory per
destination, and only v3 treats those as namespaces. Older versions ignore every
subdirectory and publish nothing, silently. The `cork` role asserts this floor on a build
plane; note that `artifact_server_version: latest` only installs when the binary is absent,
so an already-provisioned host needs one pass with `artifact_server_upgrade: yes`.

## Usage

```yaml
- hosts: build_plane
  become: yes
  tasks:
    - include_role:
        name: picoctf.ansible_roles.docker_builder
      vars:
        storage_device: /dev/disk/by-id/nvme-Amazon_Elastic_Block_Store_vol0...
    - include_role:
        name: picoctf.ansible_roles.cork_build
      vars:
        cork_registry: "registry.example.internal:5000"
        cork_cert_src: "{{ playbook_dir }}/docker-certs"
        cork_dir: /mnt/data/cork/challenges
        cork_db: /mnt/data/cork/cork.db
        cork_artifact_dir: /mnt/data/cork/artifacts
        cork_destinations:
          c_library: "http://orchestrator.example.internal:4200"
        artifact_server_backend: s3
        artifact_server_other_options: "-o bucket=... -o cloudfront-distribution=... --salt ..."
```

Then, on the plane:

```shell
$ cork-build build library.yaml          # builds, pushes, hands over, converges
$ cork-build list-schemas
$ cork-build remove-schema <name>        # a NAME, not a file
```
