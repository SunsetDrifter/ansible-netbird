# community.ansible_netbird.export

Capture the current NetBird API state and write it as YAML config files
that the [configure role](../configure/README.md) can consume directly.
Also writes raw API snapshots under `raw/` for debugging.

## Requirements

- Ansible >= 2.15
- Python >= 3.9 on the controller
- A NetBird API token with read access to the resources you intend to export

## Local-only execution

This role calls the NetBird REST API from the controller; it does *not*
connect to managed nodes. Run it against `localhost` (e.g. `hosts: localhost`).
No facts are gathered — the role only needs the controller's date for file
headers, which it computes via Jinja's `strftime` filter.

## Role variables

### Required

| Variable             | Type | Description                                                       |
|----------------------|------|-------------------------------------------------------------------|
| `netbird_api_url`    | str  | Base URL of the NetBird API (e.g. `https://netbird.example.com`). |
| `netbird_api_token`  | str  | Personal access token; passed via `module_defaults` and `no_log`. |

### Optional

| Variable                  | Default                          | Description                                                                                                                              |
|---------------------------|----------------------------------|------------------------------------------------------------------------------------------------------------------------------------------|
| `export_dir`              | `/tmp/netbird_config_export`     | Output directory. Created if missing. Override to a playbook-relative path if file permissions matter on a multi-user host.              |
| `netbird_validate_certs`  | `true`                           | Validate the API server TLS certificate. Set to `false` only against self-signed test environments.                                       |

Inputs are validated by `meta/argument_specs.yml`; a missing required
variable will fail fast before any API calls are made.

## Output layout

```
export_dir/
├── settings.yml                  # account settings
├── networks.yml                  # networks + routers + resources
├── routes.yml                    # routes (deprecated API)
├── setup_keys.yml                # setup keys (read-only reference)
├── access_control/
│   ├── groups.yml
│   ├── posture_checks.yml
│   └── policies.yml
├── dns/
│   ├── nameservers.yml
│   ├── zones.yml
│   └── settings.yml
└── raw/                          # raw API snapshots (for debugging)
    ├── account_settings_raw.yml
    ├── groups_raw.yml
    ├── posture_checks_raw.yml
    ├── setup_keys_raw.yml
    ├── dns_nameservers_raw.yml
    ├── dns_zones_raw.yml
    ├── networks_raw.yml
    ├── routes_raw.yml
    ├── policies_raw.yml
    ├── users_reference.yml
    └── peers_reference.yml
```

> **Security note.** `raw/setup_keys_raw.yml` and `raw/account_settings_raw.yml`
> may contain sensitive material. Treat `export_dir/` as a secret and
> tighten file permissions in your own playbook if running on a shared host.

## Minimal example

```yaml
- hosts: localhost
  gather_facts: false
  tasks:
    - name: Export NetBird config
      ansible.builtin.include_role:
        name: community.ansible_netbird.export
      vars:
        netbird_api_url: "https://netbird.example.com"
        netbird_api_token: "{{ vault_netbird_api_token }}"
        export_dir: "{{ playbook_dir }}/netbird_export"
```

## Round-tripping with `configure`

```yaml
- hosts: localhost
  gather_facts: false
  tasks:
    - name: Snapshot current state
      ansible.builtin.include_role:
        name: community.ansible_netbird.export
      vars:
        export_dir: "{{ playbook_dir }}/netbird_export"
        netbird_api_url: "{{ netbird_api_url }}"
        netbird_api_token: "{{ netbird_api_token }}"

    - name: Preview re-apply (should report 0 changes)
      ansible.builtin.include_role:
        name: community.ansible_netbird.configure
      vars:
        configure_config_dir: "{{ playbook_dir }}/netbird_export"
        netbird_api_url: "{{ netbird_api_url }}"
        netbird_api_token: "{{ netbird_api_token }}"
```
