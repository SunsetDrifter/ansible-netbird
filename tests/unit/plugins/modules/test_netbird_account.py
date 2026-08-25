# -*- coding: utf-8 -*-
# Copyright: (c) 2024-2026, NetBird and contributors
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
"""Unit tests for the netbird_account module's settings update payload.

Run via:
    ansible-test units --docker default

The account settings PUT is FULL-REPLACE on the NetBird API, and the nested
``extra`` object has no per-field nil-check server-side: any subfield absent
from the JSON body decodes to its zero value and is written unconditionally.
A task naming only one ``extra_*`` parameter must therefore not clear the
others -- the module has to merge the desired ``extra`` update against the
account's current ``extra`` settings at the subkey level, not just splice the
whole nested object in wholesale.

Verified against the handler in
management/server/http/handlers/accounts/accounts_handler.go: none of
AccountExtraSettings' fields are pointers, and
``updateAccountRequestSettings`` copies all of them across unconditionally
whenever ``req.Settings.Extra != nil``.

``NetBirdAPI`` is patched, so no request is made. These assert on the
arguments the module hands the API client, which is where the defect lives.
"""

from __future__ import absolute_import, division, print_function
__metaclass__ = type

import pytest

from ansible_collections.community.ansible_netbird.plugins.modules import netbird_account


EXISTING_ACCOUNT = {
    'id': 'acc-1',
    'settings': {
        'peer_login_expiration_enabled': True,
        'peer_login_expiration': 86400,
        'extra': {
            'peer_approval_enabled': True,
            'user_approval_required': True,
            'network_traffic_logs_enabled': False,
            'network_traffic_logs_groups': ['group-1'],
            'network_traffic_packet_counter_enabled': False,
        },
    },
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
    """Drive netbird_account.main() with AnsibleModule and NetBirdAPI patched.

    Returns the recorded update_account ``settings`` dict, or None if no
    update was made.
    """
    existing = EXISTING_ACCOUNT if existing is None else existing
    full = {
        'api_url': 'https://api.example.test',
        'api_token': 'token',
        'validate_certs': True,
        'timeout': 30,
        'state': 'present',
        'account_id': None,
        'peer_login_expiration_enabled': None,
        'peer_login_expiration': None,
        'peer_inactivity_expiration_enabled': None,
        'peer_inactivity_expiration': None,
        'regular_users_view_blocked': None,
        'groups_propagation_enabled': None,
        'jwt_groups_enabled': None,
        'jwt_groups_claim_name': None,
        'jwt_allow_groups': None,
        'routing_peer_dns_resolution_enabled': None,
        'dns_domain': None,
        'network_range': None,
        'network_range_v6': None,
        'ipv6_enabled_groups': None,
        'lazy_connection_enabled': None,
        'extra_peer_approval_enabled': None,
        'extra_user_approval_required': None,
        'extra_network_traffic_logs_enabled': None,
        'extra_network_traffic_logs_groups': None,
        'extra_network_traffic_packet_counter_enabled': None,
        'auto_update_always': None,
        'auto_update_version': None,
        'peer_expose_enabled': None,
        'peer_expose_groups': None,
    }
    full.update(params)
    module = DummyModule(full)

    recorded = {}

    class FakeAPI:
        def __init__(self, *args, **kwargs):
            pass

        def list_accounts(self):
            return [existing], {}

        def update_account(self, account_id, data):
            recorded['account_id'] = account_id
            recorded.update(data)
            return dict(existing, **data), {}

    monkeypatch.setattr(netbird_account, 'AnsibleModule', lambda **kw: module)
    monkeypatch.setattr(netbird_account, 'NetBirdAPI', FakeAPI)

    with pytest.raises(SystemExit):
        netbird_account.main()

    return recorded.get('settings')


class TestExtraSettingsMergePreservesOmittedSubfields:
    """A task naming one extra_* option must not clear the others."""

    def test_single_extra_flag_preserves_the_rest(self, monkeypatch):
        settings = run_module(monkeypatch, {
            'extra_network_traffic_logs_enabled': True,
        })
        assert settings is not None, "expected an update to be sent"
        assert settings['extra'] == {
            'peer_approval_enabled': True,
            'user_approval_required': True,
            'network_traffic_logs_enabled': True,
            'network_traffic_logs_groups': ['group-1'],
            'network_traffic_packet_counter_enabled': False,
        }

    def test_different_single_extra_flag_preserves_the_rest(self, monkeypatch):
        settings = run_module(monkeypatch, {
            'extra_peer_approval_enabled': False,
        })
        assert settings is not None, "expected an update to be sent"
        assert settings['extra']['user_approval_required'] is True
        assert settings['extra']['network_traffic_logs_groups'] == ['group-1']
        assert settings['extra']['peer_approval_enabled'] is False

    def test_top_level_fields_still_carry_over_current_values(self, monkeypatch):
        """The shallow merge for non-nested fields was already correct --
        must not regress while fixing the nested `extra` case."""
        settings = run_module(monkeypatch, {
            'extra_peer_approval_enabled': False,
        })
        assert settings['peer_login_expiration_enabled'] is True
        assert settings['peer_login_expiration'] == 86400

    def test_no_extra_param_leaves_current_extra_untouched(self, monkeypatch):
        settings = run_module(monkeypatch, {
            'peer_login_expiration': 604800,
        })
        assert settings is not None, "expected an update to be sent"
        assert settings['extra'] == EXISTING_ACCOUNT['settings']['extra']

    def test_account_with_no_current_extra_settings(self, monkeypatch):
        """An account that has never set any extra field returns no `extra`
        key at all (server omits it) -- the merge must not blow up on a
        missing key."""
        existing = {
            'id': 'acc-2',
            'settings': {'peer_login_expiration_enabled': False},
        }
        settings = run_module(monkeypatch, {
            'extra_peer_approval_enabled': True,
        }, existing=existing)
        assert settings is not None, "expected an update to be sent"
        assert settings['extra'] == {'peer_approval_enabled': True}


class TestNoSpuriousUpdate:
    """Requesting values identical to the current state must not update."""

    def test_identical_task_makes_no_update_call(self, monkeypatch):
        settings = run_module(monkeypatch, {
            'peer_login_expiration_enabled': True,
            'peer_login_expiration': 86400,
        })
        assert settings is None, f"unexpected update sent: {settings}"
