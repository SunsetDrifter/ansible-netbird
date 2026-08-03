# -*- coding: utf-8 -*-
# Copyright: (c) 2024-2026, NetBird and contributors
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
"""Unit tests for DNS zone identification.

Run via:
    ansible-test units --docker default

A zone's name and its domain are the same thing in every case that works:
consumers that resolve zones by name, the NetBird Kubernetes operator among
them, cannot find a zone whose name has drifted from its domain. So ``name``
now defaults to ``domain``.

That default is applied before the lookup, which makes the fallback load
bearing rather than a nicety: a drifted zone -- the very thing the default
exists to heal -- is invisible to a name lookup, so declaring it from its
domain alone would create a second zone for the same domain, and
``state: absent`` would report success having deleted nothing.

``NetBirdAPI`` is patched, so no request is made.
"""

from __future__ import absolute_import, division, print_function
__metaclass__ = type

import pytest

from ansible_collections.community.ansible_netbird.plugins.modules import netbird_dns_zone


DRIFTED = {
    'id': 'zone-1',
    'name': 'Office Zone',
    'domain': 'corp.example.com',
    'enabled': True,
    'enable_search_domain': False,
    'distribution_groups': [],
}

ALIGNED = dict(DRIFTED, name='corp.example.com')

BASE_PARAMS = {
    'api_url': 'https://api.example.test',
    'api_token': 'token',
    'validate_certs': True,
    'timeout': 30,
    'state': 'present',
    'zone_id': None,
    'name': None,
    'domain': None,
    'enabled': True,
    'enable_search_domain': False,
    'distribution_groups': None,
    'records': None,
}


class _Exit(Exception):
    pass


class DummyModule:
    def __init__(self, params, check_mode=False):
        self.params = params
        self.check_mode = check_mode
        self.warnings = []
        self.exit_kwargs = None
        self.fail_kwargs = None

    def exit_json(self, **kwargs):
        self.exit_kwargs = kwargs
        raise _Exit()

    def fail_json(self, **kwargs):
        self.fail_kwargs = kwargs
        raise _Exit()

    def warn(self, msg):
        self.warnings.append(msg)


def run_module(monkeypatch, params, zones=None):
    """Drive netbird_dns_zone.main(), returning ``(module, calls)``."""
    zones = [DRIFTED] if zones is None else zones
    module = DummyModule(dict(BASE_PARAMS, **params))
    calls = []

    class FakeAPI:
        def __init__(self, *args, **kwargs):
            # The real client keeps a handle on the module so a lookup can fail
            # the task directly; an ambiguous match uses it.
            self.module = module

        def list_dns_zones(self):
            return list(zones), {}

        def get_dns_zone(self, zone_id):
            return zones[0], {}

        def create_dns_zone(self, **kwargs):
            calls.append(('create', kwargs))
            return dict(kwargs, id='zone-new'), {}

        def update_dns_zone(self, zone_id, **kwargs):
            calls.append(('update', zone_id, kwargs))
            return dict(zones[0], **kwargs), {}

        def delete_dns_zone(self, zone_id):
            calls.append(('delete', zone_id))
            return {}, {}

        def list_dns_zone_records(self, zone_id):
            return [], {}

    monkeypatch.setattr(netbird_dns_zone, 'AnsibleModule', lambda **kw: module)
    monkeypatch.setattr(netbird_dns_zone, 'NetBirdAPI', FakeAPI)

    with pytest.raises(_Exit):
        netbird_dns_zone.main()

    return module, calls


