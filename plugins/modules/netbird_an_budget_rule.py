#!/usr/bin/python
# -*- coding: utf-8 -*-
# Copyright: (c) 2026, Community
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

"""Ansible module for managing NetBird agent-network budget rules."""

from __future__ import absolute_import, division, print_function
__metaclass__ = type

DOCUMENTATION = r'''
---
module: netbird_an_budget_rule
short_description: Manage NetBird agent-network budget rules
description:
  - Create, update, and delete budget rules for the NetBird agent-network
    feature (C(/api/agent-network/budget-rules)).
  - Budget rules enforce token and cost limits on groups and users
    within the agent network.
  - Rules are matched by C(name) (unique) or C(rule_id).
version_added: "1.4.0"
author:
  - Jan Zboril (@RollLikeRollo)
options:
  state:
    description:
      - The desired state of the budget rule.
    type: str
    choices: ['present', 'absent']
    default: present
  rule_id:
    description:
      - The unique identifier of the budget rule.
      - Use to look up an existing rule by ID instead of by name.
    type: str
  name:
    description:
      - Display name of the budget rule. Must be unique.
      - Required when creating a new rule.
    type: str
  enabled:
    description:
      - Whether the budget rule is enforced.
      - Defaults to C(true) on create; omit to keep the current value on update.
    type: bool
  target_groups:
    description:
      - List of group IDs the rule applies to.
    type: list
    elements: str
  target_users:
    description:
      - List of user IDs the rule applies to.
    type: list
    elements: str
  limits:
    description:
      - Token and budget limit configuration.
      - On update, omitting a sub-limit (e.g. C(budget_limit)) preserves
        the existing value instead of clearing it. To disable a sub-limit,
        include it with C(enabled=false) rather than omitting it.
    type: dict
    suboptions:
      token_limit:
        description:
          - Token-based limit settings.
        type: dict
        suboptions:
          enabled:
            description:
              - Whether the token limit is enforced.
            type: bool
            required: true
          group_cap:
            description:
              - Maximum tokens allowed per group within the window.
            type: int
          user_cap:
            description:
              - Maximum tokens allowed per user within the window.
            type: int
          window_seconds:
            description:
              - Rolling window duration in seconds (minimum 60 when enabled).
            type: int
      budget_limit:
        description:
          - Cost-based limit settings.
        type: dict
        suboptions:
          enabled:
            description:
              - Whether the budget limit is enforced.
            type: bool
            required: true
          group_cap_usd:
            description:
              - Maximum cost in USD allowed per group within the window.
            type: float
          user_cap_usd:
            description:
              - Maximum cost in USD allowed per user within the window.
            type: float
          window_seconds:
            description:
              - Rolling window duration in seconds (minimum 60 when enabled).
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
- name: Create a budget rule with token limits
  community.ansible_netbird.netbird_an_budget_rule:
    api_url: "https://netbird.example.com"
    api_token: "{{ netbird_token }}"
    name: "dev-team-limits"
    enabled: true
    target_groups:
      - "group-id-1"
    target_users:
      - "user-id-1"
    limits:
      token_limit:
        enabled: true
        group_cap: 100000
        user_cap: 10000
        window_seconds: 3600
      budget_limit:
        enabled: false
    state: present

- name: Update only token_limit — budget_limit is preserved
  community.ansible_netbird.netbird_an_budget_rule:
    api_url: "https://netbird.example.com"
    api_token: "{{ netbird_token }}"
    name: "dev-team-limits"
    limits:
      token_limit:
        enabled: true
        group_cap: 200000
        user_cap: 20000
        window_seconds: 3600
    state: present

- name: Disable the budget sub-limit (omitting would preserve it)
  community.ansible_netbird.netbird_an_budget_rule:
    api_url: "https://netbird.example.com"
    api_token: "{{ netbird_token }}"
    name: "dev-team-limits"
    limits:
      budget_limit:
        enabled: false
    state: present

- name: Delete a budget rule by name
  community.ansible_netbird.netbird_an_budget_rule:
    api_url: "https://netbird.example.com"
    api_token: "{{ netbird_token }}"
    name: "dev-team-limits"
    state: absent

- name: Delete a budget rule by ID
  community.ansible_netbird.netbird_an_budget_rule:
    api_url: "https://netbird.example.com"
    api_token: "{{ netbird_token }}"
    rule_id: "rule-id-123"
    state: absent
'''

