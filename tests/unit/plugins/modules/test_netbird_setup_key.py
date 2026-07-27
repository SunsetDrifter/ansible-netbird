# -*- coding: utf-8 -*-
# Copyright: (c) 2024-2026, NetBird and contributors
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
"""Unit tests for netbird_setup_key's validity and immutability guards.

Run via:
    ansible-test units --docker default

A setup key is found by name and nothing else, so the lookup happily returns
one that is revoked, expired, or out of uses. Such a key satisfies no desired
state: reporting ``changed: false`` against it tells the operator enrolment is
provisioned when the next peer to use it will fail, with nothing connecting
the two events.

Both helpers under test are pure, so they need no API or module stub.
"""

from __future__ import absolute_import, division, print_function
__metaclass__ = type

import pytest

from ansible_collections.community.ansible_netbird.plugins.modules.netbird_setup_key import (
    setup_key_immutable_drift,
    setup_key_invalid_reason,
)


def key(**overrides):
    base = {
        'id': 'key-1',
        'name': 'demo',
        'valid': True,
        'revoked': False,
        'type': 'reusable',
        'usage_limit': 0,
        'used_times': 0,
        'ephemeral': False,
        'allow_extra_dns_labels': False,
    }
    base.update(overrides)
    return base


class TestSetupKeyInvalidReason:

    def test_usable_key_has_no_reason(self):
        assert setup_key_invalid_reason(key()) is None

    def test_revoked(self):
        assert 'revoked' in setup_key_invalid_reason(key(revoked=True))

    def test_not_valid(self):
        assert 'not valid' in setup_key_invalid_reason(key(valid=False))

    def test_usage_exhausted(self):
        reason = setup_key_invalid_reason(key(usage_limit=5, used_times=5))
        assert 'no uses left' in reason
        assert '5 of 5' in reason

    def test_usage_over_limit(self):
        """Defensive: the counter should not exceed the limit, but a key that
        somehow did must still be reported unusable rather than slipping
        through an equality check."""
        assert setup_key_invalid_reason(key(usage_limit=5, used_times=9))

    def test_unlimited_usage_is_not_exhausted(self):
        """usage_limit 0 means unlimited — a used key is still fine."""
        assert setup_key_invalid_reason(key(usage_limit=0, used_times=999)) is None

    def test_specific_reason_wins_over_the_generic_one(self):
        """A key can be several kinds of dead at once. The message should name
        the actionable cause, not just 'not valid'."""
        reason = setup_key_invalid_reason(
            key(valid=False, usage_limit=5, used_times=5))
        assert 'no uses left' in reason

    def test_missing_fields_are_tolerated(self):
        """Older API versions, or a trimmed response, must not raise."""
        assert setup_key_invalid_reason({'id': 'k', 'name': 'n'}) is None


class TestSetupKeyImmutableDrift:
    """Parameters fixed at creation must be reported, not silently dropped."""

    DEFAULTS = {
        'key_type': 'one-off',
        'usage_limit': 0,
        'ephemeral': False,
        'allow_extra_dns_labels': False,
    }

    def test_no_drift_when_everything_matches(self):
        current = key(type='reusable', usage_limit=10)
        params = {'key_type': 'reusable', 'usage_limit': 10,
                  'ephemeral': False, 'allow_extra_dns_labels': False}
        assert setup_key_immutable_drift(current, params, self.DEFAULTS) == []

    def test_reports_usage_limit_drift(self):
        current = key(usage_limit=100)
        params = {'usage_limit': 5}
        drift = setup_key_immutable_drift(current, params, self.DEFAULTS)
        assert len(drift) == 1
        assert 'usage_limit' in drift[0]
        assert '5' in drift[0] and '100' in drift[0]

    def test_reports_key_type_drift(self):
        current = key(type='one-off')
        params = {'key_type': 'reusable'}
        drift = setup_key_immutable_drift(current, params, self.DEFAULTS)
        assert any('key_type' in d for d in drift)

    def test_default_valued_params_are_not_reported(self):
        """These parameters all carry argspec defaults, so a value equal to
        the default cannot be distinguished from one never supplied. Warning
        on those would fire for every task that simply omits them."""
        current = key(type='reusable', usage_limit=100)
        params = {'key_type': 'one-off', 'usage_limit': 0}   # both defaults
        assert setup_key_immutable_drift(current, params, self.DEFAULTS) == []

    def test_none_params_are_not_reported(self):
        assert setup_key_immutable_drift(key(), {'key_type': None}, self.DEFAULTS) == []

    def test_expires_in_is_never_reported(self):
        """It is a duration at creation and the API returns an absolute
        timestamp; the two cannot be compared without guessing creation time."""
        current = key(expires='2030-01-01T00:00:00Z')
        params = {'expires_in': 99}
        assert setup_key_immutable_drift(current, params, self.DEFAULTS) == []

    def test_drift_is_ordered_deterministically(self):
        """The message goes in a warning; unstable ordering makes it noisy to
        diff across runs."""
        current = key(type='one-off', usage_limit=1, ephemeral=False)
        params = {'key_type': 'reusable', 'usage_limit': 7, 'ephemeral': True}
        drift = setup_key_immutable_drift(current, params, self.DEFAULTS)
        assert [d.split(' ')[0] for d in drift] == sorted(
            d.split(' ')[0] for d in drift)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
