#!/usr/bin/python
# -*- coding: utf-8 -*-
# Copyright: (c) 2026, Community
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

"""Ansible module for managing NetBird agent-network AI providers."""

from __future__ import absolute_import, division, print_function
__metaclass__ = type

DOCUMENTATION = r'''
---
module: netbird_an_provider
short_description: Manage NetBird agent-network AI providers
description:
  - Create, update, and delete agent-network AI providers
    (C(/api/agent-network/providers)).
  - Providers configure upstream LLM API endpoints (OpenAI, Anthropic,
    Azure OpenAI, Bedrock, Vertex AI, Mistral, or custom) with per-model
    pricing and identity header injection.
  - Providers are matched by C(name), which is treated as unique.
version_added: "1.4.0"
author:
  - Jan Zboril (@RollLikeRollo)
options:
  state:
    description:
      - The desired state of the provider.
    type: str
    choices: ['present', 'absent']
    default: present
  provider_id:
    description:
      - The unique identifier of the provider (server-assigned, e.g. C(ainp_...)).
      - Optional; the module otherwise matches by C(name).
    type: str
  name:
    description:
      - Display name of the provider. Must be unique.
      - Required to create a provider.
    type: str
  catalog_provider_id:
    description:
      - Catalog provider type (e.g. C(openai_api), C(anthropic_api),
        C(azure_openai_api), C(bedrock_api), C(vertex_ai_api),
        C(mistral_api), C(custom)).
      - Required to create a provider. Immutable after creation.
    type: str
  upstream_url:
    description:
      - Full upstream URL with scheme (e.g. C(https://api.openai.com/v1)).
    type: str
  api_key:
    description:
      - Upstream API key. Sealed at rest and never returned by the API,
        so changes cannot be detected. Providing it on an existing
        provider always sends an update carrying the key and reports
        C(changed) -- omit it after creation to keep runs idempotent.
      - Required on create, optional on update.
    type: str
  models:
    description:
      - Operator-configured models with pricing information.
    type: list
    elements: dict
    suboptions:
      id:
        description:
          - Model identifier (e.g. C(gpt-4o), C(claude-sonnet-4-20250514)).
        type: str
        required: true
      input_per_1k:
        description:
          - Cost per 1K input tokens in USD.
        type: float
        required: true
      output_per_1k:
        description:
          - Cost per 1K output tokens in USD.
        type: float
        required: true
      cached_input_per_1k:
        description:
          - Cost per 1K cached input tokens in USD.
        type: float
      cache_read_per_1k:
        description:
          - Cost per 1K cache-read tokens in USD.
        type: float
      cache_creation_per_1k:
        description:
          - Cost per 1K cache-creation tokens in USD.
        type: float
  extra_values:
    description:
      - Operator-supplied extra header values passed to the upstream.
    type: dict
  identity_header_user_id:
    description:
      - Wire header name for user identity injection. Empty string disables.
    type: str
  identity_header_groups:
    description:
      - Wire header name for groups CSV injection. Empty string disables.
    type: str
  enabled:
    description:
      - Whether the provider is enabled.
      - Defaults to C(true) on create; omit to keep the current value on update.
    type: bool
  skip_tls_verification:
    description:
      - Skip upstream TLS certificate verification.
      - Defaults to C(false) on create; omit to keep the current value on update.
    type: bool
  metadata_disabled:
    description:
      - Disable identity metadata injection into upstream requests.
      - Defaults to C(false) on create; omit to keep the current value on update.
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
- name: Create an OpenAI provider
  community.ansible_netbird.netbird_an_provider:
    api_url: "https://netbird.example.com"
    api_token: "{{ netbird_token }}"
    name: "OpenAI Production"
    catalog_provider_id: openai_api
    upstream_url: "https://api.openai.com/v1"
    api_key: "{{ openai_api_key }}"
    models:
      - id: gpt-4o
        input_per_1k: 0.0025
        output_per_1k: 0.01
    enabled: true
    state: present

- name: Create an Anthropic provider with caching costs
  community.ansible_netbird.netbird_an_provider:
    api_url: "https://netbird.example.com"
    api_token: "{{ netbird_token }}"
    name: "Anthropic"
    catalog_provider_id: anthropic_api
    upstream_url: "https://api.anthropic.com"
    api_key: "{{ anthropic_api_key }}"
    models:
      - id: claude-sonnet-4-20250514
        input_per_1k: 0.003
        output_per_1k: 0.015
        cached_input_per_1k: 0.00375
        cache_read_per_1k: 0.0003
        cache_creation_per_1k: 0.00375
    state: present

- name: Delete a provider
  community.ansible_netbird.netbird_an_provider:
    api_url: "https://netbird.example.com"
    api_token: "{{ netbird_token }}"
    name: "OpenAI Production"
    state: absent
'''

