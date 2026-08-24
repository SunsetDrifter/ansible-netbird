# -*- coding: utf-8 -*-
# Copyright: (c) 2024-2026, NetBird and contributors
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
"""Unit tests for service preview diff accuracy.

Run via:
    ansible-test units --docker default

Three shape mismatches between the exported YAML and what _compare_service
reads from the API made the preview flag every service as CHANGED on a
freshly exported config:

1. access_groups / distribution_groups: names vs IDs — the export writes
   group names, but the API returns IDs. Without resolution, every service
   with groups shows drift.
2. targets: the export flattens options.direct_upstream etc. to top-level
   target keys, while the API returns them in a nested options dict.
3. auth: the declared-keys filter is top-level only, so an exported
   bearer-only auth reports password_auth and pin_auth as removed.

_compare_service is pure; no request is made.
"""

from __future__ import absolute_import, division, print_function
__metaclass__ = type

import pytest

from ansible_collections.community.ansible_netbird.plugins.filter.netbird_diff import (
    netbird_diff,
    _compare_service,
)

GROUP_IDS = {
    'ci-test-group': 'grp-abc-123',
    'developers': 'grp-dev-001',
}


def api_service(**overrides):
    """A service as the API returns it."""
    base = {
        'id': 'svc-1',
        'domain': 'app.example.com',
        'name': 'app.example.com',
        'mode': 'http',
        'private': False,
        'enabled': True,
        'listen_port': 0,
        'pass_host_header': False,
        'rewrite_redirects': False,
        'access_groups': [{'id': 'grp-abc-123'}],
        'targets': [{
            'target_id': 'res-1',
            'target_type': 'subnet',
            'host': '10.0.0.1',
            'port': 8080,
            'path': '/',
            'protocol': 'http',
            'enabled': True,
            'options': {
                'direct_upstream': True,
                'skip_tls_verify': False,
                'path_rewrite': 'preserve',
                'proxy_protocol': False,
            },
        }],
        'auth': {
            'bearer_auth': {'enabled': False, 'distribution_groups': []},
            'password_auth': {'enabled': False, 'password': ''},
            'pin_auth': {'enabled': False, 'pin': ''},
        },
        'meta': {},
        'proxy_cluster': 'cluster-1',
    }
    base.update(overrides)
    return base


def exported_service(**overrides):
    """A service as the export template writes it (module input shape)."""
    base = {
        'domain': 'app.example.com',
        'private': False,
        'enabled': True,
        'access_groups': ['ci-test-group'],
        'targets': [{
            'host': '10.0.0.1',
            'port': 8080,
            'protocol': 'http',
            'target_id': 'res-1',
            'target_type': 'subnet',
            'enabled': True,
            'direct_upstream': True,
            'skip_tls_verify': False,
        }],
        'state': 'present',
    }
    base.update(overrides)
    return base


class TestAccessGroupResolution:

    def test_exported_names_match_api_ids(self):
        """The core fix: name→ID resolution prevents false positives."""
        diffs = _compare_service(
            api_service(), exported_service(), group_ids=GROUP_IDS)
        assert not any('access_groups' in d for d in diffs)

    def test_without_group_ids_names_differ(self):
        diffs = _compare_service(api_service(), exported_service())
        assert any('access_groups' in d for d in diffs)

    def test_raw_ids_in_config_still_work(self):
        svc = exported_service(access_groups=['grp-abc-123'])
        diffs = _compare_service(api_service(), svc, group_ids=GROUP_IDS)
        assert not any('access_groups' in d for d in diffs)


class TestTargetNormalization:

    def test_flat_vs_nested_options_are_equal(self):
        """Export writes flat keys; API returns nested options dict."""
        diffs = _compare_service(
            api_service(), exported_service(), group_ids=GROUP_IDS)
        assert not any('targets' in d for d in diffs)

    def test_a_real_target_change_is_detected(self):
        changed = exported_service(targets=[{
            'host': '10.0.0.2',
            'port': 9090,
            'protocol': 'http',
            'target_id': 'res-1',
            'target_type': 'subnet',
            'enabled': True,
        }])
        diffs = _compare_service(api_service(), changed, group_ids=GROUP_IDS)
        assert any('targets' in d for d in diffs)

    def test_skip_tls_change_detected(self):
        changed = exported_service(targets=[{
            'host': '10.0.0.1',
            'port': 8080,
            'protocol': 'http',
            'target_id': 'res-1',
            'target_type': 'subnet',
            'enabled': True,
            'direct_upstream': True,
            'skip_tls_verify': True,
        }])
        diffs = _compare_service(api_service(), changed, group_ids=GROUP_IDS)
        assert any('targets' in d for d in diffs)


class TestAuthDeclaredKeys:

    def test_bearer_only_does_not_report_other_schemes_removed(self):
        """Export omits password_auth and pin_auth when only bearer is
        enabled. The diff must not flag those as removed."""
        current = api_service(auth={
            'bearer_auth': {
                'enabled': True,
                'distribution_groups': ['grp-abc-123'],
            },
            'password_auth': {'enabled': False, 'password': ''},
            'pin_auth': {'enabled': False, 'pin': ''},
        })
        desired = exported_service(auth={
            'bearer_auth': {
                'enabled': True,
                'distribution_groups': ['ci-test-group'],
            },
        })
        diffs = _compare_service(current, desired, group_ids=GROUP_IDS)
        assert not any('password_auth' in d for d in diffs)
        assert not any('pin_auth' in d for d in diffs)

    def test_bearer_distribution_groups_resolved(self):
        current = api_service(auth={
            'bearer_auth': {
                'enabled': True,
                'distribution_groups': ['grp-abc-123'],
            },
            'password_auth': {'enabled': False, 'password': ''},
            'pin_auth': {'enabled': False, 'pin': ''},
        })
        desired = exported_service(auth={
            'bearer_auth': {
                'enabled': True,
                'distribution_groups': ['ci-test-group'],
            },
        })
        diffs = _compare_service(current, desired, group_ids=GROUP_IDS)
        assert not any('distribution_groups' in d for d in diffs)

    def test_no_auth_in_desired_skips_auth_comparison(self):
        diffs = _compare_service(api_service(), exported_service(),
                                 group_ids=GROUP_IDS)
        assert not any('auth' in d for d in diffs)

    def test_real_auth_change_is_detected(self):
        desired = exported_service(auth={
            'bearer_auth': {'enabled': True, 'distribution_groups': []},
        })
        current = api_service(auth={
            'bearer_auth': {'enabled': False, 'distribution_groups': []},
            'password_auth': {'enabled': False, 'password': ''},
            'pin_auth': {'enabled': False, 'pin': ''},
        })
        diffs = _compare_service(current, desired, group_ids=GROUP_IDS)
        assert any('enabled' in d for d in diffs)


class TestFullRoundTrip:
    """End-to-end through netbird_diff with service resource_type."""

    def test_freshly_exported_config_reports_no_changes(self):
        current_map = {'app.example.com': api_service()}
        desired_list = [exported_service()]
        result = netbird_diff(desired_list, current_map, 'service',
                              key_field='domain', group_ids=GROUP_IDS)
        assert result['changed'] == {}
        assert result['unchanged'] == ['app.example.com']

    def test_a_real_change_is_still_detected(self):
        current_map = {'app.example.com': api_service()}
        desired_list = [exported_service(private=True)]
        result = netbird_diff(desired_list, current_map, 'service',
                              key_field='domain', group_ids=GROUP_IDS)
        assert 'app.example.com' in result['changed']


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
