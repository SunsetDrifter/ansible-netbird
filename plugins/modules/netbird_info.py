#!/usr/bin/python
# -*- coding: utf-8 -*-
# Copyright: (c) 2024, Community
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

"""Ansible module for gathering NetBird information."""

from __future__ import absolute_import, division, print_function
__metaclass__ = type

DOCUMENTATION = r'''
---
module: netbird_info
short_description: Gather information about NetBird resources
description:
  - Gather information about various NetBird resources.
  - Useful for dynamic inventory or gathering facts.
version_added: "1.0.0"
author:
  - NetBird (@netbirdio)
options:
  resource:
    description:
      - Type of resource to gather information about.
      - Most resources return a list. Singleton resources (C(accounts),
        C(current_user), C(dns_settings), C(an_settings)) return a dict.
      - C(an_access_logs) and C(an_access_log_sessions) are B(paginated)
        by the server (max 100 per page). The returned C(data) is the raw
        API response envelope containing C(data) (the entries), C(page),
        C(page_size), C(total_records), and C(total_pages). Only the
        first page is returned; loop with increasing page numbers in your
        playbook to fetch all pages.
    type: str
    choices: ['accounts', 'users', 'peers', 'groups', 'setup_keys', 'policies',
              'networks', 'routes', 'dns_nameservers', 'dns_zones',
              'dns_settings', 'posture_checks', 'events', 'countries',
              'current_user', 'identity_providers', 'invites',
              'services', 'service_domains', 'proxy_clusters',
              'an_settings', 'an_providers', 'an_catalog_providers',
              'an_policies', 'an_guardrails', 'an_budget_rules',
              'an_access_logs', 'an_access_log_sessions',
              'an_usage_overview', 'an_consumption']
    required: true
  service_user:
    description:
      - Filter users by service user type.
      - Only applicable when resource is 'users'.
    type: bool
  country_code:
    description:
      - Country code for listing cities.
      - Only applicable when resource is 'cities'.
    type: str
  page:
    description:
      - Page number for paginated resources (1-indexed).
      - Only applicable to C(an_access_logs) and C(an_access_log_sessions).
      - Omit to fetch the first page.
    type: int
  page_size:
    description:
      - Number of items per page (max 100).
      - Only applicable to C(an_access_logs) and C(an_access_log_sessions).
      - Omit to use the server default.
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
- name: Get all peers
  community.ansible_netbird.netbird_info:
    api_url: "https://netbird.example.com"
    api_token: "{{ netbird_token }}"
    resource: peers
  register: peers_info

- name: Get all groups
  community.ansible_netbird.netbird_info:
    api_url: "https://netbird.example.com"
    api_token: "{{ netbird_token }}"
    resource: groups
  register: groups_info

- name: Get all service users
  community.ansible_netbird.netbird_info:
    api_url: "https://netbird.example.com"
    api_token: "{{ netbird_token }}"
    resource: users
    service_user: true
  register: service_users_info

- name: Get current user info
  community.ansible_netbird.netbird_info:
    api_url: "https://netbird.example.com"
    api_token: "{{ netbird_token }}"
    resource: current_user
  register: current_user_info

- name: Get all policies
  community.ansible_netbird.netbird_info:
    api_url: "https://netbird.example.com"
    api_token: "{{ netbird_token }}"
    resource: policies
  register: policies_info

- name: Get DNS settings
  community.ansible_netbird.netbird_info:
    api_url: "https://netbird.example.com"
    api_token: "{{ netbird_token }}"
    resource: dns_settings
  register: dns_settings

- name: Get all events
  community.ansible_netbird.netbird_info:
    api_url: "https://netbird.example.com"
    api_token: "{{ netbird_token }}"
    resource: events
  register: events_info

- name: Get available countries for geo-location
  community.ansible_netbird.netbird_info:
    api_url: "https://netbird.example.com"
    api_token: "{{ netbird_token }}"
    resource: countries
  register: countries_info

- name: List agent-network providers
  community.ansible_netbird.netbird_info:
    api_url: "https://netbird.example.com"
    api_token: "{{ netbird_token }}"
    resource: an_providers
  register: an_providers_info

- name: Get agent-network access logs (paginated — first page)
  community.ansible_netbird.netbird_info:
    api_url: "https://netbird.example.com"
    api_token: "{{ netbird_token }}"
    resource: an_access_logs
  register: access_logs
  # access_logs.data is an envelope dict:
  #   access_logs.data.data       — list of log entries (first page)
  #   access_logs.data.page       — current page number
  #   access_logs.data.total_records — total entry count
  #   access_logs.data.total_pages   — calculated page count

- name: Get agent-network usage overview
  community.ansible_netbird.netbird_info:
    api_url: "https://netbird.example.com"
    api_token: "{{ netbird_token }}"
    resource: an_usage_overview
  register: usage_info
'''

