#!/usr/bin/python
# -*- coding: utf-8 -*-
# Copyright: (c) 2026, Community
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

"""Ansible module for managing NetBird agent-network guardrails."""

from __future__ import absolute_import, division, print_function
__metaclass__ = type

DOCUMENTATION = r'''
---
module: netbird_an_guardrail
short_description: Manage NetBird agent-network guardrails
description:
  - Create, update, and delete agent-network guardrails in NetBird
    (C(/api/agent-network/guardrails)).
  - Guardrails control which AI models agents may use and whether
    prompts are captured, optionally with PII redaction.
  - Guardrails are matched by C(name), which is expected to be unique.
version_added: "1.4.0"
author:
  - Jan Zboril (@RollLikeRollo)
options:
  state:
    description:
      - The desired state of the guardrail.
    type: str
    choices: ['present', 'absent']
    default: present
  guardrail_id:
    description:
      - The unique identifier of the guardrail.
      - Optional; the module otherwise matches by C(name).
    type: str
  name:
    description:
      - Display name of the guardrail. Must be unique.
      - Required when creating a new guardrail. When updating an existing
        guardrail by C(guardrail_id), the current name is reused if omitted.
    type: str
  description:
    description:
      - Optional description of the guardrail.
      - Omit to keep the existing value on update.
    type: str
  checks:
    description:
      - Guardrail configuration containing model allowlist and prompt
        capture settings.
      - Required when creating a new guardrail. When updating, omitting
        a sub-check (e.g. C(prompt_capture)) preserves the existing value.
        To disable a sub-check, include it with C(enabled=false) rather
        than omitting it.
    type: dict
    suboptions:
      model_allowlist:
        description:
          - Controls which AI models agents are permitted to use.
        type: dict
        suboptions:
          enabled:
            description:
              - Whether the model allowlist is enabled.
            type: bool
          models:
            description:
              - List of allowed model IDs.
            type: list
            elements: str
      prompt_capture:
        description:
          - Controls whether agent prompts are captured.
        type: dict
        suboptions:
          enabled:
            description:
              - Whether prompt capture is enabled.
            type: bool
          redact_pii:
            description:
              - Whether to redact personally identifiable information
                from captured prompts.
            type: bool
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
- name: Create a guardrail with model allowlist and prompt capture
  community.ansible_netbird.netbird_an_guardrail:
    api_url: "https://netbird.example.com"
    api_token: "{{ netbird_token }}"
    name: "production-guardrail"
    description: "Restrict models and capture prompts in production"
    checks:
      model_allowlist:
        enabled: true
        models:
          - "gpt-4"
          - "claude-3-opus"
      prompt_capture:
        enabled: true
        redact_pii: true
    state: present

- name: Update a guardrail to add a model to the allowlist
  community.ansible_netbird.netbird_an_guardrail:
    api_url: "https://netbird.example.com"
    api_token: "{{ netbird_token }}"
    name: "production-guardrail"
    checks:
      model_allowlist:
        enabled: true
        models:
          - "gpt-4"
          - "claude-3-opus"
          - "claude-3-sonnet"
    state: present

- name: Disable prompt capture (omitting would preserve it)
  community.ansible_netbird.netbird_an_guardrail:
    api_url: "https://netbird.example.com"
    api_token: "{{ netbird_token }}"
    name: "production-guardrail"
    checks:
      prompt_capture:
        enabled: false
        redact_pii: false
    state: present

- name: Delete a guardrail
  community.ansible_netbird.netbird_an_guardrail:
    api_url: "https://netbird.example.com"
    api_token: "{{ netbird_token }}"
    name: "production-guardrail"
    state: absent
'''

RETURN = r'''
guardrail:
  description: The guardrail object.
  returned: success
  type: dict
'''

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.community.ansible_netbird.plugins.module_utils.netbird_api import (
    NetBirdAPI,
    NetBirdAPIError,
    find_one_by_name,
    netbird_argument_spec
)


def find_guardrail_by_name(api, name):
    """Find a guardrail by name."""
    guardrails, _unused = api.list_an_guardrails()
    return find_one_by_name(api, guardrails, name, 'guardrails')


