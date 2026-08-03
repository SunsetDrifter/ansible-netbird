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

from ansible_collections.community.ansible_netbird.plugins.modules import netbird_setup_key
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


class TestRevokedIsADesiredState:
    """``revoked: true`` asks for an unusable key, so nothing about it is a
    defect. Reporting one would warn on every run, and with rotation enabled
    would delete and recreate the key every run -- the replacement is revoked
    too, so the condition never clears."""

    def test_a_revoked_key_is_not_invalid_when_revocation_was_asked_for(self):
        assert setup_key_invalid_reason(key(revoked=True, valid=False),
                                        desired_revoked=True) is None

    def test_an_exhausted_key_is_not_reported_either(self):
        """The whole check is meaningless once an unusable key is the goal."""
        assert setup_key_invalid_reason(key(usage_limit=1, used_times=1),
                                        desired_revoked=True) is None

    def test_still_reported_when_revocation_was_not_asked_for(self):
        assert setup_key_invalid_reason(key(revoked=True),
                                        desired_revoked=False) == 'it is revoked'

    def test_defaults_to_reporting(self):
        """Callers that predate the parameter keep the old behaviour."""
        assert setup_key_invalid_reason(key(revoked=True)) == 'it is revoked'


class _Exit(Exception):
    pass


class DummyModule:
    """Minimal AnsibleModule stand-in capturing warnings and the exit path."""

    def __init__(self, params, check_mode=False):
        self.params = params
        self.check_mode = check_mode
        self.warnings = []
        self.exit_kwargs = None
        self.fail_kwargs = None

    def exit_json(self, **kwargs):
        self.exit_kwargs = kwargs
        raise _Exit()

    def fail_json(self, **kwargs):
        self.fail_kwargs = kwargs
        raise _Exit()

    def warn(self, msg):
        self.warnings.append(msg)


# Out of uses rather than revoked: an exhausted key cannot enrol, and unlike
# revocation it does not interact with the update path, so a test using it
# isolates the behaviour under test.
EXHAUSTED_KEY = {
    'id': 'key-1',
    'name': 'enrolment',
    'valid': False,
    'revoked': False,
    'type': 'reusable',
    'usage_limit': 1,
    'used_times': 1,
    'ephemeral': False,
    'allow_extra_dns_labels': False,
    'auto_groups': [],
}

REVOKED_KEY = dict(EXHAUSTED_KEY, revoked=True, usage_limit=0, used_times=0)


BASE_PARAMS = {
    'api_url': 'https://api.example.test',
    'api_token': 'token',
    'validate_certs': True,
    'timeout': 30,
    'state': 'present',
    'key_id': None,
    'name': None,
    'key_type': 'one-off',
    'expires_in': 86400,
    'revoked': False,
    'auto_groups': None,
    'usage_limit': 0,
    'ephemeral': False,
    'allow_extra_dns_labels': False,
    'rotate_when_invalid': False,
}


def run_module(monkeypatch, params, existing=None, check_mode=False,
               create_fails=False):
    """Drive netbird_setup_key.main() with AnsibleModule and NetBirdAPI patched.

    Returns ``(module, calls)`` so a test can assert on both what was warned
    and what was sent. ``create_fails`` makes create_setup_key raise, for
    asserting what a half-done rotation leaves behind.
    """
    existing = EXHAUSTED_KEY if existing is None else existing
    module = DummyModule(dict(BASE_PARAMS, **params), check_mode=check_mode)
    calls = []

    class FakeAPI:
        def __init__(self, *args, **kwargs):
            pass

        def get_setup_key(self, key_id):
            return existing, {}

        def list_setup_keys(self):
            return [existing], {}

        def delete_setup_key(self, key_id):
            calls.append(('delete', key_id))
            return {}, {}

        def create_setup_key(self, **kwargs):
            if create_fails:
                raise netbird_setup_key.NetBirdAPIError(
                    'boom', status_code=500)
            calls.append(('create', kwargs))
            return dict(existing, key='plaintext-secret'), {}

        def update_setup_key(self, key_id, **kwargs):
            calls.append(('update', key_id, kwargs))
            return existing, {}

    monkeypatch.setattr(netbird_setup_key, 'AnsibleModule', lambda **kw: module)
    monkeypatch.setattr(netbird_setup_key, 'NetBirdAPI', FakeAPI)

    with pytest.raises(_Exit):
        netbird_setup_key.main()

    return module, calls


class TestRotationNeedsAName:
    """Rotation creates a replacement from the task's parameters, so it needs
    a name to create with; addressed by ``key_id`` alone there is none. The
    replacement is created before the invalid key is deleted, so a failed
    create cannot destroy the key it was meant to replace."""

    def test_key_id_only_does_not_delete(self, monkeypatch):
        _module, calls = run_module(monkeypatch, {
            'key_id': 'key-1',
            'rotate_when_invalid': True,
        })
        assert [c[0] for c in calls] == [], \
            "nothing may be deleted when there is no name to recreate with"

    def test_key_id_only_does_not_fail_the_task(self, monkeypatch):
        module, _calls = run_module(monkeypatch, {
            'key_id': 'key-1',
            'rotate_when_invalid': True,
        })
        assert module.fail_kwargs is None
        assert module.exit_kwargs is not None

    def test_key_id_only_warns_and_says_what_to_pass(self, monkeypatch):
        module, _calls = run_module(monkeypatch, {
            'key_id': 'key-1',
            'rotate_when_invalid': True,
        })
        assert any('name' in w for w in module.warnings), module.warnings

    def test_name_match_does_rotate(self, monkeypatch):
        _module, calls = run_module(monkeypatch, {
            'name': 'enrolment',
            'rotate_when_invalid': True,
        })
        assert [c[0] for c in calls] == ['create', 'delete'], \
            "the replacement must exist before the invalid key is deleted"
        assert calls[0][1]['name'] == 'enrolment'

    def test_key_id_with_name_rotates(self, monkeypatch):
        """A name is all the create path needs, however the key was found."""
        _module, calls = run_module(monkeypatch, {
            'key_id': 'key-1',
            'name': 'enrolment',
            'rotate_when_invalid': True,
        })
        assert [c[0] for c in calls] == ['create', 'delete']

    def test_create_failure_leaves_the_old_key(self, monkeypatch):
        """A rotation whose create call fails must not have deleted anything:
        the invalid key stays addressable for the next attempt."""
        module, calls = run_module(monkeypatch, {
            'name': 'enrolment',
            'rotate_when_invalid': True,
        }, create_fails=True)
        assert 'delete' not in [c[0] for c in calls]
        assert module.fail_kwargs is not None

    def test_check_mode_deletes_nothing(self, monkeypatch):
        _module, calls = run_module(monkeypatch, {
            'name': 'enrolment',
            'rotate_when_invalid': True,
        }, check_mode=True)
        assert calls == []


