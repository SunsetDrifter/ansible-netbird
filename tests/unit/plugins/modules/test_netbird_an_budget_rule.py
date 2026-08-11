# -*- coding: utf-8 -*-
# Copyright: (c) 2026, Community
# GNU General Public License v3.0+
"""Unit tests for the netbird_an_budget_rule module.

Covers create, idempotent no-change, target_groups update,
delete, and delete-noop.
``NetBirdAPI`` is patched so no network request is made.
"""

from __future__ import absolute_import, division, print_function
__metaclass__ = type

import pytest

from ansible_collections.community.ansible_netbird.plugins.modules import netbird_an_budget_rule


EXISTING_RULE = {
    'id': 'rule-1',
    'name': 'dev-team-limits',
    'enabled': True,
    'target_groups': ['grp-dev'],
    'target_users': ['user-1'],
    'limits': {
        'token_limit': {
            'enabled': True,
            'group_cap': 100000,
            'user_cap': 10000,
            'window_seconds': 3600,
        },
        'budget_limit': {
            'enabled': False,
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


def run_module(monkeypatch, params, existing_rules=None,
               check_mode=False):
    """Drive netbird_an_budget_rule.main() with patched deps.

    Returns (module, recorded_calls) where recorded_calls tracks
    which API methods were called and with what arguments.
    """
    if existing_rules is None:
        existing_rules = []

    full = {
        'api_url': 'https://api.example.test',
        'api_token': 'token',
        'validate_certs': True,
        'timeout': 30,
        'state': 'present',
        'rule_id': None,
        'name': None,
        'enabled': None,
        'target_groups': None,
        'target_users': None,
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
            return list(existing_rules), {}

        def post(self, endpoint, data=None):
            recorded['calls'].append(('post', data))
            new = dict(EXISTING_RULE)
            new.update(data)
            new['id'] = 'rule-new'
            return new, {}

        def put(self, endpoint, data=None):
            recorded['calls'].append(('put', data))
            updated = dict(EXISTING_RULE)
            updated.update(data)
            return updated, {}

        def delete(self, endpoint):
            recorded['calls'].append(('delete', endpoint))
            return None, {}

    monkeypatch.setattr(
        netbird_an_budget_rule, 'AnsibleModule', lambda **kw: module)
    monkeypatch.setattr(
        netbird_an_budget_rule, 'NetBirdAPI', FakeAPI)
    monkeypatch.setattr(
        netbird_an_budget_rule, 'find_one_by_name', _find_by_name)

    with pytest.raises(SystemExit):
        netbird_an_budget_rule.main()

    return module, recorded


class TestCreate:

    def test_create_new_rule(self, monkeypatch):
        module, recorded = run_module(monkeypatch, {
            'name': 'dev-team-limits',
            'enabled': True,
            'target_groups': ['grp-dev'],
            'target_users': ['user-1'],
            'limits': {
                'token_limit': {
                    'enabled': True,
                    'group_cap': 100000,
                    'user_cap': 10000,
                    'window_seconds': 3600,
                },
                'budget_limit': {
                    'enabled': False,
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
            'name': 'dev-team-limits',
            'enabled': True,
            'target_groups': ['grp-dev'],
            'target_users': ['user-1'],
            'limits': {
                'token_limit': {
                    'enabled': True,
                    'group_cap': 100000,
                    'user_cap': 10000,
                    'window_seconds': 3600,
                },
                'budget_limit': {
                    'enabled': False,
                },
            },
        }, existing_rules=[EXISTING_RULE])
        assert module.exit_kwargs['changed'] is False
        assert not any(
            isinstance(c, tuple) and c[0] in ('post', 'put')
            for c in recorded['calls'])

    def test_different_target_groups_triggers_update(self, monkeypatch):
        module, recorded = run_module(monkeypatch, {
            'name': 'dev-team-limits',
            'enabled': True,
            'target_groups': ['grp-dev', 'grp-qa'],
            'target_users': ['user-1'],
            'limits': {
                'token_limit': {
                    'enabled': True,
                    'group_cap': 100000,
                    'user_cap': 10000,
                    'window_seconds': 3600,
                },
                'budget_limit': {
                    'enabled': False,
                },
            },
        }, existing_rules=[EXISTING_RULE])
        assert module.exit_kwargs['changed'] is True
        assert any(
            isinstance(c, tuple) and c[0] == 'put'
            for c in recorded['calls'])


class TestLimitsCarryForward:

    def test_omitted_budget_limit_preserved(self, monkeypatch):
        """Sending only token_limit should not clear budget_limit."""
        existing = dict(EXISTING_RULE)
        existing['limits'] = {
            'token_limit': {
                'enabled': True,
                'group_cap': 100000,
                'user_cap': 10000,
                'window_seconds': 3600,
            },
            'budget_limit': {
                'enabled': True,
                'group_cap_usd': 50.0,
                'user_cap_usd': 5.0,
                'window_seconds': 3600,
            },
        }
        module, recorded = run_module(monkeypatch, {
            'name': 'dev-team-limits',
            'limits': {
                'token_limit': {
                    'enabled': True,
                    'group_cap': 200000,
                    'user_cap': 10000,
                    'window_seconds': 3600,
                },
            },
        }, existing_rules=[existing])
        assert module.exit_kwargs['changed'] is True
        put_calls = [c for c in recorded['calls']
                     if isinstance(c, tuple) and c[0] == 'put']
        assert len(put_calls) == 1
        sent_limits = put_calls[0][1]['limits']
        assert sent_limits['budget_limit']['enabled'] is True
        assert sent_limits['budget_limit']['group_cap_usd'] == 50.0
        assert sent_limits['token_limit']['group_cap'] == 200000

    def test_omitted_enabled_preserved(self, monkeypatch):
        """Omitting enabled should not reset a disabled rule to enabled."""
        existing = dict(EXISTING_RULE)
        existing['enabled'] = False
        module, recorded = run_module(monkeypatch, {
            'name': 'dev-team-limits',
            'target_groups': ['grp-dev', 'grp-qa'],
        }, existing_rules=[existing])
        assert module.exit_kwargs['changed'] is True
        put_calls = [c for c in recorded['calls']
                     if isinstance(c, tuple) and c[0] == 'put']
        assert len(put_calls) == 1
        assert put_calls[0][1].get('enabled', 'MISSING') is not True


class TestDelete:

    def test_delete_existing(self, monkeypatch):
        module, recorded = run_module(monkeypatch, {
            'name': 'dev-team-limits',
            'state': 'absent',
        }, existing_rules=[EXISTING_RULE])
        assert module.exit_kwargs['changed'] is True
        assert any(
            isinstance(c, tuple) and c[0] == 'delete'
            for c in recorded['calls'])

    def test_delete_nonexistent_noop(self, monkeypatch):
        module, recorded = run_module(monkeypatch, {
            'name': 'dev-team-limits',
            'state': 'absent',
        })
        assert module.exit_kwargs['changed'] is False
        assert not any(
            isinstance(c, tuple) and c[0] == 'delete'
            for c in recorded['calls'])