def build_body(params, current=None):
    """Build the full guardrail payload from module params.

    The API does a full replace on PUT, so any field the caller omits carries
    the current guardrail's value forward instead of being cleared or reset to
    a default.  ``current`` is the existing guardrail, or None on create.
    """
    current = current or {}

    desc = params.get('description')
    body = {
        'name': params.get('name') or current.get('name', ''),
        'description': desc if desc is not None else current.get('description', ''),
    }

    desired_checks = params.get('checks')
    current_checks = current.get('checks') or {}

    if desired_checks is not None:
        checks = {}
        desired_ma = desired_checks.get('model_allowlist')
        current_ma = current_checks.get('model_allowlist') or {}
        if desired_ma is not None:
            ma_enabled = desired_ma.get('enabled')
            ma_models = desired_ma.get('models')
            checks['model_allowlist'] = {
                'enabled': ma_enabled if ma_enabled is not None else current_ma.get('enabled', False),
                'models': ma_models if ma_models is not None else current_ma.get('models', []),
            }
        else:
            checks['model_allowlist'] = current_ma

        desired_pc = desired_checks.get('prompt_capture')
        current_pc = current_checks.get('prompt_capture') or {}
        if desired_pc is not None:
            pc_enabled = desired_pc.get('enabled')
            pc_redact = desired_pc.get('redact_pii')
            checks['prompt_capture'] = {
                'enabled': pc_enabled if pc_enabled is not None else current_pc.get('enabled', False),
                'redact_pii': pc_redact if pc_redact is not None else current_pc.get('redact_pii', False),
            }
        else:
            checks['prompt_capture'] = current_pc

        body['checks'] = checks
    else:
        body['checks'] = current_checks

    return body


def guardrail_needs_update(current, desired):
    """Check whether a guardrail needs to be updated.

    Compares name, description, and checks recursively.  model_allowlist.models
    is compared as a sorted set so ordering does not trigger spurious changes.
    """
    if current.get('name') != desired.get('name'):
        return True
    if (current.get('description') or '') != (desired.get('description') or ''):
        return True

    cur_checks = current.get('checks') or {}
    des_checks = desired.get('checks') or {}

    # model_allowlist
    cur_ma = cur_checks.get('model_allowlist') or {}
    des_ma = des_checks.get('model_allowlist') or {}
    if bool(cur_ma.get('enabled', False)) != bool(des_ma.get('enabled', False)):
        return True
    if sorted(cur_ma.get('models') or []) != sorted(des_ma.get('models') or []):
        return True

    # prompt_capture
    cur_pc = cur_checks.get('prompt_capture') or {}
    des_pc = des_checks.get('prompt_capture') or {}
    if bool(cur_pc.get('enabled', False)) != bool(des_pc.get('enabled', False)):
        return True
    if bool(cur_pc.get('redact_pii', False)) != bool(des_pc.get('redact_pii', False)):
        return True

    return False


def run_module():
    """Main module execution."""
    argument_spec = netbird_argument_spec()
    argument_spec.update(
        state=dict(type='str', choices=['present', 'absent'], default='present'),
        guardrail_id=dict(type='str'),
        name=dict(type='str'),
        description=dict(type='str'),
        checks=dict(type='dict'),
    )

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
        required_one_of=[
            ('guardrail_id', 'name'),
        ],
    )

    api = NetBirdAPI(
        module,
        module.params['api_url'],
        module.params['api_token'],
        module.params['validate_certs'],
        timeout=module.params['timeout'],
    )

    state = module.params['state']
    guardrail_id = module.params['guardrail_id']
    name = module.params['name']

    result = dict(changed=False, guardrail={})

    try:
        # Find existing guardrail
        existing = None
        if guardrail_id:
            try:
                existing, _unused = api.get_an_guardrail(guardrail_id)
            except NetBirdAPIError as e:
                if e.status_code != 404:
                    raise
        elif name:
            existing = find_guardrail_by_name(api, name)

        if state == 'absent':
            if existing:
                if not module.check_mode:
                    api.delete_an_guardrail(existing['id'])
                result['changed'] = True
                result['msg'] = 'Guardrail deleted successfully'
            module.exit_json(**result)

        # state == 'present'
        desired = build_body(module.params, current=existing)

        if existing:
            if guardrail_needs_update(existing, desired):
                if not module.check_mode:
                    updated, _unused = api.update_an_guardrail(
                        existing['id'], desired)
                    result['guardrail'] = updated
                else:
                    result['guardrail'] = existing
                result['changed'] = True
            else:
                result['guardrail'] = existing
        else:
            # Create new guardrail
            if not name:
                module.fail_json(msg="name is required when creating a new guardrail")

            if not module.check_mode:
                created, _unused = api.create_an_guardrail(desired)
                result['guardrail'] = created
            else:
                result['guardrail'] = desired
            result['changed'] = True

        module.exit_json(**result)

    except NetBirdAPIError as e:
        module.fail_json(msg=str(e), status_code=e.status_code, response=e.response)


def main():
    run_module()


if __name__ == '__main__':
    main()
