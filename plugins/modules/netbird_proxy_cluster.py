#!/usr/bin/python
# -*- coding: utf-8 -*-
# Copyright: (c) 2026, Community
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

"""Ansible module for managing NetBird reverse-proxy clusters."""

from __future__ import absolute_import, division, print_function
__metaclass__ = type

DOCUMENTATION = r'''
---
module: netbird_proxy_cluster
short_description: Remove NetBird self-hosted reverse-proxy clusters
description:
  - Delete self-hosted (BYOP) proxy cluster registrations via the
    NetBird API (C(/api/reverse-proxies/clusters)).
  - Proxy clusters are registered automatically by the proxy software;
    only deletion is available through the API, so this module only
    supports C(state=absent).
version_added: "1.4.0"
author:
  - Community
options:
  state:
    description:
      - The desired state. Only C(absent) is supported.
    type: str
    choices: ['absent']
    default: absent
  address:
    description:
      - The cluster address to remove (e.g. C(old.proxy.example.com)).
    type: str
    required: true
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
- name: Remove a self-hosted proxy cluster
  community.ansible_netbird.netbird_proxy_cluster:
    api_url: "https://netbird.example.com"
    api_token: "{{ netbird_token }}"
    address: "old.proxy.example.com"
    state: absent
'''

RETURN = r'''
cluster_info:
  description: Empty dict (the cluster has been removed).
  returned: success
  type: dict
'''

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.community.ansible_netbird.plugins.module_utils.netbird_api import (
    NetBirdAPI,
    NetBirdAPIError,
    netbird_argument_spec
)


def cluster_exists(api, address):
    """Check whether a cluster with the given address is registered."""
    clusters, _unused = api.list_proxy_clusters()
    for cluster in (clusters or []):
        if cluster.get('address') == address:
            return True
    return False


def run_module():
    """Main module execution."""
    argument_spec = netbird_argument_spec()
    argument_spec.update(
        state=dict(type='str', choices=['absent'], default='absent'),
        address=dict(type='str', required=True),
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

    address = module.params['address']
    result = dict(changed=False, cluster_info={})

    try:
        if cluster_exists(api, address):
            if not module.check_mode:
                api.delete_proxy_cluster(address)
            result['changed'] = True
            result['msg'] = 'Proxy cluster removed successfully'

        module.exit_json(**result)

    except NetBirdAPIError as e:
        module.fail_json(msg=str(e), status_code=e.status_code, response=e.response)


def main():
    run_module()


if __name__ == '__main__':
    main()