RETURN = r'''
data:
  description: The requested information.
  returned: success
  type: raw
  sample:
    - id: "peer-123"
      name: "my-server"
      ip: "100.64.0.1"
count:
  description: Number of items returned (for list resources).
  returned: success
  type: int
  sample: 5
'''

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.community.ansible_netbird.plugins.module_utils.netbird_api import (
    NetBirdAPI,
    NetBirdAPIError,
    netbird_argument_spec
)


def run_module():
    """Main module execution."""
    argument_spec = netbird_argument_spec()
    argument_spec.update(
        resource=dict(
            type='str',
            required=True,
            choices=['accounts', 'users', 'peers', 'groups', 'setup_keys',
                     'policies', 'networks', 'routes', 'dns_nameservers',
                     'dns_zones', 'dns_settings', 'posture_checks', 'events',
                     'countries', 'current_user', 'identity_providers', 'invites',
                     'services', 'service_domains', 'proxy_clusters',
                     'an_settings', 'an_providers', 'an_catalog_providers',
                     'an_policies', 'an_guardrails', 'an_budget_rules',
                     'an_access_logs', 'an_access_log_sessions',
                     'an_usage_overview', 'an_consumption']
        ),
        service_user=dict(type='bool'),
        country_code=dict(type='str'),
        page=dict(type='int'),
        page_size=dict(type='int'),
    )

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True
    )

    api = NetBirdAPI(
        module,
        module.params['api_url'],
        module.params['api_token'],
        module.params['validate_certs'],
        timeout=module.params['timeout']
    )

    resource = module.params['resource']

    def _page_params():
        """Build pagination params from non-null module values."""
        params = {}
        if module.params.get('page') is not None:
            params['page'] = module.params['page']
        if module.params.get('page_size') is not None:
            params['page_size'] = module.params['page_size']
        return params or None

    result = dict(
        changed=False,
        data=None
    )

    try:
        # Map resource types to API methods
        if resource == 'accounts':
            data, _unused = api.list_accounts()
        elif resource == 'users':
            service_user = module.params.get('service_user')
            data, _unused = api.list_users(service_user=service_user)
        elif resource == 'current_user':
            data, _unused = api.get_current_user()
        elif resource == 'peers':
            data, _unused = api.list_peers()
        elif resource == 'groups':
            data, _unused = api.list_groups()
        elif resource == 'setup_keys':
            data, _unused = api.list_setup_keys()
        elif resource == 'policies':
            data, _unused = api.list_policies()
        elif resource == 'networks':
            data, _unused = api.list_networks()
        elif resource == 'routes':
            data, _unused = api.list_routes()
        elif resource == 'dns_nameservers':
            data, _unused = api.list_nameserver_groups()
        elif resource == 'dns_zones':
            data, _unused = api.list_dns_zones()
        elif resource == 'dns_settings':
            data, _unused = api.get_dns_settings()
        elif resource == 'posture_checks':
            data, _unused = api.list_posture_checks()
        elif resource == 'events':
            data, _unused = api.list_events()
        elif resource == 'countries':
            data, _unused = api.list_countries()
        elif resource == 'identity_providers':
            data, _unused = api.list_identity_providers()
        elif resource == 'invites':
            data, _unused = api.list_user_invites()
        elif resource == 'services':
            data, _unused = api.list_services()
        elif resource == 'service_domains':
            data, _unused = api.list_service_domains()
        elif resource == 'proxy_clusters':
            data, _unused = api.list_proxy_clusters()
        elif resource == 'an_settings':
            data, _unused = api.get_an_settings()
        elif resource == 'an_providers':
            data, _unused = api.list_an_providers()
        elif resource == 'an_catalog_providers':
            data, _unused = api.list_an_catalog_providers()
        elif resource == 'an_policies':
            data, _unused = api.list_an_policies()
        elif resource == 'an_guardrails':
            data, _unused = api.list_an_guardrails()
        elif resource == 'an_budget_rules':
            data, _unused = api.list_an_budget_rules()
        elif resource == 'an_access_logs':
            data, _unused = api.list_an_access_logs(params=_page_params())
        elif resource == 'an_access_log_sessions':
            data, _unused = api.list_an_access_log_sessions(params=_page_params())
        elif resource == 'an_usage_overview':
            data, _unused = api.get_an_usage_overview()
        elif resource == 'an_consumption':
            data, _unused = api.get_an_consumption()
        else:
            module.fail_json(msg=f"Unknown resource type: {resource}")

        result['data'] = data

        # Add count for list resources
        if isinstance(data, list):
            result['count'] = len(data)

        module.exit_json(**result)

    except NetBirdAPIError as e:
        module.fail_json(msg=str(e), status_code=e.status_code, response=e.response)


def main():
    run_module()


if __name__ == '__main__':
    main()
