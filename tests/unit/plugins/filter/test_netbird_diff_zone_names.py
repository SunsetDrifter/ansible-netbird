# -*- coding: utf-8 -*-
# Copyright: (c) 2024-2026, NetBird and contributors
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
"""Unit tests for how the preview diff identifies a config entry.

Run via:
    ansible-test units --docker default

A DNS zone's name follows its domain when omitted, so a config entry may
declare a domain alone. Reading ``name`` directly yields '' for such an entry,
which made the preview report two wrong things at once: a new zone called '',
and the real zone as orphaned -- the latter being what a strict run then acts
on.

The fallback is inert for every other resource type the filter handles, none of
which carry a ``domain`` key.

The filter is pure.
"""

from __future__ import absolute_import, division, print_function
__metaclass__ = type

import pytest

from ansible_collections.community.ansible_netbird.plugins.filter.netbird_diff import (
    netbird_diff,
)


ZONE = {'id': 'zone-1', 'name': 'corp.example.com',
        'domain': 'corp.example.com', 'enabled': True}


class TestDomainOnlyEntry:

    def test_is_not_reported_as_a_new_empty_name(self):
        result = netbird_diff([{'domain': 'corp.example.com'}],
                              {'corp.example.com': ZONE})
        assert '' not in result['new']
        assert result['new'] == []

    def test_does_not_orphan_the_zone_it_declares(self):
        """The consequence that matters: strict mode deletes what lands here."""
        result = netbird_diff([{'domain': 'corp.example.com'}],
                              {'corp.example.com': ZONE})
        assert result['orphaned'] == []

    def test_is_recognised_as_existing(self):
        result = netbird_diff([{'domain': 'corp.example.com'}],
                              {'corp.example.com': ZONE})
        assert 'corp.example.com' in result['unchanged'] or \
            'corp.example.com' in result['changed']

    def test_a_genuinely_new_domain_is_still_new(self):
        result = netbird_diff([{'domain': 'new.example.com'}], {})
        assert result['new'] == ['new.example.com']

    def test_absent_matches_by_domain(self):
        result = netbird_diff([{'domain': 'corp.example.com', 'state': 'absent'}],
                              {'corp.example.com': ZONE})
        assert result['remove'] == ['corp.example.com']

    def test_an_explicit_name_still_wins(self):
        entry = {'name': 'Office Zone', 'domain': 'corp.example.com'}
        result = netbird_diff([entry], {'Office Zone': dict(ZONE, name='Office Zone')})
        assert result['orphaned'] == []
        assert result['new'] == []

    def test_an_empty_name_falls_back_to_domain(self):
        """`name: ''` is indistinguishable from an omitted one here, and the
        module treats it the same way."""
        result = netbird_diff([{'name': '', 'domain': 'corp.example.com'}],
                              {'corp.example.com': ZONE})
        assert result['orphaned'] == []


class TestOtherResourceTypesAreUnaffected:
    """None of them carry a `domain` key, so the fallback never fires."""

    def test_a_named_resource_is_unchanged(self):
        current = {'developers': {'id': 'g-1', 'name': 'developers'}}
        result = netbird_diff([{'name': 'developers'}], current)
        assert result['orphaned'] == []
        assert result['new'] == []

    def test_an_orphan_is_still_orphaned(self):
        current = {'stale': {'id': 'g-9', 'name': 'stale'}}
        result = netbird_diff([{'name': 'developers'}], current)
        assert result['orphaned'] == ['stale']

    def test_a_nameserver_groups_domains_list_is_not_mistaken_for_a_domain(self):
        """The key is `domains`, plural, so the fallback must not read it. A
        nameless entry still classifies as '' exactly as it did before -- the
        point is that it does not silently acquire an identity from an unrelated
        key."""
        result = netbird_diff([{'domains': ['corp.example.com']}], {})
        assert result['new'] == ['']
        assert 'corp.example.com' not in result['new']

    def test_protected_names_are_still_excluded(self):
        current = {'All': {'id': 'g-all', 'name': 'All'}}
        result = netbird_diff([], current, protected=['All'])
        assert result['orphaned'] == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
