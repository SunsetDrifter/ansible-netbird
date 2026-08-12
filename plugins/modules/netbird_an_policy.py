#!/usr/bin/python
# -*- coding: utf-8 -*-
# Copyright: (c) 2026, Community
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

"""Ansible module for managing NetBird agent-network policies."""

from __future__ import absolute_import, division, print_function
__metaclass__ = type

DOCUMENTATION = r'''
---
module: netbird_an_policy
short_description: Manage NetBird agent-network policies
description:
  - Create, update, and delete agent-network policies via the NetBird API
    (C(/api/agent-network/policies)).
  - An agent-network policy governs which source groups may reach which
    destination providers, with optional guardrails and rate/budget limits.
  - Policies are matched by C(policy_id) or by C(name) (unique lookup).
  - C(source_groups) accepts group names (resolved by the configure role)
    or raw group IDs.
version_added: "1.4.0"
author:
  - Jan Zboril (@RollLikeRollo)
options:
  state:
    description:
      - The desired state of the policy.
    type: str
    choices: ['present', 'absent']
    default: present
  policy_id:
    description:
      - The unique identifier of the policy.
      - Optional; the module otherwise matches by C(name).
    type: str
  name:
    description:
      - Display name of the policy.
      - Required to create a policy. When updating an existing policy by
        C(policy_id), the current name is reused if this is omitted.
    type: str
  description:
    description:
      - Optional description for the policy.
    type: str
  enabled:
    description:
      - Whether the policy is enforced.
      - Defaults to C(true) on create; omit to keep the current value on update.
    type: bool
  source_groups:
    description:
      - List of NetBird group IDs (or names resolved externally) allowed
        to use this policy.
    type: list
    elements: str
  destination_provider_ids:
    description:
      - List of provider IDs accessible through this policy.
    type: list
    elements: str
  guardrail_ids:
    description:
      - List of guardrail IDs attached to this policy.
    type: list
    elements: str
  limits:
    description:
      - Rate and budget limits for the policy.
      - On update, omitting a sub-limit (e.g. C(budget_limit)) preserves
        the existing value instead of clearing it. To disable a sub-limit,
        include it with C(enabled=false) rather than omitting it.
    type: dict
    suboptions:
      token_limit:
        description:
          - Token-based rate limit.
        type: dict
        suboptions:
          enabled:
            description: Whether the token limit is enabled.
            type: bool
            default: false
          group_cap:
            description: Maximum tokens per group within the window.
            type: int
            default: 0
          user_cap:
            description: Maximum tokens per user within the window.
            type: int
            default: 0
          window_seconds:
            description: Rolling window in seconds (minimum 60).
            type: int
            default: 60
      budget_limit:
        description:
          - Budget-based spending limit.
        type: dict
        suboptions:
          enabled:
            description: Whether the budget limit is enabled.
            type: bool
            default: false
          group_cap_usd:
            description: Maximum spend per group in USD within the window.
            type: float
            default: 0
          user_cap_usd:
            description: Maximum spend per user in USD within the window.
            type: float
            default: 0
          window_seconds:
            description: Rolling window in seconds (minimum 60).
            type: int
            default: 60
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
- name: Create an agent-network policy
  community.ansible_netbird.netbird_an_policy:
    api_url: "https://netbird.example.com"
    api_token: "{{ netbird_token }}"
    name: "Default AI policy"
    description: "Allow developers to access OpenAI"
    enabled: true
    source_groups:
      - "developers-group-id"
    destination_provider_ids:
      - "openai-provider-id"
    guardrail_ids:
      - "pii-guardrail-id"
    limits:
      token_limit:
        enabled: true
        group_cap: 100000
        user_cap: 10000
        window_seconds: 3600
      budget_limit:
        enabled: true
        group_cap_usd: 50.0
        user_cap_usd: 5.0
        window_seconds: 3600
    state: present

- name: Disable budget limit on a policy (omitting would preserve it)
  community.ansible_netbird.netbird_an_policy:
    api_url: "https://netbird.example.com"
    api_token: "{{ netbird_token }}"
    name: "Default AI policy"
    limits:
      budget_limit:
        enabled: false
    state: present

- name: Delete an agent-network policy
  community.ansible_netbird.netbird_an_policy:
    api_url: "https://netbird.example.com"
    api_token: "{{ netbird_token }}"
    name: "Default AI policy"
    state: absent
'''

RETURN = r'''
policy:
  description: The agent-network policy object.
  returned: success
  type: dict
'''

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.community.ansible_netbird.plugins.module_utils.netbird_api import (
    NetBirdAPI,
    NetBirdAPIError,
    extract_ids,
    find_one_by_name,
    netbird_argument_spec
)


def find_policy_by_name(api, name):
    """Find an agent-network policy by name."""
    policies, _unused = api.list_an_policies()
    return find_one_by_name(api, policies, name, 'agent-network policies')


def build_limits(limits, current_limits=None):
    """Build the limits payload, carrying forward unset sub-fields.

    Each sub-limit (token_limit, budget_limit) is a flat dict; an omitted
    sub-limit keeps the current value.
    """
    limits = limits or {}
    current_limits = current_limits or {}

    def _sub_limit(key, defaults):
        desired = limits.get(key)
        if desired is not None:
            result = dict(defaults)
            result.update({k: v for k, v in desired.items() if v is not None})
            return result
        if current_limits.get(key) is not None:
            return current_limits[key]
        return dict(defaults)

    return {
        'token_limit': _sub_limit('token_limit', {
            'enabled': False,
            'group_cap': 0,
            'user_cap': 0,
            'window_seconds': 60,
        }),
        'budget_limit': _sub_limit('budget_limit', {
            'enabled': False,
            'group_cap_usd': 0,
            'user_cap_usd': 0,
            'window_seconds': 60,
        }),
    }


