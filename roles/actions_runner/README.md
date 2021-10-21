# Actions Runner

## Description

Installs the Github Actions [`self-hosted runner`](https://github.com/actions/runner) on a host and
associates it with a repository.

The host must have outbound open access on port 443 (HTTPS). After configuration, specify `runs-on:
self-hosted` in the repository's workflow files to use the runner.

## Role Variables

| Name | Description | Default |
| --- | --- | --- |
| repo_url | GitHub repo URL to associate with this runner (required). | unset |
| token | Authentication token for this runner (required). Find this under Settings > Actions > Runners > New Self-Hosted Runner. | unset |
| extra_config_options | String of additional options to pass when configuring the runner (e.g. `--name my_runner --work /custom/work_dir`). Run `config.sh --help` from the [runner download](https://github.com/actions/runner/releases) to see all available options. Do not re-specify `--url` or `--token`, as these are set automatically. | unset |