class TestRevokedDesiredStateDoesNotChurn:

    def test_a_revoked_key_asked_to_be_revoked_is_left_alone(self, monkeypatch):
        """Without the guard this deletes and recreates on every run, emitting
        a fresh plaintext secret each time."""
        _module, calls = run_module(monkeypatch, {
            'name': 'enrolment',
            'revoked': True,
            'rotate_when_invalid': True,
        }, existing=REVOKED_KEY)
        assert [c[0] for c in calls] == [], calls

    def test_and_reports_no_change(self, monkeypatch):
        module, _calls = run_module(monkeypatch, {
            'name': 'enrolment',
            'revoked': True,
            'rotate_when_invalid': True,
        }, existing=REVOKED_KEY)
        assert module.exit_kwargs['changed'] is False


class TestRevocationIsNotUndone:
    """``revoked`` defaults to ``false``, so a task naming a revoked key asked
    to un-revoke it without ever mentioning the field. The API refuses that
    ("can't un-revoke a revoked setup key"), so the task failed with a 422
    about something the playbook never said."""

    def test_no_update_is_sent_for_a_revoked_key(self, monkeypatch):
        _module, calls = run_module(monkeypatch, {
            'name': 'enrolment',
        }, existing=REVOKED_KEY)
        assert calls == [], "revoked=false must not be sent to a revoked key"

    def test_it_reports_no_change_rather_than_failing(self, monkeypatch):
        module, _calls = run_module(monkeypatch, {
            'name': 'enrolment',
        }, existing=REVOKED_KEY)
        assert module.fail_kwargs is None
        assert module.exit_kwargs['changed'] is False

    def test_it_says_revocation_cannot_be_undone(self, monkeypatch):
        module, _calls = run_module(monkeypatch, {
            'name': 'enrolment',
        }, existing=REVOKED_KEY)
        assert any('un-revok' in w for w in module.warnings), module.warnings

    def test_another_edit_still_applies_with_revoked_preserved(self, monkeypatch):
        """An auto_groups change is legal on a revoked key; only the revoked
        transition is not. The update must carry the current value, not the
        requested one, or the API rejects the whole request."""
        _module, calls = run_module(monkeypatch, {
            'name': 'enrolment',
            'auto_groups': ['grp-1'],
        }, existing=REVOKED_KEY)
        assert [c[0] for c in calls] == ['update'], calls
        assert calls[0][2]['revoked'] is True
        assert calls[0][2]['auto_groups'] == ['grp-1']

    def test_revoking_an_unrevoked_key_still_works(self, monkeypatch):
        """The permitted direction is untouched."""
        _module, calls = run_module(monkeypatch, {
            'name': 'enrolment',
            'revoked': True,
        }, existing=dict(EXHAUSTED_KEY, usage_limit=0, used_times=0))
        assert [c[0] for c in calls] == ['update'], calls
        assert calls[0][2]['revoked'] is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


class TestRenameIsDriftNotChange:
    """The API's update accepts only ``revoked`` and ``auto_groups``, so a
    key found by ``key_id`` with a different ``name`` cannot be renamed.
    Treating the mismatch as an update reported ``changed: true`` on every
    run while renaming nothing; it is immutable drift like ``key_type``."""

    USABLE = dict(EXHAUSTED_KEY, valid=True, usage_limit=0, used_times=0)

    def test_no_update_is_sent(self, monkeypatch):
        _module, calls = run_module(monkeypatch, {
            'key_id': 'key-1',
            'name': 'new-name',
        }, existing=self.USABLE)
        assert [c[0] for c in calls] == []

    def test_it_reports_no_change(self, monkeypatch):
        module, _calls = run_module(monkeypatch, {
            'key_id': 'key-1',
            'name': 'new-name',
        }, existing=self.USABLE)
        assert module.exit_kwargs is not None
        assert module.exit_kwargs.get('changed') is False

    def test_the_drift_warning_names_the_name(self, monkeypatch):
        module, _calls = run_module(monkeypatch, {
            'key_id': 'key-1',
            'name': 'new-name',
        }, existing=self.USABLE)
        assert any('name' in w and 'new-name' in w for w in module.warnings), \
            module.warnings

    def test_a_matching_name_is_not_drift(self, monkeypatch):
        module, _calls = run_module(monkeypatch, {
            'key_id': 'key-1',
            'name': 'enrolment',
        }, existing=self.USABLE)
        assert module.warnings == [], module.warnings
