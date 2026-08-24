#!/usr/bin/python
# -*- coding: utf-8 -*-
# Copyright: (c) 2026, Community
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

"""Ansible module for managing NetBird agent-network settings."""

from __future__ import absolute_import, division, print_function
__metaclass__ = type

DOCUMENTATION = r'''
---
module: netbird_an_settings
short_description: Manage NetBird agent-network settings
description:
  - View and update agent-network settings in NetBird
    (C(/api/agent-network/settings)).
  - Configure log collection, prompt collection, PII redaction,
    and access log retention for the agent network.
  - This is an account-level singleton resource; only C(state=present)
    is supported (no create or delete).
  - On management builds that require bootstrapping, the module issues
    a POST to initialise the settings row when none exists and either
    O(proxy_address) or O(endpoint) is provided.
version_added: "1.4.0"
author:
  - Jan Zboril (@RollLikeRollo)
options:
  state:
    description:
      - The desired state. Only C(present) is supported.
    type: str
    choices: ['present']
    default: present
  proxy_address:
    description:
      - Custom proxy address for bootstrapping agent-network settings.
      - Required (or O(endpoint)) to bootstrap settings on accounts
        that have never been initialised. Ignored after bootstrapping.
    type: str
  endpoint:
    description:
      - Custom endpoint for bootstrapping agent-network settings.
      - Required (or O(proxy_address)) to bootstrap settings on accounts
        that have never been initialised. Read-only after bootstrapping;
        the module echoes the server-assigned value in updates.
    type: str
  enable_log_collection:
    description:
      - Enable or disable agent-network log collection.
    type: bool
  enable_prompt_collection:
    description:
      - Enable or disable agent-network prompt collection.
    type: bool
  redact_pii:
    description:
      - Enable or disable PII redaction in collected data.
    type: bool
  access_log_retention_days:
    description:
      - Number of days to retain access logs.
      - A value of 0 or less means indefinite retention.
    type: int
extends_documentation_fragment:
  - community.ansible_netbird.netbird
attributes:
  check_mode:
    description: Can run in C(check_mode) and predict changes without modifying the target.
    support: full
  diff_mode:
    description: This module does not report a diff of the changes it makes.
    support: none
requirements:
  - python >= 3.9
'''

EXAMPLES = r'''
- name: Enable log and prompt collection
  community.ansible_netbird.netbird_an_settings:
    api_url: "https://netbird.example.com"
    api_token: "{{ netbird_token }}"
    enable_log_collection: true
    enable_prompt_collection: true
    state: present

- name: Enable PII redaction and set log retention
  community.ansible_netbird.netbird_an_settings:
    api_url: "https://netbird.example.com"
    api_token: "{{ netbird_token }}"
    redact_pii: true
    access_log_retention_days: 90
    state: present

- name: Disable all collection features
  community.ansible_netbird.netbird_an_settings:
    api_url: "https://netbird.example.com"
    api_token: "{{ netbird_token }}"
    enable_log_collection: false
    enable_prompt_collection: false
    state: present
'''

RETURN = r'''
settings:
  description: The agent-network settings object.
  returned: success
  type: dict
'''

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.community.ansible_netbird.plugins.module_utils.netbird_api import (
    NetBirdAPI,
    NetBirdAPIError,
    netbird_argument_spec
)


def build_desired_settings(module):
    """Build the desired settings dict from module parameters.

    Only includes fields the user explicitly provided so that
    unspecified fields are left unchanged.
    """
    settings = {}

    param_mapping = {
        'enable_log_collection': 'enable_log_collection',
        'enable_prompt_collection': 'enable_prompt_collection',
        'redact_pii': 'redact_pii',
        'access_log_retention_days': 'access_log_retention_days',
    }

    for param, api_field in param_mapping.items():
        value = module.params.get(param)
        if value is not None:
            settings[api_field] = value

    return settings


def settings_need_update(current_settings, desired_settings):
    """Check if agent-network settings need to be updated."""
    for key, value in desired_settings.items():
        if current_settings.get(key) != value:
            return True
    return False


def run_module():
    """Main module execution."""
    argument_spec = netbird_argument_spec()
    argument_spec.update(
        state=dict(type='str', choices=['present'], default='present'),
        proxy_address=dict(type='str'),
        endpoint=dict(type='str'),
        enable_log_collection=dict(type='bool'),
        enable_prompt_collection=dict(type='bool'),
        redact_pii=dict(type='bool'),
        access_log_retention_days=dict(type='int'),
    )

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
    )

    api = NetBirdAPI(
        module,
        module.params['api_url'],
        module.params['api_token'],
        module.params['validate_certs'],
        timeout=module.params['timeout']
    )

    result = dict(changed=False, settings={})

    try:
        # GET current settings — older builds return null for uninitialized
        # accounts; current builds 404 when not bootstrapped.
        bootstrapped = True
        try:
            current_settings, _unused = api.get('/api/agent-network/settings')
            if current_settings is None:
                current_settings = {}
                bootstrapped = False
        except NetBirdAPIError as e:
            if e.status_code == 404:
                current_settings = {}
                bootstrapped = False
            else:
                raise

        desired_settings = build_desired_settings(module)

        if not bootstrapped:
            bootstrap_data = {}
            if module.params.get('proxy_address'):
                bootstrap_data['proxy_address'] = module.params['proxy_address']
            if module.params.get('endpoint'):
                bootstrap_data['endpoint'] = module.params['endpoint']
            if not bootstrap_data:
                module.fail_json(
                    msg="Agent-network settings have not been bootstrapped. "
                        "Provide proxy_address or endpoint to initialise them.")
            bootstrap_data.update(desired_settings)
            if not module.check_mode:
                created, _unused = api.post(
                    '/api/agent-network/settings', data=bootstrap_data)
                result['settings'] = created
            else:
                result['settings'] = bootstrap_data
            result['changed'] = True
            module.exit_json(**result)

        if desired_settings:
            if settings_need_update(current_settings, desired_settings):
                if not module.check_mode:
                    update_data = {**current_settings, **desired_settings}
                    # Remove read-only timestamps from the PUT body
                    for key in ('subdomain', 'created_at', 'updated_at'):
                        update_data.pop(key, None)
                    # endpoint is immutable — echo the assigned value unchanged
                    if 'endpoint' not in update_data and current_settings.get('endpoint'):
                        update_data['endpoint'] = current_settings['endpoint']
                    updated, _unused = api.put(
                        '/api/agent-network/settings',
                        data=update_data,
                    )
                    result['settings'] = updated
                else:
                    result['settings'] = current_settings
                result['changed'] = True
            else:
                result['settings'] = current_settings
        else:
            result['settings'] = current_settings

        module.exit_json(**result)

    except NetBirdAPIError as e:
        module.fail_json(msg=str(e), status_code=e.status_code, response=e.response)


def main():
    run_module()


if __name__ == '__main__':
    main()