class TestDomainFallbackLookup:
    """The regression the fallback prevents: a duplicate zone for a domain
    that already has one."""

    def test_a_drifted_zone_is_found_from_its_domain_alone(self, monkeypatch):
        _module, calls = run_module(monkeypatch, {'domain': 'corp.example.com'})
        assert [c[0] for c in calls] != ['create'], \
            "created a second zone for a domain that already has one"

    def test_and_its_name_is_healed_to_the_domain(self, monkeypatch):
        """The point of the default: the drift is corrected rather than
        duplicated."""
        _module, calls = run_module(monkeypatch, {'domain': 'corp.example.com'})
        assert [c[0] for c in calls] == ['update'], calls
        assert calls[0][2]['name'] == 'corp.example.com'

    def test_the_match_is_reported(self, monkeypatch):
        module, _calls = run_module(monkeypatch, {'domain': 'corp.example.com'})
        assert any('domain' in w for w in module.warnings), module.warnings

    def test_absent_deletes_the_drifted_zone(self, monkeypatch):
        """Otherwise the task reports success having deleted nothing."""
        _module, calls = run_module(monkeypatch, {
            'domain': 'corp.example.com',
            'state': 'absent',
        })
        assert calls == [('delete', 'zone-1')], calls

    def test_an_aligned_zone_is_still_matched_by_name(self, monkeypatch):
        """The fallback must not be the only path that works."""
        _module, calls = run_module(monkeypatch, {
            'domain': 'corp.example.com',
        }, zones=[ALIGNED])
        assert calls == [], "an already-aligned zone needs no change"

    def test_no_warning_when_the_name_lookup_succeeded(self, monkeypatch):
        module, _calls = run_module(monkeypatch, {
            'domain': 'corp.example.com',
        }, zones=[ALIGNED])
        assert module.warnings == []

    def test_an_unknown_domain_still_creates(self, monkeypatch):
        _module, calls = run_module(monkeypatch, {'domain': 'new.example.com'})
        assert [c[0] for c in calls] == ['create'], calls
        assert calls[0][1]['name'] == 'new.example.com'

    def test_an_explicit_name_is_not_overridden(self, monkeypatch):
        """Matching by name comes first, so an explicit name still wins."""
        _module, calls = run_module(monkeypatch, {
            'name': 'Office Zone',
            'domain': 'corp.example.com',
        })
        assert calls == [], calls

    def test_a_name_differing_from_its_domain_warns(self, monkeypatch):
        module, _calls = run_module(monkeypatch, {
            'name': 'Office Zone',
            'domain': 'corp.example.com',
        })
        assert any('Kubernetes' in w or 'resolve zones by name' in w
                   for w in module.warnings), module.warnings

    def test_an_ambiguous_domain_fails_rather_than_picking_one(self, monkeypatch):
        """Duplicate domains are what the bug this fallback fixes used to
        create, so they are the likely state of an affected tenant. Picking one
        would rename or delete an arbitrary member of the pair."""
        twins = [DRIFTED, dict(DRIFTED, id='zone-2', name='Office Zone (copy)')]
        module, calls = run_module(monkeypatch, {
            'domain': 'corp.example.com',
        }, zones=twins)
        assert calls == [], "must not touch either zone"
        assert module.fail_kwargs is not None
        assert 'corp.example.com' in module.fail_kwargs['msg']

    def test_the_ambiguity_failure_names_both_candidates(self, monkeypatch):
        twins = [DRIFTED, dict(DRIFTED, id='zone-2', name='Office Zone (copy)')]
        module, _calls = run_module(monkeypatch, {
            'domain': 'corp.example.com',
        }, zones=twins)
        msg = module.fail_kwargs['msg']
        assert 'Office Zone' in msg and 'copy' in msg
        assert 'zone_id' in msg          # tells the caller how to disambiguate

    def test_absent_also_refuses_an_ambiguous_domain(self, monkeypatch):
        twins = [DRIFTED, dict(DRIFTED, id='zone-2', name='Office Zone (copy)')]
        _module, calls = run_module(monkeypatch, {
            'domain': 'corp.example.com',
            'state': 'absent',
        }, zones=twins)
        assert calls == [], "must not delete an arbitrary one of the pair"

    def test_one_match_among_other_domains_is_fine(self, monkeypatch):
        others = [dict(DRIFTED, id='z-9', name='Other', domain='other.example.com'),
                  DRIFTED]
        _module, calls = run_module(monkeypatch, {
            'domain': 'corp.example.com',
        }, zones=others)
        assert [c[0] for c in calls] == ['update'], calls

    def test_name_only_does_not_fall_back(self, monkeypatch):
        """With no domain there is nothing to fall back on, and a zone cannot
        be created either -- domain is required for that."""
        module, calls = run_module(monkeypatch, {'name': 'Nonexistent Zone'})
        assert calls == []
        assert module.fail_kwargs is not None
        assert 'domain' in module.fail_kwargs['msg']


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
