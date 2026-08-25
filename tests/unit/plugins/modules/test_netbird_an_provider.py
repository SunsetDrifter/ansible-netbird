# -*- coding: utf-8 -*-
# Copyright: (c) 2026, Community
# GNU General Public License v3.0+
"""Unit tests for the netbird_an_provider module.

Covers create, create-requires-api_key, idempotent no-change,
upstream_url update, api_key-not-compared, delete, and delete-noop.
``NetBirdAPI`` is patched so no network request is made.
"""

from __future__ import absolute_import, division, print_function
__metaclass__ = type

import pytest

from ansible_collections.community.ansible_netbird.plugins.modules import netbird_an_provider


EXISTING_PROVIDER = {
    'id': 'ainp_1',
    'name': 'OpenAI Production',
    'provider_id': 'openai_api',
    'upstream_url': 'https://api.openai.com/v1',
    'enabled': True,
    'skip_tls_verification': False,
    'metadata_disabled': False,
    'identity_header_user_id': '',
    'identity_header_groups': '',
    'models': [
        {
            'id': 'gpt-4o',
            'input_per_1k': 0.0025,
            'output_per_1k': 0.01,
        },
    ],
    'extra_values': {},
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


def run_module(monkeypatch, params, existing_providers=None,
               check_mode=False):
    """Drive netbird_an_provider.main() with patched deps.

    Returns (module, recorded_calls) where recorded_calls tracks
    which API methods were called and with what arguments.
    """
    if existing_providers is None:
        existing_providers = []

    full = {
        'api_url': 'https://api.example.test',
        'api_token': 'token',
        'validate_certs': True,
        'timeout': 30,
        'state': 'present',
        'provider_id': None,
        'name': None,
        'catalog_provider_id': None,
        'upstream_url': None,
        'api_key': None,
        'models': None,
        'extra_values': None,
        'identity_header_user_id': None,
        'identity_header_groups': None,
        'enabled': True,
        'skip_tls_verification': False,
        'metadata_disabled': False,
    }
    full.update(params)
    module = DummyModule(full, check_mode=check_mode)
    recorded = {'calls': []}

    class FakeAPI:

        def __init__(self, *args, **kwargs):
            pass

        def list_an_providers(self):
            recorded['calls'].append('list')
            return list(existing_providers), {}

        def get_an_provider(self, provider_id):
            recorded['calls'].append(('get', provider_id))
            for p in existing_providers:
                if p['id'] == provider_id:
                    return p, {}
            raise netbird_an_provider.NetBirdAPIError(
                'not found', status_code=404)

        def create_an_provider(self, data):
            recorded['calls'].append(('create', data))
            new = dict(EXISTING_PROVIDER)
            new.update(data)
            new['id'] = 'ainp_new'
            return new, {}

        def update_an_provider(self, provider_id, data):
            recorded['calls'].append(('update', provider_id, data))
            updated = dict(EXISTING_PROVIDER)
            updated.update(data)
            return updated, {}

        def delete_an_provider(self, provider_id):
            recorded['calls'].append(('delete', provider_id))
            return None, {}

    monkeypatch.setattr(
        netbird_an_provider, 'AnsibleModule', lambda **kw: module)
    monkeypatch.setattr(
        netbird_an_provider, 'NetBirdAPI', FakeAPI)
    monkeypatch.setattr(
        netbird_an_provider, 'find_one_by_name', _find_by_name)

    with pytest.raises(SystemExit):
        netbird_an_provider.main()

    return module, recorded


class TestCreate:

    def test_create_new_provider(self, monkeypatch):
        module, recorded = run_module(monkeypatch, {
            'name': 'OpenAI Production',
            'catalog_provider_id': 'openai_api',
            'upstream_url': 'https://api.openai.com/v1',
            'api_key': 'sk-test-key',
            'models': [
                {
                    'id': 'gpt-4o',
                    'input_per_1k': 0.0025,
                    'output_per_1k': 0.01,
                },
            ],
        })
        assert module.exit_kwargs['changed'] is True
        assert any(
            isinstance(c, tuple) and c[0] == 'create'
            for c in recorded['calls'])

    def test_create_requires_api_key(self, monkeypatch):
        module, recorded = run_module(monkeypatch, {
            'name': 'OpenAI Production',
            'catalog_provider_id': 'openai_api',
            'upstream_url': 'https://api.openai.com/v1',
        })
        assert module.fail_kwargs is not None
        assert 'api_key' in module.fail_kwargs['msg']


class TestIdempotent:

    def test_existing_same_config_no_change(self, monkeypatch):
        module, recorded = run_module(monkeypatch, {
            'name': 'OpenAI Production',
            'catalog_provider_id': 'openai_api',
            'upstream_url': 'https://api.openai.com/v1',
            'models': [
                {
                    'id': 'gpt-4o',
                    'input_per_1k': 0.0025,
                    'output_per_1k': 0.01,
                },
            ],
        }, existing_providers=[EXISTING_PROVIDER])
        assert module.exit_kwargs['changed'] is False
        assert not any(
            isinstance(c, tuple) and c[0] in ('create', 'update')
            for c in recorded['calls'])

    def test_different_upstream_triggers_update(self, monkeypatch):
        module, recorded = run_module(monkeypatch, {
            'name': 'OpenAI Production',
            'upstream_url': 'https://api.openai.com/v2',
        }, existing_providers=[EXISTING_PROVIDER])
        assert module.exit_kwargs['changed'] is True
        assert any(
            isinstance(c, tuple) and c[0] == 'update'
            for c in recorded['calls'])


class TestApiKey:

    def test_api_key_not_compared(self, monkeypatch):
        """api_key is never returned by the API, so providing it with
        no other changes should not trigger an update."""
        module, recorded = run_module(monkeypatch, {
            'name': 'OpenAI Production',
            'catalog_provider_id': 'openai_api',
            'upstream_url': 'https://api.openai.com/v1',
            'api_key': 'sk-new-key',
            'models': [
                {
                    'id': 'gpt-4o',
                    'input_per_1k': 0.0025,
                    'output_per_1k': 0.01,
                },
            ],
        }, existing_providers=[EXISTING_PROVIDER])
        assert module.exit_kwargs['changed'] is False
        assert not any(
            isinstance(c, tuple) and c[0] == 'update'
            for c in recorded['calls'])


class TestDelete:

    def test_delete_existing(self, monkeypatch):
        module, recorded = run_module(monkeypatch, {
            'name': 'OpenAI Production',
            'state': 'absent',
        }, existing_providers=[EXISTING_PROVIDER])
        assert module.exit_kwargs['changed'] is True
        assert ('delete', 'ainp_1') in recorded['calls']

    def test_delete_nonexistent_noop(self, monkeypatch):
        module, recorded = run_module(monkeypatch, {
            'name': 'OpenAI Production',
            'state': 'absent',
        })
        assert module.exit_kwargs['changed'] is False
        assert not any(
            isinstance(c, tuple) and c[0] == 'delete'
            for c in recorded['calls'])
