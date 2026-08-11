# -*- coding: utf-8 -*-
# Copyright: (c) 2026, Community
# GNU General Public License v3.0+
"""Unit tests for the netbird_an_policy module.

Covers create, idempotent no-change, source_groups update,
limits change update, delete, and delete-noop.
``NetBirdAPI`` is patched so no network request is made.
"""

from __future__ import absolute_import, division, print_function
__metaclass__ = type

import pytest

from ansible_collections.community.ansible_netbird.plugins.modules import netbird_an_policy


EXISTING_POLICY = {
    'id': 'pol-1',
    'name': 'Default AI policy',
    'description': 'Allow developers access',
    'enabled': True,
    'source_groups': ['grp-dev'],
    'destination_provider_ids': ['ainp_1'],
    'guardrail_ids': ['gr-1'],
    'limits': {
        'token_limit': {
            'enabled': True,
            'group_cap': 100000,
            'user_cap': 10000,
            'window_seconds': 3600,
        },
        'budget_limit': {
            'enabled': False,
            'group_cap_usd': 0,
            'user_cap_usd': 0,
            'window_seconds': 60,
        },
    },
}


class DummyModule:
    """Minimal AnsibleModule stand-in."""

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


def _find_by_name(_api, items, name, _plural):
    """Simple find_one_by_name replacement for tests."""
    matches = [i for i in (items or []) if i.get('name') == name]
    return matches[0] if matches else None


def run_module(monkeypatch, params, existing_policies=None,
               check_mode=False):
    """Drive netbird_an_policy.main() with patched deps.

    Returns (module, recorded_calls) where recorded_calls tracks
    which API methods were called and with what arguments.
    """
    if existing_policies is None:
        existing_policies = []

    full = {
        'api_url': 'https://api.example.test',
        'api_token': 'token',
        'validate_certs': True,
        'timeout': 30,
        'state': 'present',
        'policy_id': None,
        'name': None,
        'description': '',
        'enabled': True,
        'source_groups': None,
        'destination_provider_ids': None,
        'guardrail_ids': None,
        'limits': None,
    }
    full.update(params)
    module = DummyModule(full, check_mode=check_mode)
    recorded = {'calls': []}

    class FakeAPI:

        def __init__(self, *args, **kwargs):
            pass

        def get(self, endpoint):
            recorded['calls'].append(('get', endpoint))
            return list(existing_policies), {}

        def post(self, endpoint, data=None):
            recorded['calls'].append(('post', data))
            new = dict(EXISTING_POLICY)
            new.update(data)
            new['id'] = 'pol-new'
            return new, {}

        def put(self, endpoint, data=None):
            recorded['calls'].append(('put', data))
            updated = dict(EXISTING_POLICY)
            updated.update(data)
            return updated, {}

        def delete(self, endpoint):
            recorded['calls'].append(('delete', endpoint))
            return None, {}

    monkeypatch.setattr(
        netbird_an_policy, 'AnsibleModule', lambda **kw: module)
    monkeypatch.setattr(
        netbird_an_policy, 'NetBirdAPI', FakeAPI)
    monkeypatch.setattr(
        netbird_an_policy, 'find_one_by_name', _find_by_name)

    with pytest.raises(SystemExit):
        netbird_an_policy.main()

    return module, recorded


class TestCreate:

    def test_create_new_policy(self, monkeypatch):
        module, recorded = run_module(monkeypatch, {
            'name': 'Default AI policy',
            'description': 'Allow developers access',
            'source_groups': ['grp-dev'],
            'destination_provider_ids': ['ainp_1'],
            'guardrail_ids': ['gr-1'],
            'limits': {
                'token_limit': {
                    'enabled': True,
                    'group_cap': 100000,
                    'user_cap': 10000,
                    'window_seconds': 3600,
                },
            },
        })
        assert module.exit_kwargs['changed'] is True
        assert any(
            isinstance(c, tuple) and c[0] == 'post'
            for c in recorded['calls'])


class TestIdempotent:

    def test_existing_same_config_no_change(self, monkeypatch):
        module, recorded = run_module(monkeypatch, {
            'name': 'Default AI policy',
            'description': 'Allow developers access',
            'source_groups': ['grp-dev'],
            'destination_provider_ids': ['ainp_1'],
            'guardrail_ids': ['gr-1'],
            'limits': {
                'token_limit': {
                    'enabled': True,
                    'group_cap': 100000,
                    'user_cap': 10000,
                    'window_seconds': 3600,
                },
                'budget_limit': {
                    'enabled': False,
                    'group_cap_usd': 0,
                    'user_cap_usd': 0,
                    'window_seconds': 60,
                },
            },
        }, existing_policies=[EXISTING_POLICY])
        assert module.exit_kwargs['changed'] is False
        assert not any(
            isinstance(c, tuple) and c[0] in ('post', 'put')
            for c in recorded['calls'])

    def test_different_source_groups_triggers_update(self, monkeypatch):
        module, recorded = run_module(monkeypatch, {
            'name': 'Default AI policy',
            'description': 'Allow developers access',
            'source_groups': ['grp-dev', 'grp-qa'],
            'destination_provider_ids': ['ainp_1'],
            'guardrail_ids': ['gr-1'],
        }, existing_policies=[EXISTING_POLICY])
        assert module.exit_kwargs['changed'] is True
        assert any(
            isinstance(c, tuple) and c[0] == 'put'
            for c in recorded['calls'])

    def test_limits_change_triggers_update(self, monkeypatch):
        module, recorded = run_module(monkeypatch, {
            'name': 'Default AI policy',
            'description': 'Allow developers access',
            'source_groups': ['grp-dev'],
            'destination_provider_ids': ['ainp_1'],
            'guardrail_ids': ['gr-1'],
            'limits': {
                'token_limit': {
                    'enabled': True,
                    'group_cap': 100000,
                    'user_cap': 50000,
                    'window_seconds': 3600,
                },
                'budget_limit': {
                    'enabled': False,
                    'group_cap_usd': 0,
                    'user_cap_usd': 0,
                    'window_seconds': 60,
                },
            },
        }, existing_policies=[EXISTING_POLICY])
        assert module.exit_kwargs['changed'] is True
        assert any(
            isinstance(c, tuple) and c[0] == 'put'
            for c in recorded['calls'])


class TestDelete:

    def test_delete_existing(self, monkeypatch):
        module, recorded = run_module(monkeypatch, {
            'name': 'Default AI policy',
            'state': 'absent',
        }, existing_policies=[EXISTING_POLICY])
        assert module.exit_kwargs['changed'] is True
        assert any(
            isinstance(c, tuple) and c[0] == 'delete'
            for c in recorded['calls'])

    def test_delete_nonexistent_noop(self, monkeypatch):
        module, recorded = run_module(monkeypatch, {
            'name': 'Default AI policy',
            'state': 'absent',
        })
        assert module.exit_kwargs['changed'] is False
        assert not any(
            isinstance(c, tuple) and c[0] == 'delete'
            for c in recorded['calls'])
