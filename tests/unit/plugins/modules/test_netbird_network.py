# -*- coding: utf-8 -*-
# Copyright: (c) 2024-2026, NetBird and contributors
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
"""Unit tests for network resource identity and comparison.

Run via:
    ansible-test units --docker default

``sync_resources`` used to key both its current and desired maps on
``address``. Address is a property of a resource, not its identity: two
resources may legitimately share one, and changing it should be an update
rather than a delete-and-recreate that churns the resource id.

Both functions under test are pure.
"""

from __future__ import absolute_import, division, print_function
__metaclass__ = type

import pytest

from ansible_collections.community.ansible_netbird.plugins.modules.netbird_network import (
    resource_key,
    resource_needs_update,
)


class TestResourceKey:

    def test_named_resource_keys_on_name(self):
        assert resource_key({'name': 'web', 'address': '10.0.0.1/32'}) == ('name', 'web')

    def test_unnamed_resource_falls_back_to_address(self):
        """`name` defaults to '' in the argspec, so unnamed resources are
        legal and common. They keep the previous address-based identity —
        there is nothing else to key them on."""
        assert resource_key({'name': '', 'address': '10.0.0.1/32'}) == \
            ('address', '10.0.0.1/32')

    def test_missing_name_falls_back_to_address(self):
        assert resource_key({'address': '10.0.0.1/32'}) == ('address', '10.0.0.1/32')

    def test_none_name_falls_back_to_address(self):
        assert resource_key({'name': None, 'address': '10.0.0.1/32'}) == \
            ('address', '10.0.0.1/32')

    def test_whitespace_only_name_is_treated_as_unnamed(self):
        assert resource_key({'name': '   ', 'address': '10.0.0.1/32'}) == \
            ('address', '10.0.0.1/32')

    def test_name_is_stripped(self):
        """Otherwise a stray space makes a config non-idempotent against a
        resource the API stored trimmed."""
        assert resource_key({'name': ' web ', 'address': '10.0.0.1/32'}) == \
            ('name', 'web')

    def test_two_resources_sharing_an_address_have_distinct_keys(self):
        """The headline case: same host, two names, different distribution
        groups. Keying on address collapsed these into one."""
        a = resource_key({'name': 'web', 'address': '10.0.0.1/32'})
        b = resource_key({'name': 'ssh', 'address': '10.0.0.1/32'})
        assert a != b

    def test_identity_survives_an_address_change(self):
        """So an address edit is an update, not a delete-and-recreate."""
        before = resource_key({'name': 'web', 'address': '10.0.0.1/32'})
        after = resource_key({'name': 'web', 'address': '10.0.0.2/32'})
        assert before == after


class TestResourceNeedsUpdate:

    BASE = {
        'name': 'web',
        'address': '10.0.0.1/32',
        'description': '',
        'enabled': True,
        'groups': [],
    }

    def test_identical_needs_no_update(self):
        assert resource_needs_update(self.BASE, dict(self.BASE)) is False

    def test_address_change_is_detected(self):
        """New: address is no longer the identity, so a change to it has to be
        picked up here or the edit is silently dropped."""
        desired = dict(self.BASE, address='10.0.0.2/32')
        assert resource_needs_update(self.BASE, desired) is True

    def test_name_change_is_detected(self):
        assert resource_needs_update(self.BASE, dict(self.BASE, name='api')) is True

    def test_description_change_is_detected(self):
        assert resource_needs_update(self.BASE, dict(self.BASE, description='x')) is True

    def test_enabled_change_is_detected(self):
        assert resource_needs_update(self.BASE, dict(self.BASE, enabled=False)) is True

    def test_group_change_is_detected(self):
        assert resource_needs_update(self.BASE, dict(self.BASE, groups=['g1'])) is True

    def test_group_order_is_not_a_change(self):
        current = dict(self.BASE, groups=['g1', 'g2'])
        desired = dict(self.BASE, groups=['g2', 'g1'])
        assert resource_needs_update(current, desired) is False

    def test_groups_as_dicts_compare_against_plain_ids(self):
        """The API returns related objects as dicts; params are id strings."""
        current = dict(self.BASE, groups=[{'id': 'g1', 'name': 'one'}])
        desired = dict(self.BASE, groups=['g1'])
        assert resource_needs_update(current, desired) is False

    def test_none_and_empty_address_are_equivalent(self):
        current = dict(self.BASE, address=None)
        desired = dict(self.BASE, address='')
        assert resource_needs_update(current, desired) is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
