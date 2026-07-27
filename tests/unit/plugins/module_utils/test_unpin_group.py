# -*- coding: utf-8 -*-
# Copyright: (c) 2024-2026, NetBird and contributors
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
"""Unit tests for the auto_groups unpin helpers.

Run via:
    ansible-test units --docker default

The API refuses to delete a group that any setup key's or any user's
``auto_groups`` still references, answering 400 without naming the owner. Both
owner types must be swept: a caller handling only setup keys still hits the 400
on the user case.

These PUTs are full-replace, so each owner has to be re-sent with its other
mutable fields intact — omitting them would un-revoke a key or strip a user's
role while unpinning.

The API client is stubbed; no request is made.
"""

from __future__ import absolute_import, division, print_function
__metaclass__ = type

import pytest

from ansible_collections.community.ansible_netbird.plugins.module_utils.netbird_api import (
    find_auto_group_owners,
    unpin_group,
)


class StubAPI:
    def __init__(self, setup_keys=None, users=None):
        self._keys = setup_keys or []
        self._users = users or []
        self.key_updates = []
        self.user_updates = []

    def list_setup_keys(self):
        return self._keys, {}

    def list_users(self):
        return self._users, {}

    def update_setup_key(self, key_id, **kwargs):
        self.key_updates.append((key_id, kwargs))
        return {}, {}

    def update_user(self, user_id, **kwargs):
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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
