# -*- coding: utf-8 -*-
# Copyright: (c) 2026, Community
# GNU General Public License v3.0+
"""Unit tests for the netbird_an_settings module.

Covers update, no-change when same, and check-mode.
The settings resource is an account-level singleton with only
GET and PUT -- no create or delete.
``NetBirdAPI`` is patched so no network request is made.
"""

from __future__ import absolute_import, division, print_function
__metaclass__ = type

import pytest

from ansible_collections.community.ansible_netbird.plugins.modules import netbird_an_settings


EXISTING_SETTINGS = {
    'enable_log_collection': False,
    'enable_prompt_collection': False,
    'redact_pii': False,
    'access_log_retention_days': 30,
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


def run_module(monkeypatch, params, current_settings=None,
               check_mode=False):
    """Drive netbird_an_settings.main() with patched deps.

    Returns (module, recorded_calls) where recorded_calls tracks
    which API methods were called and with what arguments.
    """
    if current_settings is None:
        current_settings = dict(EXISTING_SETTINGS)

    full = {
        'api_url': 'https://api.example.test',
        'api_token': 'token',
        'validate_certs': True,
        'timeout': 30,
        'state': 'present',
        'enable_log_collection': None,
        'enable_prompt_collection': None,
        'redact_pii': None,
        'access_log_retention_days': None,
    }
    full.update(params)
    module = DummyModule(full, check_mode=check_mode)
    recorded = {'calls': []}

    class FakeAPI:

        def __init__(self, *args, **kwargs):
            pass

        def get(self, endpoint):
            recorded['calls'].append(('get', endpoint))
            return dict(current_settings), {}

        def put(self, endpoint, data=None):
            recorded['calls'].append(('put', data))
            updated = dict(current_settings)
            updated.update(data)
            return updated, {}

    monkeypatch.setattr(
        netbird_an_settings, 'AnsibleModule', lambda **kw: module)
    monkeypatch.setattr(
        netbird_an_settings, 'NetBirdAPI', FakeAPI)

    with pytest.raises(SystemExit):
        netbird_an_settings.main()

    return module, recorded


class TestSettings:

    def test_update_settings(self, monkeypatch):
        module, recorded = run_module(monkeypatch, {
            'enable_log_collection': True,
        })
        assert module.exit_kwargs['changed'] is True
        put_calls = [c for c in recorded['calls']
                     if isinstance(c, tuple) and c[0] == 'put']
        assert len(put_calls) == 1
        sent = put_calls[0][1]
        assert sent['enable_log_collection'] is True
        # Omitted fields must carry the existing values forward.
        assert sent['access_log_retention_days'] == 30
        assert sent['redact_pii'] is False

    def test_no_change_when_same(self, monkeypatch):
        module, recorded = run_module(monkeypatch, {
            'enable_log_collection': False,
        })
        assert module.exit_kwargs['changed'] is False
        assert not any(
            isinstance(c, tuple) and c[0] == 'put'
            for c in recorded['calls'])

    def test_check_mode(self, monkeypatch):
        module, recorded = run_module(monkeypatch, {
            'enable_log_collection': True,
        }, check_mode=True)
        assert module.exit_kwargs['changed'] is True
        assert not any(
            isinstance(c, tuple) and c[0] == 'put'
            for c in recorded['calls'])