RETURN = r'''
provider:
  description: The agent-network AI provider object.
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


def normalize_model(model):
    """Normalize a model dict for comparison, keeping only comparable fields."""
    normalized = {
        'id': model['id'],
        'input_per_1k': model.get('input_per_1k', 0),
        'output_per_1k': model.get('output_per_1k', 0),
    }
    for field in ('cached_input_per_1k', 'cache_read_per_1k', 'cache_creation_per_1k'):
        if model.get(field) is not None:
            normalized[field] = model[field]
    return normalized


def models_differ(current, desired):
    """Compare model lists, sorted by model id."""
    cur = sorted(
        [normalize_model(m) for m in (current or [])],
        key=lambda m: m['id'],
    )
    des = sorted(
        [normalize_model(m) for m in (desired or [])],
        key=lambda m: m['id'],
    )
    return cur != des


def provider_needs_update(current, desired):
    """Check whether a provider needs to be updated, ignoring computed fields.

    Skips: id, api_key (never returned), created_at, updated_at,
    provider_id (catalog type, immutable after create).
    """
    for field in ('name', 'upstream_url'):
        if current.get(field) != desired.get(field):
            return True

    for field in ('enabled', 'skip_tls_verification', 'metadata_disabled'):
        if bool(current.get(field)) != bool(desired.get(field)):
            return True

    for field in ('identity_header_user_id', 'identity_header_groups'):
        if (current.get(field) or '') != (desired.get(field) or ''):
            return True

    if (current.get('extra_values') or {}) != (desired.get('extra_values') or {}):
        return True

    if models_differ(current.get('models'), desired.get('models')):
        return True

    return False


def build_body(params, current=None):
    """Build the full provider payload from module params.

    The API does a full replace on PUT, so any field the caller omits
    carries the current provider's value forward.
    """
    current = current or {}

    body = {
        'name': params.get('name') or current.get('name'),
        'provider_id': params.get('catalog_provider_id') or current.get('provider_id'),
        'upstream_url': params.get('upstream_url') or current.get('upstream_url', ''),
        'enabled': (
            params['enabled']
            if params.get('enabled') is not None
            else current.get('enabled', True)
        ),
        'skip_tls_verification': (
            params['skip_tls_verification']
            if params.get('skip_tls_verification') is not None
            else current.get('skip_tls_verification', False)
        ),
        'metadata_disabled': (
            params['metadata_disabled']
            if params.get('metadata_disabled') is not None
            else current.get('metadata_disabled', False)
        ),
        'identity_header_user_id': (
            params['identity_header_user_id']
            if params.get('identity_header_user_id') is not None
            else current.get('identity_header_user_id', '')
        ),
        'identity_header_groups': (
            params['identity_header_groups']
            if params.get('identity_header_groups') is not None
            else current.get('identity_header_groups', '')
        ),
    }

    # models
    if params.get('models') is not None:
        body['models'] = params['models']
    elif current.get('models') is not None:
        body['models'] = current['models']
    else:
        body['models'] = []

    # extra_values
    if params.get('extra_values') is not None:
        body['extra_values'] = params['extra_values']
    elif current.get('extra_values') is not None:
        body['extra_values'] = current['extra_values']
    else:
        body['extra_values'] = {}

    # api_key -- include only when provided; the API never returns it,
    # so we cannot carry forward from current.
    if params.get('api_key'):
        body['api_key'] = params['api_key']

    return body


def run_module():
    """Main module execution."""
    argument_spec = netbird_argument_spec()
    argument_spec.update(
        state=dict(type='str', choices=['present', 'absent'], default='present'),
        provider_id=dict(type='str'),
        name=dict(type='str'),
        catalog_provider_id=dict(type='str'),
        upstream_url=dict(type='str'),
        api_key=dict(type='str', no_log=True),
        models=dict(
            type='list',
            elements='dict',
            options=dict(
                id=dict(type='str', required=True),
                input_per_1k=dict(type='float', required=True),
                output_per_1k=dict(type='float', required=True),
                cached_input_per_1k=dict(type='float'),
                cache_read_per_1k=dict(type='float'),
                cache_creation_per_1k=dict(type='float'),
            ),
        ),
        extra_values=dict(type='dict'),
        identity_header_user_id=dict(type='str'),
        identity_header_groups=dict(type='str'),
        enabled=dict(type='bool'),
        skip_tls_verification=dict(type='bool'),
        metadata_disabled=dict(type='bool'),
    )

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
        required_one_of=[('provider_id', 'name')],
    )

    api = NetBirdAPI(
        module,
        module.params['api_url'],
        module.params['api_token'],
        module.params['validate_certs'],
        timeout=module.params['timeout'],
    )

    state = module.params['state']
    provider_id = module.params['provider_id']
    name = module.params['name']

    result = dict(changed=False, provider={})

    try:
        existing = None
        if provider_id:
            try:
                existing, _unused = api.get_an_provider(provider_id)
            except NetBirdAPIError as e:
                if e.status_code != 404:
                    raise
        elif name:
            providers, _unused = api.list_an_providers()
            existing = find_one_by_name(api, providers, name, 'providers')

        if state == 'absent':
            if existing:
                if not module.check_mode:
                    api.delete_an_provider(existing['id'])
                result['changed'] = True
                result['msg'] = 'Provider deleted successfully'
            module.exit_json(**result)

        # state == 'present'
        if not existing and not name:
            module.fail_json(msg='name is required to create a provider')

        desired = build_body(module.params, current=existing)

        if existing:
            # api_key is sealed by the API and never returned, so the
            # comparator cannot see it: a provided key must force the
            # update or rotation silently no-ops.
            if (provider_needs_update(existing, desired)
                    or module.params.get('api_key')):
                if not module.check_mode:
                    updated, _unused = api.update_an_provider(
                        existing['id'], desired,
                    )
                    result['provider'] = updated
                else:
                    result['provider'] = existing
                result['changed'] = True
            else:
                result['provider'] = existing
        else:
            if not module.params.get('api_key'):
                module.fail_json(msg='api_key is required to create a provider')
            if not module.params.get('catalog_provider_id'):
                module.fail_json(
                    msg='catalog_provider_id is required to create a provider',
                )
            if not module.check_mode:
                created, _unused = api.create_an_provider(desired)
                result['provider'] = created
            else:
                result['provider'] = desired
            result['changed'] = True

        module.exit_json(**result)

    except NetBirdAPIError as e:
        module.fail_json(
            msg=str(e), status_code=e.status_code, response=e.response,
        )


def main():
    run_module()


if __name__ == '__main__':
    main()
