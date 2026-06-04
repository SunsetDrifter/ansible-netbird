# netbirdio.ansible_netbird.configure

Apply NetBird logical configuration from YAML files via the NetBird REST API.

Manages **account settings**, **groups**, **setup keys**, **posture checks**,
**DNS** (nameserver groups + zones), **networks** (with routers and
resources), and **policies**. By default the role runs in **preview mode**
and only renders a diff report — set `configure_commit: true` to apply changes.

## Requirements

- Ansible >= 2.15
- Python >= 3.9 on the controller
- A NetBird API token with permissions for the resources you intend to manage

## Local-only execution

This role calls the NetBird REST API from the controller; it does *not*
connect to managed nodes. Run it against `localhost` (e.g. `hosts: localhost`)
or any other host that is effectively the controller. The role contains
`delegate_to: localhost` on the filesystem `stat` tasks for defence-in-depth,
but every API call still executes wherever the play targets, so don't aim
this role at a remote inventory host.

## Role variables

### Required

| Variable                  | Type | Description                                                                              |
|---------------------------|------|------------------------------------------------------------------------------------------|
| `configure_config_dir`    | path | Path to the NetBird YAML config directory (see *Expected layout* below).                 |
| `netbird_api_url`         | str  | Base URL of the NetBird API (e.g. `https://netbird.example.com`).                        |
| `netbird_api_token`       | str  | Personal access token; passed via `module_defaults` and marked `no_log`.                 |

### Optional

| Variable                              | Default | Description                                                                                                                             |
|---------------------------------------|---------|-----------------------------------------------------------------------------------------------------------------------------------------|
| `configure_commit`                    | `false` | When `true`, applies changes. When `false`, only renders a preview diff.                                                                 |
| `configure_strict`                    | `false` | When `true` (and `configure_commit: true`), deletes API-only resources not present in YAML.                                              |
| `netbird_validate_certs`              | `true`  | Validate the API server TLS certificate. Set to `false` only against self-signed test environments.                                      |
| `configure_display_setup_key_values`  | `false` | Echo newly-created setup-key values to job output (shown once, cannot be retrieved later). Use only for interactive bootstrap runs.      |

Inputs are validated by `meta/argument_specs.yml`; a missing required
variable will fail fast before any API calls are made.

## Behaviour matrix

| `configure_commit` | `configure_strict` | What the role does                                                                                                                                                                                                                                          |
|--------------------|--------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `false`            | n/a                | **Preview only.** Fetches API state, renders a diff report (`+ Add`, `~ Changed`, `= Unchanged`, `- Remove`, ` - Orphan`). No mutations.                                                                                                                     |
| `true`             | `false`            | **Apply.** Creates/updates YAML-managed resources (idempotent). Resources present in the API but absent from YAML are reported as *orphaned* in earlier preview runs but left untouched.                                                                     |
| `true`             | `true`             | **Apply + reconcile.** Same as above, then deletes API-only resources (policies, networks, DNS nameserver groups, DNS zones, setup keys, posture checks, groups) that are not in YAML. Protected groups (`All`, JWT-issued groups) are never deleted.        |

## Expected `configure_config_dir` layout

```
configure_config_dir/
├── settings.yml                   # account-level settings (optional)
├── networks.yml                   # networks + routers + resources (optional)
├── setup_keys.yml                 # setup keys (optional)
├── access_control/
│   ├── groups.yml                 # groups (optional)
│   ├── posture_checks.yml         # posture checks (optional)
│   └── policies.yml               # policies (optional)
└── dns/
    ├── nameservers.yml            # DNS nameserver groups (optional)
    ├── zones.yml                  # DNS zones + records (optional)
    └── settings.yml               # DNS settings (optional)
```

Use the [export role](../export/README.md) to generate a starter `configure_config_dir`
from a live NetBird instance.

## Minimal example

```yaml
- hosts: localhost
  gather_facts: false
  tasks:
    - name: Preview NetBird config (read-only)
      ansible.builtin.include_role:
        name: netbirdio.ansible_netbird.configure
      vars:
        configure_config_dir: "{{ playbook_dir }}/netbird_config"
        netbird_api_url: "https://netbird.example.com"
        netbird_api_token: "{{ vault_netbird_api_token }}"

    - name: Apply NetBird config
      ansible.builtin.include_role:
        name: netbirdio.ansible_netbird.configure
      vars:
        configure_config_dir: "{{ playbook_dir }}/netbird_config"
        netbird_api_url: "https://netbird.example.com"
        netbird_api_token: "{{ vault_netbird_api_token }}"
        configure_commit: true
```

## Tags

Each phase of the role is tagged so it can be targeted with
`--tags`/`--skip-tags`:

| Tag                          | Covers                                                  |
|------------------------------|---------------------------------------------------------|
| `configure`                  | Everything in this role.                                |
| `configure-validate`         | Pre-flight validation and config loading.               |
| `configure-settings`         | Account settings (`netbird_account`).                   |
| `configure-posture-checks`   | Posture checks (`netbird_posture_check`).               |
| `configure-groups`           | Groups (`netbird_group`).                               |
| `configure-resolve`          | ID/name resolution (fetches + maps + name → ID).        |
| `configure-setup-keys`       | Setup keys (`netbird_setup_key`).                       |
| `configure-dns`              | DNS nameserver groups, settings, zones.                 |
| `configure-networks`         | Networks (`netbird_network`).                           |
| `configure-policies`         | Policies (`netbird_policy`).                            |
| `configure-preview`          | Preview-only fetches + diff report.                     |
| `configure-strict`           | Strict-mode deletions.                                  |

## Notes on `module_defaults`

API auth (`api_url`, `api_token`, `validate_certs`) is set via
`module_defaults` on the block that wraps every API task. This is at
**block level** (not play level) intentionally: ansible-core 2.15 has a
variable-resolution timing issue where play-level `module_defaults`
referencing group_vars with Jinja2 expressions can be resolved before
group_vars are loaded. Block level avoids that.
