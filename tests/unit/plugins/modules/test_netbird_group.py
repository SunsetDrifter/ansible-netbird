# -*- coding: utf-8 -*-
# Copyright: (c) 2024-2026, NetBird and contributors
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
"""Unit tests for the netbird_group module's update payload.

Run via:
    ansible-test units --docker default

The group PUT is FULL-REPLACE on the NetBird API: a key absent from the
payload is cleared, not left alone. ``NetBirdAPI.update_group`` only sends the
keys it receives a non-None value for, so the module must substitute the
existing value for anything the task did not mention — otherwise an ordinary
peers edit or rename silently detaches the group's network resources.

Verified against a live tenant: a group holding one network resource, sent
``PUT {name, peers}``, came back with ``resources: null``.

``NetBirdAPI`` is patched, so no request is made. These assert on the
arguments the module hands the API client, which is where the defect lives.
"""

from __future__ import absolute_import, division, print_function
__metaclass__ = type

import pytest

from ansible_collections.community.ansible_netbird.plugins.modules import netbird_group


EXISTING = {
    'id': 'grp-1',
    'name': 'demo-clients',
    'peers': [{'id': 'peer-1'}],
    'resources': [{'id': 'res-1', 'type': 'host'}],
}


class DummyModule:
    """Minimal AnsibleModule stand-in capturing the exit path."""

    def __init__(self, params, check_mode=False):
        self.params = params
        self.check_mode = check_mode
        self.exit_kwargs = None
        self.fail_kwargs = None

    def exit_json(self, **kwargs):
        self.exit_kwargs = kwargs
        raise SystemExit(0)

    def fail_json(self, **kwargs):
        self.fail_kwargs = kwargs
        raise SystemExit(1)

    def warn(self, msg):
        pass


def run_module(monkeypatch, params, existing=None):
    """Drive netbird_group.main() with AnsibleModule and NetBirdAPI patched.

    Returns the recorded update_group kwargs, or None if no update was made.
    """
    existing = EXISTING if existing is None else existing
    full = {
        'api_url': 'https://api.example.test',
        'api_token': 'token',
        'validate_certs': True,
        'timeout': 30,
        'state': 'present',
        'group_id': None,
        'name': None,
        'peers': None,
        'resources': None,
    }
    full.update(params)
    module = DummyModule(full)

    recorded = {}

    class FakeAPI:
        def __init__(self, *args, **kwargs):
            pass

        def get_group(self, group_id):
            return existing, {}

        def list_groups(self):
            return [existing], {}

        def update_group(self, group_id, **kwargs):
            recorded['group_id'] = group_id
            recorded.update(kwargs)
            return dict(existing, **{k: v for k, v in kwargs.items() if v is not None}), {}

        def create_group(self, **kwargs):  # pragma: no cover - not exercised here
            recorded['created'] = kwargs
            return existing, {}

    monkeypatch.setattr(netbird_group, 'AnsibleModule', lambda **kw: module)
    monkeypatch.setattr(netbird_group, 'NetBirdAPI', FakeAPI)

    with pytest.raises(SystemExit):
        netbird_group.main()

    return recorded or None


class TestUpdatePreservesOmittedFields:
    """A partial task must not become a destructive full-replace."""

    def test_peers_edit_sends_back_existing_resources(self, monkeypatch):
        recorded = run_module(monkeypatch, {
            'group_id': 'grp-1',
            'name': 'demo-clients',
            'peers': ['peer-1', 'peer-2'],
        })
        assert recorded is not None, "expected an update to be sent"
        assert recorded['resources'] == [{'id': 'res-1', 'type': 'host'}]

    def test_rename_sends_back_existing_peers_and_resources(self, monkeypatch):
        recorded = run_module(monkeypatch, {
            'group_id': 'grp-1',
            'name': 'demo-clients-renamed',
        })
        assert recorded is not None, "expected an update to be sent"
        assert recorded['name'] == 'demo-clients-renamed'
        assert recorded['peers'] == ['peer-1']
        assert recorded['resources'] == [{'id': 'res-1', 'type': 'host'}]

    def test_peers_edit_sends_back_existing_name(self, monkeypatch):
        """Addressed by id with no name given: the name must be carried over,
        not omitted — the API requires it and would otherwise reject or blank
        it."""
        recorded = run_module(monkeypatch, {
            'group_id': 'grp-1',
            'peers': [],
        })
        assert recorded is not None, "expected an update to be sent"
        assert recorded['name'] == 'demo-clients'

    def test_resources_returned_as_null_are_treated_as_empty(self, monkeypatch):
        """The API answers with JSON null, not [], for an empty resources
        list. A `.get('resources', [])` default never fires on a
        present-and-None key, so the substitution must use `or []`."""
        existing = dict(EXISTING, resources=None)
        recorded = run_module(monkeypatch, {
            'group_id': 'grp-1',
            'name': 'demo-clients-renamed',
        }, existing=existing)
        assert recorded is not None, "expected an update to be sent"
        assert recorded['resources'] == []

    def test_explicit_resources_still_win(self, monkeypatch):
        """Substitution is a fallback, never an override — a task that does
        specify resources must be honoured, including clearing them."""
        recorded = run_module(monkeypatch, {
            'group_id': 'grp-1',
            'name': 'demo-clients',
            'resources': [],
        })
        assert recorded is not None, "expected an update to be sent"
        assert recorded['resources'] == []


class TestNoSpuriousUpdate:
    """Substituting existing values must not invent changes."""

    def test_identical_task_makes_no_update_call(self, monkeypatch):
        recorded = run_module(monkeypatch, {
            'group_id': 'grp-1',
            'name': 'demo-clients',
            'peers': ['peer-1'],
        })
        assert recorded is None, f"unexpected update sent: {recorded}"
