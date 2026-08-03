# -*- coding: utf-8 -*-
# Copyright: (c) 2024-2026, NetBird and contributors
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
"""Unit tests for the netbird_service target payload.

Run via:
    ansible-test units --docker default

Two target options are legal for some service modes and rejected outright for
others, and the API answers 400 rather than ignoring the field:

- ``path_rewrite`` is refused on TCP, UDP and TLS ("path_rewrite is not
  supported for L4 services"), so a default that always sends it makes every
  L4 service impossible to create;
- ``proxy_protocol`` is refused on HTTP and on UDP, so it is only usable on
  TCP and TLS.

Between them there is no mode where both defaults can be sent, which is why
``build_target`` takes the service mode.

``build_target`` is pure; no request is made.
"""

from __future__ import absolute_import, division, print_function
__metaclass__ = type

import pytest

from ansible_collections.community.ansible_netbird.plugins.modules.netbird_service import (
    build_target,
    targets_differ,
)


def target(**overrides):
    """A target as the argspec hands it over: every suboption with a default
    is already filled in, and the ones without are present as None."""
    base = {
        'target_id': 'res-1',
        'target_type': 'subnet',
        'host': '10.0.0.1',
        'port': 8080,
        'path': '/',
        'protocol': 'http',
        'enabled': True,
        'direct_upstream': True,
        'skip_tls_verify': False,
        'path_rewrite': None,
        'proxy_protocol': False,
    }
    base.update(overrides)
    return base


class TestPathRewriteByMode:

    @pytest.mark.parametrize('mode', ['tcp', 'udp', 'tls'])
    def test_omitted_for_l4_when_unset(self, mode):
        """The regression: sending it made every L4 service a 400."""
        options = build_target(target(), mode)['options']
        assert 'path_rewrite' not in options

    def test_defaults_to_preserve_for_http(self):
        """Unchanged for HTTP services, where the value is meaningful and
        where dropping it would change how paths reach the upstream."""
        assert build_target(target(), 'http')['options']['path_rewrite'] == 'preserve'

    def test_defaults_to_preserve_when_no_mode_is_given(self):
        assert build_target(target())['options']['path_rewrite'] == 'preserve'

    @pytest.mark.parametrize('mode', ['tcp', 'udp', 'tls', 'http'])
    def test_an_explicit_value_is_always_sent(self, mode):
        """Not silently dropped for L4 — the operator asked for something the
        API refuses, and should see the API say so rather than have the
        request rewritten underneath them."""
        options = build_target(target(path_rewrite='default'), mode)['options']
        assert options['path_rewrite'] == 'default'


class TestHost:

    def test_omitted_when_unset(self):
        """A peer target has no backend address of its own, so an empty host
        would be wrong rather than merely redundant."""
        assert 'host' not in build_target(target(host=None, target_type='peer'))

    def test_omitted_when_empty(self):
        assert 'host' not in build_target(target(host=''))

    def test_sent_when_given(self):
        assert build_target(target(host='10.0.0.9'))['host'] == '10.0.0.9'


class TestProxyProtocol:

    def test_defaults_to_false(self):
        """False is safe to send on every mode: the API only rejects a true
        value on HTTP and UDP."""
        assert build_target(target())['options']['proxy_protocol'] is False

    def test_sent_when_enabled(self):
        assert build_target(target(proxy_protocol=True), 'tcp')['options']['proxy_protocol'] is True


class TestRemainingPayload:

    def test_carries_the_identifying_fields(self):
        payload = build_target(target(target_type='cluster'), 'tcp')
        assert payload['target_id'] == 'res-1'
        assert payload['target_type'] == 'cluster'
        assert payload['port'] == 8080

    def test_defaults_are_applied_for_a_bare_dict(self):
        """Reached when the caller is not the argspec — the comparator builds
        targets from server responses."""
        payload = build_target({'target_id': 'r', 'port': 1}, 'http')
        assert payload['target_type'] == 'subnet'
        assert payload['path'] == '/'
        assert payload['protocol'] == 'http'
        assert payload['enabled'] is True
        assert payload['options']['direct_upstream'] is True
        assert payload['options']['skip_tls_verify'] is False


def sent(**overrides):
    """A target as it went to the API / comes back from it."""
    base = {
        'target_id': 'res-1',
        'target_type': 'cluster',
        'host': '10.0.0.1',
        'port': 8080,
        'path': '/',
        'protocol': 'http',
        'enabled': True,
        'options': {'direct_upstream': True, 'skip_tls_verify': False,
                    'path_rewrite': 'preserve', 'proxy_protocol': False},
    }
    base.update(overrides)
    return base


class TestHostChangeDetection:
    """`host` is left out of the match key for non-subnet targets because
    ``replaceHostByLookup`` overwrites it on every read path. That rewrite is
    unconditional -- it does not consult ``direct_upstream`` -- so for peer,
    host and domain targets the returned host is never the operator's value and
    comparing it would never converge.

    Cluster is the exception the lookup skips, which is also the one type where
    host is required and operator-meaningful.
    """

    def test_an_edited_cluster_host_is_detected(self):
        """The regression: silently ignored, so the playbook and the server
        disagreed permanently."""
        assert targets_differ([sent()], [sent(host='10.0.0.2')]) is True

    def test_an_unchanged_cluster_host_is_not_a_change(self):
        assert targets_differ([sent()], [sent()]) is False

    @pytest.mark.parametrize('target_type', ['peer', 'host', 'domain'])
    def test_a_rewritten_host_never_reads_as_drift(self, target_type):
        """replaceHostByLookup replaces the host with the peer IP or the
        resource's address on every read, whatever was sent and whatever
        direct_upstream says. Comparing it would mean changed=true on every run,
        forever, with the PUT unable to make it converge."""
        current = sent(target_type=target_type, host='100.64.0.7')
        desired = sent(target_type=target_type, host='10.0.0.9')
        assert targets_differ([current], [desired]) is False

    @pytest.mark.parametrize('direct', [True, False])
    def test_the_peer_case_holds_either_way_on_direct_upstream(self, direct):
        """The validator's comment says an operator host is honoured when
        direct_upstream is set. The read path does not implement that, so the
        flag must not gate the comparison."""
        opts = {'direct_upstream': direct, 'skip_tls_verify': False,
                'path_rewrite': 'preserve', 'proxy_protocol': False}
        current = sent(target_type='peer', host='100.64.0.7', options=opts)
        desired = sent(target_type='peer', host='10.0.0.9', options=dict(opts))
        assert targets_differ([current], [desired]) is False

    def test_a_subnet_host_change_is_still_a_key_change(self):
        """Subnet keeps host in the match key, so this reads as a different
        target rather than an edited one -- either way, a change."""
        assert targets_differ([sent(target_type='subnet')],
                              [sent(target_type='subnet', host='10.0.0.2')]) is True

    def test_clearing_a_cluster_host_is_detected(self):
        assert targets_differ([sent()], [sent(host=None)]) is True

    def test_other_option_changes_are_unaffected(self):
        assert targets_differ([sent()], [sent(protocol='https')]) is True
        assert targets_differ([sent()], [sent(enabled=False)]) is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
