# -*- coding: utf-8 -*-
# Copyright: (c) 2026, Community
# GNU General Public License v3.0+
"""Unit tests for the netbird_service_domain module.

Run via:
    ansible-test units --docker default

Covers create, delete, idempotent no-change, target_cluster change,
rollback validation, and re-validate on existing unvalidated domains.
``NetBirdAPI`` is patched so no network request is made.
"""

from __future__ import absolute_import, division, print_function
__metaclass__ = type

import pytest

from ansible_collections.community.ansible_netbird.plugins.modules import netbird_service_domain


EXISTING_DOMAIN = {
    'id': 'dom-1',
    'domain': 'app.example.com',
    'validated': True,
    'type': 'custom',
    'target_cluster': 'eu.proxy.netbird.io',
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


def run_module(monkeypatch, params, existing_domains=None):
    """Drive netbird_service_domain.main() with patched deps.

    Returns (module, recorded_calls) where recorded_calls tracks
    which API methods were called and with what arguments.
    """
    if existing_domains is None:
        existing_domains = []

    full = {
        'api_url': 'https://api.example.test',
        'api_token': 'token',
        'validate_certs': True,
        'timeout': 30,
        'state': 'present',
        'domain': None,
        'target_cluster': None,
        'validate': False,
    }
    full.update(params)
    module = DummyModule(full)
    recorded = {'calls': []}

    class FakeAPI:
        def __init__(self, *args, **kwargs):
            pass

        def list_service_domains(self):
            recorded['calls'].append('list')
            return list(existing_domains), {}

        def create_service_domain(self, data):
            recorded['calls'].append(('create', data))
            new = dict(EXISTING_DOMAIN, **data)
            new['id'] = 'dom-new'
            return new, {}

        def delete_service_domain(self, domain_id):
            recorded['calls'].append(('delete', domain_id))
            return None, {}

        def validate_service_domain(self, domain_id):
            recorded['calls'].append(('validate', domain_id))
            return {}, {}

    monkeypatch.setattr(
        netbird_service_domain, 'AnsibleModule', lambda **kw: module)
    monkeypatch.setattr(
        netbird_service_domain, 'NetBirdAPI', FakeAPI)

    with pytest.raises(SystemExit):
        netbird_service_domain.main()

    return module, recorded


class TestCreateDomain:

    def test_create_new_domain(self, monkeypatch):
        module, recorded = run_module(monkeypatch, {
            'domain': 'app.example.com',
            'target_cluster': 'eu.proxy.netbird.io',
        })
        assert module.exit_kwargs['changed'] is True
        assert ('create', {
            'domain': 'app.example.com',
            'target_cluster': 'eu.proxy.netbird.io',
        }) in recorded['calls']

    def test_create_with_validate(self, monkeypatch):
        module, recorded = run_module(monkeypatch, {
            'domain': 'app.example.com',
            'target_cluster': 'eu.proxy.netbird.io',
            'validate': True,
        })
        assert module.exit_kwargs['changed'] is True
        assert any(c[0] == 'validate' for c in recorded['calls']
                   if isinstance(c, tuple))


class TestIdempotent:

    def test_existing_domain_same_cluster_no_change(self, monkeypatch):
        module, recorded = run_module(monkeypatch, {
            'domain': 'app.example.com',
            'target_cluster': 'eu.proxy.netbird.io',
        }, existing_domains=[EXISTING_DOMAIN])
        assert module.exit_kwargs['changed'] is False
        assert not any(
            isinstance(c, tuple) and c[0] == 'create'
            for c in recorded['calls'])

    def test_different_cluster_triggers_recreate(self, monkeypatch):
        module, recorded = run_module(monkeypatch, {
            'domain': 'app.example.com',
            'target_cluster': 'us.proxy.netbird.io',
        }, existing_domains=[EXISTING_DOMAIN])
        assert module.exit_kwargs['changed'] is True
        assert ('delete', 'dom-1') in recorded['calls']
        assert any(
            isinstance(c, tuple) and c[0] == 'create'
            for c in recorded['calls'])


class TestValidateExistingDomain:

    def test_validate_unvalidated_domain(self, monkeypatch):
        unvalidated = dict(EXISTING_DOMAIN, validated=False)
        module, recorded = run_module(monkeypatch, {
            'domain': 'app.example.com',
            'target_cluster': 'eu.proxy.netbird.io',
            'validate': True,
        }, existing_domains=[unvalidated])
        assert module.exit_kwargs['changed'] is True
        assert ('validate', 'dom-1') in recorded['calls']

    def test_validate_already_validated_is_noop(self, monkeypatch):
        module, recorded = run_module(monkeypatch, {
            'domain': 'app.example.com',
            'target_cluster': 'eu.proxy.netbird.io',
            'validate': True,
        }, existing_domains=[EXISTING_DOMAIN])
        assert module.exit_kwargs['changed'] is False
        assert not any(
            isinstance(c, tuple) and c[0] == 'validate'
            for c in recorded['calls'])

    def test_validate_unvalidated_check_mode(self, monkeypatch):
        unvalidated = dict(EXISTING_DOMAIN, validated=False)
        full = {
            'api_url': 'https://api.example.test',
            'api_token': 'token',
            'validate_certs': True,
            'timeout': 30,
            'state': 'present',
            'domain': 'app.example.com',
            'target_cluster': 'eu.proxy.netbird.io',
            'validate': True,
        }
        module = DummyModule(full, check_mode=True)
        recorded = {'calls': []}

        class FakeAPI:
            def __init__(self, *a, **kw):
                pass
            def list_service_domains(self):
                recorded['calls'].append('list')
                return [unvalidated], {}
            def validate_service_domain(self, did):
                recorded['calls'].append(('validate', did))
                return {}, {}

        monkeypatch.setattr(
            netbird_service_domain, 'AnsibleModule', lambda **kw: module)
        monkeypatch.setattr(
            netbird_service_domain, 'NetBirdAPI', FakeAPI)

        with pytest.raises(SystemExit):
            netbird_service_domain.main()

        assert module.exit_kwargs['changed'] is True
        assert not any(
            isinstance(c, tuple) and c[0] == 'validate'
            for c in recorded['calls'])


class TestRollbackValidation:

    def test_rollback_triggers_validation(self, monkeypatch):
        full = {
            'api_url': 'https://api.example.test',
            'api_token': 'token',
            'validate_certs': True,
            'timeout': 30,
            'state': 'present',
            'domain': 'app.example.com',
            'target_cluster': 'us.proxy.netbird.io',
            'validate': True,
        }
        module = DummyModule(full)
        recorded = {'calls': [], 'create_count': 0}

        class FakeAPI:
            def __init__(self, *a, **kw):
                pass
            def list_service_domains(self):
                recorded['calls'].append('list')
                return [EXISTING_DOMAIN], {}
            def delete_service_domain(self, did):
                recorded['calls'].append(('delete', did))
                return None, {}
            def create_service_domain(self, data):
                recorded['create_count'] += 1
                if recorded['create_count'] == 1:
                    raise netbird_service_domain.NetBirdAPIError(
                        'cluster unavailable', status_code=400)
                recorded['calls'].append(('create', data))
                rb = dict(EXISTING_DOMAIN, id='dom-rb', **data)
                return rb, {}
            def validate_service_domain(self, did):
                recorded['calls'].append(('validate', did))
                return {}, {}

        monkeypatch.setattr(
            netbird_service_domain, 'AnsibleModule', lambda **kw: module)
        monkeypatch.setattr(
            netbird_service_domain, 'NetBirdAPI', FakeAPI)

        with pytest.raises(SystemExit):
            netbird_service_domain.main()

        assert module.fail_kwargs is not None
        assert 'rolled back' in module.fail_kwargs['msg']
        assert module.fail_kwargs.get('domain_info', {}).get('id') == 'dom-rb'
        assert ('validate', 'dom-rb') in recorded['calls']


class TestDeleteDomain:

    def test_delete_existing(self, monkeypatch):
        module, recorded = run_module(monkeypatch, {
            'domain': 'app.example.com',
            'state': 'absent',
        }, existing_domains=[EXISTING_DOMAIN])
        assert module.exit_kwargs['changed'] is True
        assert ('delete', 'dom-1') in recorded['calls']

    def test_delete_nonexistent_is_noop(self, monkeypatch):
        module, recorded = run_module(monkeypatch, {
            'domain': 'app.example.com',
            'state': 'absent',
        })
        assert module.exit_kwargs['changed'] is False
        assert not any(
            isinstance(c, tuple) and c[0] == 'delete'
            for c in recorded['calls'])
