# -*- coding: utf-8 -*-
# Copyright: (c) 2026, Community
# GNU General Public License v3.0+
"""Unit tests for the netbird_an_guardrail module.

Covers create, check-mode create, idempotent no-change, update on
changed checks, delete, and delete-nonexistent noop.
``NetBirdAPI`` is patched so no network request is made.
"""

from __future__ import absolute_import, division, print_function
__metaclass__ = type

import pytest

from ansible_collections.community.ansible_netbird.plugins.modules import netbird_an_guardrail


EXISTING_GUARDRAIL = {
    'id': 'gr-1',
    'name': 'production-guardrail',
    'description': 'Restrict models in production',
    'checks': {
        'model_allowlist': {
            'enabled': True,
            'models': ['gpt-4', 'claude-3-opus'],
        },
        'prompt_capture': {
            'enabled': True,
            'redact_pii': True,
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


def run_module(monkeypatch, params, existing_guardrails=None,
               check_mode=False):
    """Drive netbird_an_guardrail.main() with patched deps.

    Returns (module, recorded_calls) where recorded_calls tracks
    which API methods were called and with what arguments.
    """
    if existing_guardrails is None:
        existing_guardrails = []

    full = {
        'api_url': 'https://api.example.test',
        'api_token': 'token',
        'validate_certs': True,
        'timeout': 30,
        'state': 'present',
        'guardrail_id': None,
        'name': None,
        'description': '',
        'checks': None,
    }
    full.update(params)
    module = DummyModule(full, check_mode=check_mode)
    recorded = {'calls': []}

    class FakeAPI:

        def __init__(self, *args, **kwargs):
            pass

        def get(self, endpoint):
            recorded['calls'].append(('get', endpoint))
            return list(existing_guardrails), {}

        def post(self, endpoint, data=None):
            recorded['calls'].append(('post', data))
            new = dict(EXISTING_GUARDRAIL)
            new.update(data)
            new['id'] = 'gr-new'
            return new, {}

        def put(self, endpoint, data=None):
            recorded['calls'].append(('put', data))
            updated = dict(EXISTING_GUARDRAIL)
            updated.update(data)
            return updated, {}

        def delete(self, endpoint):
            recorded['calls'].append(('delete', endpoint))
            return None, {}

    monkeypatch.setattr(
        netbird_an_guardrail, 'AnsibleModule', lambda **kw: module)
    monkeypatch.setattr(
        netbird_an_guardrail, 'NetBirdAPI', FakeAPI)
    monkeypatch.setattr(
        netbird_an_guardrail, 'find_one_by_name', _find_by_name)

    with pytest.raises(SystemExit):
        netbird_an_guardrail.main()

    return module, recorded


class TestCreate:

    def test_create_new_guardrail(self, monkeypatch):
        module, recorded = run_module(monkeypatch, {
            'name': 'production-guardrail',
            'description': 'Restrict models in production',
            'checks': {
                'model_allowlist': {
                    'enabled': True,
                    'models': ['gpt-4', 'claude-3-opus'],
                },
                'prompt_capture': {
                    'enabled': True,
                    'redact_pii': True,
                },
            },
        })
        assert module.exit_kwargs['changed'] is True
        assert any(
            isinstance(c, tuple) and c[0] == 'post'
            for c in recorded['calls'])

    def test_create_check_mode(self, monkeypatch):
        module, recorded = run_module(monkeypatch, {
            'name': 'production-guardrail',
            'checks': {
                'model_allowlist': {
                    'enabled': True,
                    'models': ['gpt-4'],
                },
            },
        }, check_mode=True)
        assert module.exit_kwargs['changed'] is True
        assert not any(
            isinstance(c, tuple) and c[0] == 'post'
            for c in recorded['calls'])


class TestIdempotent:

    def test_existing_same_checks_no_change(self, monkeypatch):
        module, recorded = run_module(monkeypatch, {
            'name': 'production-guardrail',
            'description': 'Restrict models in production',
            'checks': {
                'model_allowlist': {
                    'enabled': True,
                    'models': ['gpt-4', 'claude-3-opus'],
                },
                'prompt_capture': {
                    'enabled': True,
                    'redact_pii': True,
                },
            },
        }, existing_guardrails=[EXISTING_GUARDRAIL])
        assert module.exit_kwargs['changed'] is False
        assert not any(
            isinstance(c, tuple) and c[0] in ('post', 'put')
            for c in recorded['calls'])

    def test_different_checks_triggers_update(self, monkeypatch):
        module, recorded = run_module(monkeypatch, {
            'name': 'production-guardrail',
            'description': 'Restrict models in production',
            'checks': {
                'model_allowlist': {
                    'enabled': True,
                    'models': ['gpt-4', 'claude-3-opus', 'claude-3-sonnet'],
                },
                'prompt_capture': {
                    'enabled': True,
                    'redact_pii': True,
                },
            },
        }, existing_guardrails=[EXISTING_GUARDRAIL])
        assert module.exit_kwargs['changed'] is True
        assert any(
            isinstance(c, tuple) and c[0] == 'put'
            for c in recorded['calls'])


class TestDelete:

    def test_delete_existing(self, monkeypatch):
        module, recorded = run_module(monkeypatch, {
            'name': 'production-guardrail',
            'state': 'absent',
        }, existing_guardrails=[EXISTING_GUARDRAIL])
        assert module.exit_kwargs['changed'] is True
        assert any(
            isinstance(c, tuple) and c[0] == 'delete'
            for c in recorded['calls'])

    def test_delete_nonexistent_is_noop(self, monkeypatch):
        module, recorded = run_module(monkeypatch, {
            'name': 'production-guardrail',
            'state': 'absent',
        })
        assert module.exit_kwargs['changed'] is False
        assert not any(
            isinstance(c, tuple) and c[0] == 'delete'
            for c in recorded['calls'])
