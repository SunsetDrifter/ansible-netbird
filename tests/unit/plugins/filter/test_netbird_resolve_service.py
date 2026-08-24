# -*- coding: utf-8 -*-
# Copyright: (c) 2024-2026, NetBird and contributors
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
"""Unit tests for service resolution in netbird_resolve.

Run via:
    ansible-test units --docker default

The export template resolves group IDs to names in both access_groups and
auth.bearer_auth.distribution_groups.  On apply, _resolve_service must turn
those names back to IDs so the API receives valid group references.  Without
this, an export→apply round trip silently replaces stored group IDs with group
names, breaking bearer auth.
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
    'ci-test-access-group': 'da5v832fadhs73aet620',
    'developers': 'grp-dev-001',
}


class TestServiceAccessGroups:

    def test_resolves_names_to_ids(self):
        services = [{'domain': 'app.example.com', 'access_groups': ['developers']}]
        result = netbird_resolve_ids(services, 'service', group_ids=GROUP_IDS)
        assert result[0]['access_groups'] == ['grp-dev-001']

    def test_passes_through_raw_ids(self):
        services = [{'domain': 'app.example.com', 'access_groups': ['grp-dev-001']}]
        result = netbird_resolve_ids(services, 'service', group_ids=GROUP_IDS)
        assert result[0]['access_groups'] == ['grp-dev-001']

    def test_raises_on_unknown_name(self):
        services = [{'domain': 'app.example.com', 'access_groups': ['no-such-group']}]
        with pytest.raises(AnsibleFilterError, match='no-such-group'):
            netbird_resolve_ids(services, 'service', group_ids=GROUP_IDS)


class TestServiceBearerDistributionGroups:

    def test_resolves_names_to_ids(self):
        services = [{
            'domain': 'app.example.com',
            'auth': {'bearer_auth': {
                'enabled': True,
                'distribution_groups': ['ci-test-access-group'],
            }},
        }]
        result = netbird_resolve_ids(services, 'service', group_ids=GROUP_IDS)
        bearer = result[0]['auth']['bearer_auth']
        assert bearer['distribution_groups'] == ['da5v832fadhs73aet620']

    def test_passes_through_raw_ids(self):
        services = [{
            'domain': 'app.example.com',
            'auth': {'bearer_auth': {
                'enabled': True,
                'distribution_groups': ['da5v832fadhs73aet620'],
            }},
        }]
        result = netbird_resolve_ids(services, 'service', group_ids=GROUP_IDS)
        bearer = result[0]['auth']['bearer_auth']
        assert bearer['distribution_groups'] == ['da5v832fadhs73aet620']

    def test_raises_on_unknown_name(self):
        services = [{
            'domain': 'app.example.com',
            'auth': {'bearer_auth': {
                'enabled': True,
                'distribution_groups': ['nonexistent-group'],
            }},
        }]
        with pytest.raises(AnsibleFilterError, match='nonexistent-group'):
            netbird_resolve_ids(services, 'service', group_ids=GROUP_IDS)

    def test_preserves_bearer_enabled_flag(self):
        services = [{
            'domain': 'app.example.com',
            'auth': {'bearer_auth': {
                'enabled': True,
                'distribution_groups': ['developers'],
            }},
        }]
        result = netbird_resolve_ids(services, 'service', group_ids=GROUP_IDS)
        assert result[0]['auth']['bearer_auth']['enabled'] is True

    def test_preserves_other_auth_schemes(self):
        services = [{
            'domain': 'app.example.com',
            'auth': {
                'bearer_auth': {
                    'enabled': True,
                    'distribution_groups': ['developers'],
                },
                'password_auth': {'enabled': True, 'password': 'secret'},
            },
        }]
        result = netbird_resolve_ids(services, 'service', group_ids=GROUP_IDS)
        assert result[0]['auth']['password_auth'] == {'enabled': True, 'password': 'secret'}

    def test_no_auth_key_passes_through(self):
        services = [{'domain': 'app.example.com'}]
        result = netbird_resolve_ids(services, 'service', group_ids=GROUP_IDS)
        assert 'auth' not in result[0]

    def test_auth_without_bearer_passes_through(self):
        services = [{
            'domain': 'app.example.com',
            'auth': {'password_auth': {'enabled': True, 'password': 'pw'}},
        }]
        result = netbird_resolve_ids(services, 'service', group_ids=GROUP_IDS)
        assert 'bearer_auth' not in result[0]['auth']

    def test_bearer_without_distribution_groups_passes_through(self):
        services = [{
            'domain': 'app.example.com',
            'auth': {'bearer_auth': {'enabled': True}},
        }]
        result = netbird_resolve_ids(services, 'service', group_ids=GROUP_IDS)
        assert 'distribution_groups' not in result[0]['auth']['bearer_auth']


class TestServiceMissingRefs:

    def test_collects_unknown_access_group(self):
        services = [{'domain': 'app.example.com', 'access_groups': ['bad-group']}]
        missing = netbird_missing_refs(services, 'service', group_ids=GROUP_IDS)
        assert len(missing) == 1
        assert missing[0]['name'] == 'bad-group'
        assert 'access_groups' in missing[0]['context']

    def test_collects_unknown_bearer_distribution_group(self):
        services = [{
            'domain': 'app.example.com',
            'auth': {'bearer_auth': {
                'enabled': True,
                'distribution_groups': ['bad-bearer-group'],
            }},
        }]
        missing = netbird_missing_refs(services, 'service', group_ids=GROUP_IDS)
        assert len(missing) == 1
        assert missing[0]['name'] == 'bad-bearer-group'
        assert 'bearer_auth' in missing[0]['context']

    def test_collects_from_both_access_and_bearer(self):
        services = [{
            'domain': 'app.example.com',
            'access_groups': ['bad-access'],
            'auth': {'bearer_auth': {
                'enabled': True,
                'distribution_groups': ['bad-bearer'],
            }},
        }]
        missing = netbird_missing_refs(services, 'service', group_ids=GROUP_IDS)
        names = {m['name'] for m in missing}
        assert names == {'bad-access', 'bad-bearer'}

    def test_valid_refs_produce_empty_missing(self):
        services = [{
            'domain': 'app.example.com',
            'access_groups': ['developers'],
            'auth': {'bearer_auth': {
                'enabled': True,
                'distribution_groups': ['ci-test-access-group'],
            }},
        }]
        missing = netbird_missing_refs(services, 'service', group_ids=GROUP_IDS)
        assert missing == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
