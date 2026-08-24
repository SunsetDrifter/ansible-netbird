# -*- coding: utf-8 -*-
# Copyright: (c) 2024-2026, NetBird and contributors
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
"""Unit tests for policy rule resolution in netbird_resolve.

Run via:
    ansible-test units --docker default

A policy rule targets either groups (``sources``/``destinations``) or a
single resource (``source_resource``/``destination_resource``) — the API
rejects a rule that carries both, even when one side is an empty list.
_resolve_policy therefore must not inject ``sources: []`` or
``destinations: []`` into rules that only define the resource form.
"""

from __future__ import absolute_import, division, print_function
__metaclass__ = type

import pytest

from ansible.errors import AnsibleFilterError

from ansible_collections.community.ansible_netbird.plugins.filter.netbird_resolve import (
    netbird_resolve_ids,
    netbird_missing_refs,
)

GROUP_IDS = {
    'All': 'd919v4e0tggg008irqbg',
    'developers': 'grp-dev-001',
}

PEER_IDS = {
    'server-1': 'peer-0001',
}


def resolve_one(policy, **kwargs):
    kwargs.setdefault('group_ids', GROUP_IDS)
    kwargs.setdefault('peer_ids', PEER_IDS)
    return netbird_resolve_ids([policy], 'policy', **kwargs)[0]


class TestResourceTargetedRules:

    def test_destination_resource_rule_gets_no_destinations_key(self):
        policy = {
            'name': 'TUI Traffic',
            'rules': [{
                'name': 'TUI SSH Traffic',
                'sources': ['All'],
                'destination_resource': {'id': 'd9ntt0e0tggg00au8b70', 'type': 'host'},
                'protocol': 'tcp',
                'ports': ['22'],
                'action': 'accept',
            }],
        }
        rule = resolve_one(policy)['rules'][0]
        assert 'destinations' not in rule
        assert rule['sources'] == ['d919v4e0tggg008irqbg']
        assert rule['destination_resource'] == {'id': 'd9ntt0e0tggg00au8b70', 'type': 'host'}

    def test_source_resource_rule_gets_no_sources_key(self):
        policy = {
            'name': 'peer-sourced',
            'rules': [{
                'name': 'r1',
                'source_resource': {'name': 'server-1', 'type': 'peer'},
                'destinations': ['developers'],
                'action': 'accept',
            }],
        }
        rule = resolve_one(policy)['rules'][0]
        assert 'sources' not in rule
        assert rule['source_resource'] == {'id': 'peer-0001', 'type': 'peer'}
        assert rule['destinations'] == ['grp-dev-001']

    def test_non_peer_resource_ref_passes_through(self):
        policy = {
            'name': 'host-target',
            'rules': [{
                'name': 'r1',
                'sources': ['developers'],
                'destination_resource': {'id': 'res-123', 'type': 'domain'},
                'action': 'accept',
            }],
        }
        rule = resolve_one(policy)['rules'][0]
        assert rule['destination_resource'] == {'id': 'res-123', 'type': 'domain'}


class TestGroupTargetedRules:

    def test_group_rules_still_resolve_both_sides(self):
        policy = {
            'name': 'group-to-group',
            'rules': [{
                'name': 'r1',
                'sources': ['All'],
                'destinations': ['developers'],
                'action': 'accept',
            }],
        }
        rule = resolve_one(policy)['rules'][0]
        assert rule['sources'] == ['d919v4e0tggg008irqbg']
        assert rule['destinations'] == ['grp-dev-001']

    def test_unknown_group_name_still_raises(self):
        policy = {
            'name': 'typo',
            'rules': [{'name': 'r1', 'sources': ['no-such-group'], 'destinations': ['All'], 'action': 'accept'}],
        }
        with pytest.raises(AnsibleFilterError):
            netbird_resolve_ids([policy], 'policy', group_ids=GROUP_IDS)

    def test_unknown_group_name_still_collected_by_missing_refs(self):
        policy = {
            'name': 'typo',
            'rules': [{'name': 'r1', 'sources': ['no-such-group'], 'destinations': ['All'], 'action': 'accept'}],
        }
        missing = netbird_missing_refs([policy], 'policy', group_ids=GROUP_IDS)
        assert [m['name'] for m in missing] == ['no-such-group']
