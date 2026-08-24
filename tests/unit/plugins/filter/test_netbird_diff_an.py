# -*- coding: utf-8 -*-
# Copyright: (c) 2024-2026, NetBird and contributors
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
"""Unit tests for agent-network resource diff dispatch.

Run via:
    ansible-test units --docker default

Verifies that all four AN resource types (an_provider, an_policy,
an_guardrail, an_budget_rule) dispatch to their compare functions and
detect real changes, rather than falling through to the empty-diff path.
"""

from __future__ import absolute_import, division, print_function
__metaclass__ = type

from ansible_collections.community.ansible_netbird.plugins.filter.netbird_diff import (
    netbird_diff,
)

GROUP_IDS = {'dev-group': 'grp-dev-001'}
PROVIDER_IDS = {'my-openai': 'prov-abc-123'}
GUARDRAIL_IDS = {'restrict-models': 'guard-xyz-789'}


class TestAnProviderDispatch:

    def test_detects_catalog_provider_change(self):
        current = {'my-provider': {
            'id': 'p-1', 'name': 'my-provider',
            'provider_id': 'openai', 'api_key': 'sealed',
        }}
        desired = [{'name': 'my-provider', 'catalog_provider_id': 'anthropic'}]
        result = netbird_diff(desired, current, 'an_provider')
        assert 'my-provider' in result['changed']

    def test_unchanged_provider_is_ok(self):
        current = {'my-provider': {
            'id': 'p-1', 'name': 'my-provider',
            'provider_id': 'openai',
        }}
        desired = [{'name': 'my-provider', 'catalog_provider_id': 'openai'}]
        result = netbird_diff(desired, current, 'an_provider')
        assert result['changed'] == {}
        assert 'my-provider' in result['unchanged']

    def test_api_key_is_excluded_from_comparison(self):
        current = {'my-provider': {
            'id': 'p-1', 'name': 'my-provider',
            'provider_id': 'openai', 'api_key': 'sealed-value',
        }}
        desired = [{'name': 'my-provider', 'catalog_provider_id': 'openai'}]
        result = netbird_diff(desired, current, 'an_provider')
        assert result['changed'] == {}


class TestAnPolicyDispatch:

    def test_detects_enabled_change(self):
        current = {'my-policy': {
            'id': 'pol-1', 'name': 'my-policy', 'enabled': True,
        }}
        desired = [{'name': 'my-policy', 'enabled': False}]
        result = netbird_diff(desired, current, 'an_policy')
        assert 'my-policy' in result['changed']

    def test_detects_group_change(self):
        current = {'my-policy': {
            'id': 'pol-1', 'name': 'my-policy',
            'source_groups': ['grp-dev-001'],
        }}
        desired = [{'name': 'my-policy', 'source_groups': ['other-group']}]
        result = netbird_diff(desired, current, 'an_policy', group_ids=GROUP_IDS)
        assert 'my-policy' in result['changed']

    def test_resolves_group_names(self):
        current = {'my-policy': {
            'id': 'pol-1', 'name': 'my-policy',
            'source_groups': ['grp-dev-001'],
        }}
        desired = [{'name': 'my-policy', 'source_groups': ['dev-group']}]
        result = netbird_diff(desired, current, 'an_policy', group_ids=GROUP_IDS)
        assert result['changed'] == {}

    def test_resolves_provider_names(self):
        current = {'my-policy': {
            'id': 'pol-1', 'name': 'my-policy',
            'destination_provider_ids': ['prov-abc-123'],
        }}
        desired = [{'name': 'my-policy', 'destination_provider_ids': ['my-openai']}]
        result = netbird_diff(desired, current, 'an_policy',
                              provider_ids=PROVIDER_IDS)
        assert result['changed'] == {}

    def test_resolves_guardrail_names(self):
        current = {'my-policy': {
            'id': 'pol-1', 'name': 'my-policy',
            'guardrail_ids': ['guard-xyz-789'],
        }}
        desired = [{'name': 'my-policy', 'guardrail_ids': ['restrict-models']}]
        result = netbird_diff(desired, current, 'an_policy',
                              guardrail_ids=GUARDRAIL_IDS)
        assert result['changed'] == {}

    def test_detects_provider_change(self):
        current = {'my-policy': {
            'id': 'pol-1', 'name': 'my-policy',
            'destination_provider_ids': ['prov-abc-123'],
        }}
        desired = [{'name': 'my-policy', 'destination_provider_ids': ['other-provider']}]
        result = netbird_diff(desired, current, 'an_policy',
                              provider_ids=PROVIDER_IDS)
        assert 'my-policy' in result['changed']


class TestAnStateSkipped:

    def test_state_in_desired_does_not_diff_for_policy(self):
        current = {'my-policy': {
            'id': 'pol-1', 'name': 'my-policy', 'enabled': True,
        }}
        desired = [{'name': 'my-policy', 'enabled': True, 'state': 'present'}]
        result = netbird_diff(desired, current, 'an_policy')
        assert result['changed'] == {}

    def test_state_in_desired_does_not_diff_for_provider(self):
        current = {'my-provider': {
            'id': 'p-1', 'name': 'my-provider', 'provider_id': 'openai',
        }}
        desired = [{'name': 'my-provider', 'catalog_provider_id': 'openai',
                     'state': 'present'}]
        result = netbird_diff(desired, current, 'an_provider')
        assert result['changed'] == {}


class TestAnGuardrailDispatch:

    def test_detects_change(self):
        current = {'my-guardrail': {
            'id': 'gr-1', 'name': 'my-guardrail', 'enabled': True,
        }}
        desired = [{'name': 'my-guardrail', 'enabled': False}]
        result = netbird_diff(desired, current, 'an_guardrail')
        assert 'my-guardrail' in result['changed']


class TestAnBudgetRuleDispatch:

    def test_detects_change(self):
        current = {'my-rule': {
            'id': 'br-1', 'name': 'my-rule', 'enabled': True,
        }}
        desired = [{'name': 'my-rule', 'enabled': False}]
        result = netbird_diff(desired, current, 'an_budget_rule')
        assert 'my-rule' in result['changed']

    def test_unchanged_is_ok(self):
        current = {'my-rule': {
            'id': 'br-1', 'name': 'my-rule', 'enabled': True,
        }}
        desired = [{'name': 'my-rule', 'enabled': True}]
        result = netbird_diff(desired, current, 'an_budget_rule')
        assert result['changed'] == {}
        assert 'my-rule' in result['unchanged']


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
