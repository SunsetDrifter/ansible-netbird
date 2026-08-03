# -*- coding: utf-8 -*-
# Copyright: (c) 2024-2026, NetBird and contributors
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
"""Unit tests for netbird_route's change detection.

Run via:
    ansible-test units --docker default

Focus is ``access_control_groups``, newly exposed by the module. It gates
which peers may reach the routed CIDR, so a change that is silently dropped
is an access-control change that did not happen.

``route_needs_update`` is pure.
"""

from __future__ import absolute_import, division, print_function
__metaclass__ = type

import pytest

from ansible_collections.community.ansible_netbird.plugins.modules.netbird_route import (
    route_needs_update,
)


CURRENT = {
    'id': 'route-1',
    'network_id': 'internal',
    'network': '10.0.0.0/24',
    'description': '',
    'peer': 'peer-1',
    'metric': 9999,
    'masquerade': True,
    'enabled': True,
    'groups': ['g-dist'],
    'keep_route': False,
    'domains': [],
    'access_control_groups': ['g-acl'],
}


def params(**overrides):
    """Only the keys the module actually passes to the comparator."""
    base = {
        'network': CURRENT['network'],
        'description': CURRENT['description'],
        'peer_id': CURRENT['peer'],
        'peer_groups': None,
        'metric': CURRENT['metric'],
        'masquerade': CURRENT['masquerade'],
        'enabled': CURRENT['enabled'],
        'groups': list(CURRENT['groups']),
        'keep_route': CURRENT['keep_route'],
        'domains': None,
        'access_control_groups': list(CURRENT['access_control_groups']),
    }
    base.update(overrides)
    return base


class TestAccessControlGroups:

    def test_no_change_when_identical(self):
        assert route_needs_update(CURRENT, params()) is False

    def test_adding_an_acl_group_is_a_change(self):
        assert route_needs_update(
            CURRENT, params(access_control_groups=['g-acl', 'g-extra'])) is True

    def test_removing_all_acl_groups_is_a_change(self):
        """Clearing the ACL opens the routed CIDR to every peer the route
        reaches, so it must never be mistaken for a no-op."""
        assert route_needs_update(CURRENT, params(access_control_groups=[])) is True

    def test_replacing_the_acl_group_is_a_change(self):
        assert route_needs_update(
            CURRENT, params(access_control_groups=['g-other'])) is True

    def test_order_is_not_a_change(self):
        current = dict(CURRENT, access_control_groups=['a', 'b'])
        assert route_needs_update(
            current, params(access_control_groups=['b', 'a'])) is False

    def test_dict_shaped_groups_compare_against_plain_ids(self):
        """The API returns related objects as dicts; params are id strings."""
        current = dict(CURRENT,
                       access_control_groups=[{'id': 'g-acl', 'name': 'acl'}])
        assert route_needs_update(
            current, params(access_control_groups=['g-acl'])) is False

    def test_none_means_unspecified_not_empty(self):
        """None is 'leave alone'. The module substitutes the route's existing
        value before calling the comparator, so None must never read as a
        request to clear."""
        assert route_needs_update(
            CURRENT, params(access_control_groups=None)) is False

    def test_absent_on_the_route_and_requested_is_a_change(self):
        current = dict(CURRENT)
        del current['access_control_groups']
        assert route_needs_update(
            current, params(access_control_groups=['g-acl'])) is True


class TestOtherFieldsStillCompared:
    """Guard against the new branch shadowing the existing ones."""

    def test_network_change(self):
        assert route_needs_update(CURRENT, params(network='10.9.0.0/24')) is True

    def test_masquerade_change(self):
        assert route_needs_update(CURRENT, params(masquerade=False)) is True

    def test_distribution_group_change(self):
        assert route_needs_update(CURRENT, params(groups=['g-other'])) is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