def build_body(params, current=None):
    """Build the full policy payload from module params.

    The API does a full replace on PUT, so any field the caller omits carries
    the current policy's value forward instead of being cleared or reset to a
    default.
    """
    current = current or {}

    desc = params.get('description')
    enabled = params.get('enabled')
    body = {
        'name': params.get('name') or current.get('name', ''),
        'description': desc if desc is not None else current.get('description', ''),
        'enabled': enabled if enabled is not None else current.get('enabled', True),
    }

    # List fields: explicit value (incl. []) wins; else carry current forward.
    for field in ('source_groups', 'destination_provider_ids', 'guardrail_ids'):
        if params.get(field) is not None:
            body[field] = params[field]
        elif current.get(field) is not None:
            body[field] = extract_ids(current[field])
        else:
            body[field] = []

    # Limits: merge desired over current.
    if params.get('limits') is not None:
        body['limits'] = build_limits(params['limits'], current.get('limits'))
    elif current.get('limits') is not None:
        body['limits'] = current['limits']

    return body


def limits_differ(current, desired):
    """Compare limits dicts recursively.

    Handles the two-level structure: limits -> token_limit / budget_limit ->
    scalar fields. Returns True if any scalar leaf differs.
    """
    if not desired and not current:
        return False
    if bool(desired) != bool(current):
        return True

    for sub_key in ('token_limit', 'budget_limit'):
        cur_sub = (current or {}).get(sub_key) or {}
        des_sub = (desired or {}).get(sub_key) or {}
        # Compare every key present in either side.
        all_keys = set(cur_sub) | set(des_sub)
        for key in all_keys:
            cur_val = cur_sub.get(key)
            des_val = des_sub.get(key)
            if isinstance(cur_val, bool) or isinstance(des_val, bool):
                if bool(cur_val) != bool(des_val):
                    return True
            elif isinstance(cur_val, (int, float)) or isinstance(des_val, (int, float)):
                # Use numeric comparison to handle int vs float differences.
                if (cur_val or 0) != (des_val or 0):
                    return True
            elif cur_val != des_val:
                return True
    return False


def policy_needs_update(current, desired):
    """Check whether a policy needs to be updated, ignoring computed fields."""
    # Scalar fields.
    for field in ('name', 'description', 'enabled'):
        if current.get(field) != desired.get(field):
            return True

    # List fields compared as sets via extract_ids.
    for field in ('source_groups', 'destination_provider_ids', 'guardrail_ids'):
        cur_ids = set(extract_ids(current.get(field) or []))
        des_ids = set(desired.get(field) or [])
        if cur_ids != des_ids:
            return True

    # Limits (recursive dict compare).
    if 'limits' in desired:
        if limits_differ(current.get('limits'), desired.get('limits')):
            return True

    return False


def run_module():
    """Main module execution."""
    argument_spec = netbird_argument_spec()
    argument_spec.update(
        state=dict(type='str', choices=['present', 'absent'], default='present'),
        policy_id=dict(type='str'),
        name=dict(type='str'),
        description=dict(type='str'),
        enabled=dict(type='bool'),
        source_groups=dict(type='list', elements='str'),
        destination_provider_ids=dict(type='list', elements='str'),
        guardrail_ids=dict(type='list', elements='str'),
        limits=dict(
            type='dict',
            options=dict(
                token_limit=dict(
                    type='dict',
                    no_log=False,
                    options=dict(
                        enabled=dict(type='bool', default=False),
                        group_cap=dict(type='int', default=0),
                        user_cap=dict(type='int', default=0),
                        window_seconds=dict(type='int', default=60),
                    ),
                ),
                budget_limit=dict(
                    type='dict',
                    options=dict(
                        enabled=dict(type='bool', default=False),
                        group_cap_usd=dict(type='float', default=0),
                        user_cap_usd=dict(type='float', default=0),
                        window_seconds=dict(type='int', default=60),
                    ),
                ),
            ),
        ),
    )

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
        required_one_of=[('policy_id', 'name')],
    )

    api = NetBirdAPI(
        module,
        module.params['api_url'],
        module.params['api_token'],
        module.params['validate_certs'],
        timeout=module.params['timeout'],
    )

    state = module.params['state']
    policy_id = module.params['policy_id']
    name = module.params['name']

    result = dict(changed=False, policy={})

    try:
        existing = None
        if policy_id:
            try:
                existing, _unused = api.get_an_policy(policy_id)
            except NetBirdAPIError as e:
                if e.status_code != 404:
                    raise
        elif name:
            existing = find_policy_by_name(api, name)

        if state == 'absent':
            if existing:
                if not module.check_mode:
                    api.delete_an_policy(existing['id'])
                result['changed'] = True
                result['msg'] = 'Policy deleted successfully'
            module.exit_json(**result)

        # state == 'present'
        if not existing and not name:
            module.fail_json(msg='name is required to create a policy')

        desired = build_body(module.params, current=existing)

        if existing:
            if policy_needs_update(existing, desired):
                if not module.check_mode:
                    updated, _unused = api.update_an_policy(
                        existing['id'], desired)
                    result['policy'] = updated
                else:
                    result['policy'] = existing
                result['changed'] = True
            else:
                result['policy'] = existing
        else:
            if not module.check_mode:
                created, _unused = api.create_an_policy(desired)
                result['policy'] = created
            else:
                result['policy'] = desired
            result['changed'] = True

        module.exit_json(**result)

    except NetBirdAPIError as e:
        module.fail_json(msg=str(e), status_code=e.status_code, response=e.response)


def main():
    run_module()


if __name__ == '__main__':
    main()