RETURN = r'''
budget_rule:
  description: The budget rule object.
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


def find_budget_rule_by_name(api, name):
    """Find a budget rule by name."""
    rules, _unused = api.get('/api/agent-network/budget-rules')
    return find_one_by_name(api, rules, name, 'budget rules')


def _build_limits(limits, current_limits=None):
    """Build limits payload, carrying forward omitted sub-limits."""
    limits = limits or {}
    current_limits = current_limits or {}

    def _sub(key, defaults):
        desired = limits.get(key)
        if desired is not None:
            merged = dict(defaults)
            merged.update({k: v for k, v in desired.items() if v is not None})
            return merged
        if current_limits.get(key) is not None:
            return current_limits[key]
        return dict(defaults)

    return {
        'token_limit': _sub('token_limit', {
            'enabled': False, 'group_cap': 0,
            'user_cap': 0, 'window_seconds': 60,
        }),
        'budget_limit': _sub('budget_limit', {
            'enabled': False, 'group_cap_usd': 0,
            'user_cap_usd': 0, 'window_seconds': 60,
        }),
    }


def build_body(params, current=None):
    """Build the full-replace PUT/POST body from module parameters.

    The API does a full replace on PUT, so any field the caller omits
    carries the current value forward instead of being reset.
    """
    current = current or {}
    body = {}

    def _scalar(field, default=None):
        val = params.get(field)
        if val is not None:
            return val
        return current.get(field, default)

    body['name'] = _scalar('name', '')
    if _scalar('enabled') is not None:
        body['enabled'] = _scalar('enabled')

    for field in ('target_groups', 'target_users'):
        if params.get(field) is not None:
            body[field] = params[field]
        elif current.get(field) is not None:
            body[field] = current[field]

    if params.get('limits') is not None:
        body['limits'] = _build_limits(
            params['limits'], current.get('limits'))
    elif current.get('limits') is not None:
        body['limits'] = current['limits']

    return body


def _compare_limits(current, desired):
    """Recursively compare limits dicts, returning True if they differ."""
    if isinstance(desired, dict):
        if not isinstance(current, dict):
            return True
        for key in desired:
            if key not in current:
                return True
            if _compare_limits(current[key], desired[key]):
                return True
        return False
    if isinstance(desired, bool) or isinstance(current, bool):
        return bool(current) != bool(desired)
    if isinstance(desired, (int, float)) and isinstance(current, (int, float)):
        return float(current) != float(desired)
    return current != desired


def budget_rule_needs_update(current, params):
    """Check if a budget rule needs to be updated."""
    if params.get('name') is not None and current.get('name') != params['name']:
        return True
    if params.get('enabled') is not None and current.get('enabled') != params['enabled']:
        return True
    if params.get('target_groups') is not None:
        current_groups = set(extract_ids(current.get('target_groups') or []))
        desired_groups = set(extract_ids(params['target_groups'] or []))
        if current_groups != desired_groups:
            return True
    if params.get('target_users') is not None:
        current_users = set(extract_ids(current.get('target_users') or []))
        desired_users = set(extract_ids(params['target_users'] or []))
        if current_users != desired_users:
            return True
    if params.get('limits') is not None:
        current_limits = current.get('limits') or {}
        if _compare_limits(current_limits, params['limits']):
            return True
    return False


def run_module():
    """Main module execution."""
    argument_spec = netbird_argument_spec()
    argument_spec.update(
        state=dict(type='str', choices=['present', 'absent'], default='present'),
        rule_id=dict(type='str'),
        name=dict(type='str'),
        enabled=dict(type='bool'),
        target_groups=dict(type='list', elements='str'),
        target_users=dict(type='list', elements='str'),
        limits=dict(type='dict', options=dict(
            token_limit=dict(type='dict', options=dict(
                enabled=dict(type='bool', required=True),
                group_cap=dict(type='int'),
                user_cap=dict(type='int'),
                window_seconds=dict(type='int'),
            )),
            budget_limit=dict(type='dict', options=dict(
                enabled=dict(type='bool', required=True),
                group_cap_usd=dict(type='float'),
                user_cap_usd=dict(type='float'),
                window_seconds=dict(type='int'),
            )),
        )),
    )

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
        required_one_of=[
            ('rule_id', 'name'),
        ],
    )

    api = NetBirdAPI(
        module,
        module.params['api_url'],
        module.params['api_token'],
        module.params['validate_certs'],
        timeout=module.params['timeout']
    )

    state = module.params['state']
    rule_id = module.params['rule_id']
    name = module.params['name']

    result = dict(changed=False, budget_rule={})

    try:
        # Find existing budget rule
        existing = None
        if rule_id:
            try:
                existing, _unused = api.get(
                    f'/api/agent-network/budget-rules/{rule_id}'
                )
            except NetBirdAPIError as e:
                if e.status_code != 404:
                    raise
        elif name:
            existing = find_budget_rule_by_name(api, name)

        if state == 'absent':
            if existing:
                if not module.check_mode:
                    api.delete(
                        f'/api/agent-network/budget-rules/{existing["id"]}'
                    )
                result['changed'] = True
                result['msg'] = 'Budget rule deleted successfully'
            module.exit_json(**result)

        # state == 'present'
        if existing:
            update_params = {
                'name': name,
                'enabled': module.params['enabled'],
                'target_groups': module.params['target_groups'],
                'target_users': module.params['target_users'],
                'limits': module.params['limits'],
            }

            if budget_rule_needs_update(existing, update_params):
                if not module.check_mode:
                    body = build_body(update_params, current=existing)
                    updated, _unused = api.put(
                        f'/api/agent-network/budget-rules/{existing["id"]}',
                        data=body,
                    )
                    result['budget_rule'] = updated
                else:
                    result['budget_rule'] = existing
                result['changed'] = True
            else:
                result['budget_rule'] = existing
        else:
            # Create new budget rule
            if not name:
                module.fail_json(
                    msg="name is required when creating a new budget rule"
                )

            if not module.check_mode:
                body = build_body({
                    'name': name,
                    'enabled': module.params['enabled'],
                    'target_groups': module.params['target_groups'],
                    'target_users': module.params['target_users'],
                    'limits': module.params['limits'],
                })
                created, _unused = api.post(
                    '/api/agent-network/budget-rules',
                    data=body,
                )
                result['budget_rule'] = created
            result['changed'] = True

        module.exit_json(**result)

    except NetBirdAPIError as e:
        module.fail_json(msg=str(e), status_code=e.status_code, response=e.response)


def main():
    run_module()


if __name__ == '__main__':
    main()
