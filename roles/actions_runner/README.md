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
