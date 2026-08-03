# -*- coding: utf-8 -*-
# Copyright: (c) 2024-2026, NetBird and contributors
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
"""Unit tests for the router masquerade default.

Run via:
    ansible-test units --docker default

``masquerade`` defaulted to ``false`` on ``netbird_network``'s routers while
``netbird_route`` defaulted it to ``true``, and the dashboard enables it on
every routing peer it creates. Networks are the successor to legacy routes, so
the natural migration silently dropped NAT.

These pin the consequence that makes the change breaking rather than merely
new: because the default is applied by the argspec before the comparison, a
router declared without an explicit ``masquerade`` no longer matches one the
old default created, so the next run updates it.

``router_needs_update`` is pure.
"""

from __future__ import absolute_import, division, print_function
__metaclass__ = type

import pytest

from ansible_collections.community.ansible_netbird.plugins.modules.netbird_network import (
    router_needs_update,
)


def current(**overrides):
    """A router as the API returns it."""
    base = {'id': 'rt-1', 'peer': 'peer-1', 'metric': 9999,
            'masquerade': True, 'enabled': True}
    base.update(overrides)
    return base


def desired(**overrides):
    """A router as the argspec hands it over, defaults already filled in."""
    base = {'peer': 'peer-1', 'metric': 9999, 'masquerade': True,
            'enabled': True}
    base.update(overrides)
    return base


class TestMasqueradeDefault:

    def test_omitted_masquerade_means_true(self):
        """The default the comparator falls back to when the key is absent
        altogether, which is what a non-argspec caller passes."""
        assert router_needs_update(current(masquerade=True), {'metric': 9999}) is False
        assert router_needs_update(current(masquerade=False), {'metric': 9999}) is True

    def test_a_router_created_under_the_old_default_is_flagged_for_update(self):
        """The breaking consequence. Nothing else about the router changed."""
        assert router_needs_update(current(masquerade=False), desired()) is True

    def test_an_explicit_false_is_honoured_and_idempotent(self):
        """The migration path for playbooks that wanted the old behaviour."""
        assert router_needs_update(current(masquerade=False),
                                   desired(masquerade=False)) is False

    def test_enabling_masquerade_on_an_unmasqueraded_router_is_a_change(self):
        assert router_needs_update(current(masquerade=False),
                                   desired(masquerade=True)) is True

    def test_matching_routers_need_no_update(self):
        assert router_needs_update(current(), desired()) is False


class TestOtherFieldsAreUnaffected:

    def test_metric_change_is_detected(self):
        assert router_needs_update(current(), desired(metric=100)) is True

    def test_enabled_change_is_detected(self):
        assert router_needs_update(current(), desired(enabled=False)) is True

    def test_metric_default_is_unchanged(self):
        assert router_needs_update(current(metric=9999), {'masquerade': True}) is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
