# -*- coding: utf-8 -*-
# Copyright: (c) 2024-2026, NetBird and contributors
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
"""Unit tests for the auto_groups unpin helpers.

Run via:
    ansible-test units --docker default

The API refuses to delete a group that any setup key's or any user's
``auto_groups`` still references, answering 400 and naming only the first
blocking reference it finds -- a user by raw ID. Both owner types must be swept:
a caller handling only setup keys still hits the rejection on the user case.

These PUTs are full-replace, so each owner has to be re-sent with its other
mutable fields intact — omitting them would un-revoke a key or strip a user's
role while unpinning.

The API client is stubbed; no request is made.
"""

from __future__ import absolute_import, division, print_function
__metaclass__ = type

import pytest

from ansible_collections.community.ansible_netbird.plugins.module_utils.netbird_api import (
    NetBirdAPIError,
    find_auto_group_owners,
    unpin_group,
)


class _FailJson(Exception):
    """Raised by the stub module so a refused unpin is observable."""


class _StubModule:
    def __init__(self):
        self.fail_msg = None

    def fail_json(self, msg=None, **kwargs):
        self.fail_msg = msg
        raise _FailJson(msg)


class StubAPI:
    def __init__(self, setup_keys=None, users=None, fail_on=None):
        self._keys = setup_keys or []
        self._users = users or []
        self.key_updates = []
        self.user_updates = []
        # id of an owner whose update should raise, to exercise a sweep that
        # fails partway through
        self._fail_on = fail_on
        self.module = _StubModule()

    def list_setup_keys(self):
        return self._keys, {}

    def list_users(self):
        return self._users, {}

    def update_setup_key(self, key_id, **kwargs):
        if key_id == self._fail_on:
            raise NetBirdAPIError('boom', status_code=500)
        self.key_updates.append((key_id, kwargs))
        return {}, {}

    def update_user(self, user_id, **kwargs):
        if user_id == self._fail_on:
            raise NetBirdAPIError('boom', status_code=500)
        self.user_updates.append((user_id, kwargs))
        return {}, {}


def key(**overrides):
    base = {'id': 'key-1', 'name': 'enrolment', 'revoked': False,
            'auto_groups': ['g-target', 'g-other']}
    base.update(overrides)
    return base


def user(**overrides):
    base = {'id': 'user-1', 'email': 'se@example.com', 'role': 'admin',
            'is_blocked': False, 'auto_groups': ['g-target', 'g-other']}
    base.update(overrides)
    return base


class TestFindAutoGroupOwners:

    def test_finds_nothing_when_unpinned(self):
        api = StubAPI(setup_keys=[key(auto_groups=['g-other'])],
                      users=[user(auto_groups=[])])
        assert find_auto_group_owners(api, 'g-target') == []

    def test_finds_a_setup_key(self):
        api = StubAPI(setup_keys=[key()])
        owners = find_auto_group_owners(api, 'g-target')
        assert [(k, i, lbl) for k, i, lbl, _o in owners] == \
            [('setup key', 'key-1', 'enrolment')]

    def test_finds_a_user_and_labels_it_by_email(self):
        api = StubAPI(users=[user()])
        owners = find_auto_group_owners(api, 'g-target')
        assert [(k, i, lbl) for k, i, lbl, _o in owners] == \
            [('user', 'user-1', 'se@example.com')]

    def test_finds_both_owner_types_together(self):
        api = StubAPI(setup_keys=[key()], users=[user()])
        kinds = [k for k, _i, _lbl, _o in find_auto_group_owners(api, 'g-target')]
        assert kinds == ['setup key', 'user']

    def test_dict_shaped_auto_groups_are_matched(self):
        """The API may return related objects as dicts rather than id strings."""
        api = StubAPI(setup_keys=[key(auto_groups=[{'id': 'g-target'}])])
        assert len(find_auto_group_owners(api, 'g-target')) == 1

    def test_missing_auto_groups_is_tolerated(self):
        api = StubAPI(setup_keys=[{'id': 'k', 'name': 'n'}],
                      users=[{'id': 'u', 'email': 'e'}])
        assert find_auto_group_owners(api, 'g-target') == []

    def test_user_without_email_falls_back_to_name_then_id(self):
        api = StubAPI(users=[user(email=None, name='Named')])
        assert find_auto_group_owners(api, 'g-target')[0][2] == 'Named'
        api = StubAPI(users=[user(email=None, name=None)])
        assert find_auto_group_owners(api, 'g-target')[0][2] == 'user-1'


