#!/usr/bin/python
# -*- coding: utf-8 -*-
# Copyright: (c) 2026, Community
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

"""Ansible module for managing NetBird reverse-proxy custom domains."""

from __future__ import absolute_import, division, print_function
__metaclass__ = type

DOCUMENTATION = r'''
---
module: netbird_service_domain
short_description: Manage NetBird reverse-proxy custom domains
description:
  - Create and delete custom domains for NetBird reverse-proxy services
    (C(/api/reverse-proxies/domains)).
  - Custom domains allow services to be served on your own domain instead
    of a NetBird-provided subdomain.
  - Creating a domain triggers initial DNS validation. Use the
    C(validate) option to re-trigger validation after DNS records are set.
  - Domains are matched by the C(domain) name, which must be unique.
version_added: "1.4.0"
author:
  - Community
options:
  state:
    description:
      - The desired state of the custom domain.
    type: str
    choices: ['present', 'absent']
    default: present
  domain:
    description:
      - The custom domain name (e.g. C(app.example.com)).
      - Required.
    type: str
    required: true
  target_cluster:
    description:
      - The proxy cluster address to associate the domain with
        (e.g. C(eu.proxy.netbird.io)).
      - Required when C(state=present).
      - B(Changing the cluster) on an existing domain triggers a
        delete-and-recreate (no PUT exists). The domain receives a new ID,
        DNS validation is reset, and services bound to the domain may break.
    type: str
  validate:
    description:
      - Whether to trigger the asynchronous domain ownership validation.
      - When the domain already exists and is not yet validated, re-triggers
        validation. Success means "triggered," not "validated." Has no effect
        when C(state=absent) or when
        the domain is already validated.
    type: bool
    default: false
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
- name: Create a custom domain
  community.ansible_netbird.netbird_service_domain:
    api_url: "https://netbird.example.com"
    api_token: "{{ netbird_token }}"
    domain: "app.example.com"
    target_cluster: "eu.proxy.netbird.io"
    state: present

- name: Create and validate a custom domain
  community.ansible_netbird.netbird_service_domain:
    api_url: "https://netbird.example.com"
    api_token: "{{ netbird_token }}"
    domain: "app.example.com"
    target_cluster: "eu.proxy.netbird.io"
    validate: true
    state: present

- name: Delete a custom domain
  community.ansible_netbird.netbird_service_domain:
    api_url: "https://netbird.example.com"
    api_token: "{{ netbird_token }}"
    domain: "app.example.com"
    state: absent

- name: Validate a custom domain
  community.ansible_netbird.netbird_service_domain:
    api_url: "https://netbird.example.com"
    api_token: "{{ netbird_token }}"
    domain: "app.example.com"
    validate: true
    state: present
'''

RETURN = r'''
domain_info:
  description: The custom domain object.
  returned: success
  type: dict
'''

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.community.ansible_netbird.plugins.module_utils.netbird_api import (
    NetBirdAPI,
    NetBirdAPIError,
    netbird_argument_spec
)


def find_domain_by_name(api, domain_name):
    """Find a custom domain by its domain name. Ignore proxy clusters."""
    domains, _unused = api.list_service_domains()
    for domain in (domains or []):
        if domain.get('type') != 'custom':
            continue
        if domain.get('domain') == domain_name:
            return domain
    return None


def run_module():
    """Main module execution."""
    argument_spec = netbird_argument_spec()
    argument_spec.update(
        state=dict(type='str', choices=['present', 'absent'], default='present'),
        domain=dict(type='str', required=True),
        target_cluster=dict(type='str'),
        validate=dict(type='bool', default=False),
    )

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
        required_if=[
            ('state', 'present', ['target_cluster']),
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
    domain_name = module.params['domain']
    target_cluster = module.params['target_cluster']
    do_validate = module.params['validate']

    result = dict(changed=False, domain_info={})

    try:
        existing = find_domain_by_name(api, domain_name)

        if state == 'absent':
            if existing:
                if not module.check_mode:
                    api.delete_service_domain(existing['id'])
                result['changed'] = True
                result['msg'] = 'Custom domain deleted successfully'
            module.exit_json(**result)

        # state == 'present'
        if existing:
            if existing.get('target_cluster') != target_cluster:
                module.warn(
                    f"Changing target_cluster for '{domain_name}' requires "
                    f"delete+recreate: new domain ID, validation reset, "
                    f"and services using this domain may break."
                )
                if not module.check_mode:
                    # Delete the domain before re-creating it
                    api.delete_service_domain(existing['id'])
                    # Try to re-create the domain on the new cluster
                    created = None
                    try:
                        created, _unused = api.create_service_domain({
                            'domain': domain_name,
                            'target_cluster': target_cluster,
                        })
                    # If the re-creation fails, try to rollback to the original cluster
                    except NetBirdAPIError as create_err:
                        rollback = None
                        try:
                            rollback, _unused = api.create_service_domain({
                                'domain': domain_name,
                                'target_cluster': existing.get('target_cluster'),
                            })
                        except NetBirdAPIError:
                            module.fail_json(
                                msg=(
                                    f"Failed to re-create domain '{domain_name}' "
                                    f"on cluster '{target_cluster}' and rollback to "
                                    f"'{existing.get('target_cluster')}' also "
                                    f"failed: {create_err}"
                                )
                            )
                        if do_validate and isinstance(rollback, dict) and rollback.get('id'):
                            api.validate_service_domain(rollback['id'])
                        module.fail_json(
                            msg=(
                                f"Failed to re-create domain '{domain_name}' "
                                f"on cluster '{target_cluster}'; rolled back to "
                                f"'{existing.get('target_cluster')}': {create_err}"
                            ),
                            domain_info=rollback,
                        )
                    if not isinstance(created, dict) or not created.get('id'):
                        module.fail_json(
                            msg=(
                                f"Unexpected response when creating domain "
                                f"'{domain_name}': {created!r}"
                            )
                        )
                    if do_validate:
                        api.validate_service_domain(created['id'])
                    result['domain_info'] = created
                else:
                    result['domain_info'] = existing
                result['changed'] = True
            else:
                if do_validate and not existing.get('validated', False):
                    if not module.check_mode:
                        api.validate_service_domain(existing['id'])
                    result['changed'] = True
                result['domain_info'] = existing

        else:
            if not module.check_mode:
                created, _unused = api.create_service_domain({
                    'domain': domain_name,
                    'target_cluster': target_cluster,
                })
                if do_validate:
                    api.validate_service_domain(created['id'])
                result['domain_info'] = created
            result['changed'] = True

        module.exit_json(**result)

    except NetBirdAPIError as e:
        module.fail_json(msg=str(e), status_code=e.status_code, response=e.response)


def main():
    run_module()


if __name__ == '__main__':
    main()