class TestUnpinGroup:

    def test_removes_only_the_target_group_from_a_key(self):
        api = StubAPI(setup_keys=[key()])
        unpin_group(api, 'g-target')
        assert len(api.key_updates) == 1
        _key_id, kwargs = api.key_updates[0]
        assert kwargs['auto_groups'] == ['g-other']

    def test_removes_only_the_target_group_from_a_user(self):
        api = StubAPI(users=[user()])
        unpin_group(api, 'g-target')
        _user_id, kwargs = api.user_updates[0]
        assert kwargs['auto_groups'] == ['g-other']

    def test_key_keeps_its_revoked_state(self):
        """A payload carrying only auto_groups would un-revoke the key, since
        the PUT is full-replace."""
        api = StubAPI(setup_keys=[key(revoked=True)])
        unpin_group(api, 'g-target')
        assert api.key_updates[0][1]['revoked'] is True

    def test_user_keeps_role_and_blocked_state(self):
        api = StubAPI(users=[user(role='user', is_blocked=True)])
        unpin_group(api, 'g-target')
        kwargs = api.user_updates[0][1]
        assert kwargs['role'] == 'user'
        assert kwargs['is_blocked'] is True

    def test_clearing_the_last_group_sends_an_empty_list(self):
        """Not None — that would omit the key and leave the pin in place."""
        api = StubAPI(setup_keys=[key(auto_groups=['g-target'])])
        unpin_group(api, 'g-target')
        assert api.key_updates[0][1]['auto_groups'] == []

    def test_owners_may_be_passed_in_to_avoid_a_second_lookup(self):
        api = StubAPI(setup_keys=[key()])
        owners = find_auto_group_owners(api, 'g-target')
        api.key_updates = []
        unpin_group(api, 'g-target', owners=owners)
        assert len(api.key_updates) == 1

    def test_nothing_is_written_when_no_owner_pins_the_group(self):
        api = StubAPI(setup_keys=[key(auto_groups=['g-other'])], users=[user(auto_groups=[])])
        unpin_group(api, 'g-target')
        assert api.key_updates == []
        assert api.user_updates == []

    def test_returns_the_owners_it_edited(self):
        api = StubAPI(setup_keys=[key()], users=[user()])
        assert len(unpin_group(api, 'g-target')) == 2


class TestRoleIsRequiredForAUserOwner:
    """``update_user`` drops a ``None`` role from the payload, and the user PUT
    is full-replace, so the API reads the role as empty and answers 422
    "invalid user role" -- saying nothing about the group being unpinned. The one
    field with no safe fallback."""

    def test_a_roleless_user_refuses_the_whole_sweep(self):
        api = StubAPI(users=[user(role=None)])
        with pytest.raises(_FailJson):
            unpin_group(api, 'g-target')

    def test_nothing_is_written_when_one_owner_is_unusable(self):
        """Checked for every owner before the first PUT, so the refusal cannot
        leave half the owners edited."""
        api = StubAPI(setup_keys=[key()], users=[user(role=None)])
        with pytest.raises(_FailJson):
            unpin_group(api, 'g-target')
        assert api.key_updates == []
        assert api.user_updates == []

    def test_the_failure_names_the_user_and_says_nothing_changed(self):
        api = StubAPI(users=[user(role=None)])
        with pytest.raises(_FailJson):
            unpin_group(api, 'g-target')
        msg = api.module.fail_msg
        assert 'se@example.com' in msg
        assert 'Nothing was changed' in msg

    def test_an_empty_role_is_treated_the_same_as_a_missing_one(self):
        api = StubAPI(users=[user(role='')])
        with pytest.raises(_FailJson):
            unpin_group(api, 'g-target')

    def test_a_setup_key_needs_no_role(self):
        api = StubAPI(setup_keys=[key()])
        unpin_group(api, 'g-target')
        assert len(api.key_updates) == 1


class TestProgressReporting:
    """A sweep that fails partway through has already edited some owners. The
    caller cannot recover which ones from the API, so the helper reports them
    as it goes."""

    def test_progress_records_each_edited_owner(self):
        api = StubAPI(setup_keys=[key()], users=[user()])
        progress = []
        unpin_group(api, 'g-target', progress=progress)
        assert [kind for kind, _i, _l, _o in progress] == ['setup key', 'user']

    def test_progress_holds_only_what_succeeded_before_a_failure(self):
        api = StubAPI(setup_keys=[key()], users=[user()], fail_on='user-1')
        progress = []
        with pytest.raises(NetBirdAPIError):
            unpin_group(api, 'g-target', progress=progress)
        assert [lbl for _k, _i, lbl, _o in progress] == ['enrolment']

    def test_progress_is_empty_when_the_first_owner_fails(self):
        api = StubAPI(setup_keys=[key()], fail_on='key-1')
        progress = []
        with pytest.raises(NetBirdAPIError):
            unpin_group(api, 'g-target', progress=progress)
        assert progress == []

    def test_the_error_names_the_owner_it_failed_on(self):
        """The progress list says what succeeded; it cannot say what broke."""
        api = StubAPI(setup_keys=[key()], users=[user()], fail_on='user-1')
        with pytest.raises(NetBirdAPIError) as excinfo:
            unpin_group(api, 'g-target')
        assert 'se@example.com' in str(excinfo.value)
        assert 'user' in str(excinfo.value)

    def test_the_original_status_and_response_survive(self):
        api = StubAPI(setup_keys=[key()], fail_on='key-1')
        with pytest.raises(NetBirdAPIError) as excinfo:
            unpin_group(api, 'g-target')
        assert excinfo.value.status_code == 500

    def test_the_underlying_message_is_kept(self):
        api = StubAPI(setup_keys=[key()], fail_on='key-1')
        with pytest.raises(NetBirdAPIError) as excinfo:
            unpin_group(api, 'g-target')
        assert 'boom' in str(excinfo.value)

    def test_progress_is_optional(self):
        api = StubAPI(setup_keys=[key()])
        unpin_group(api, 'g-target')
        assert len(api.key_updates) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
