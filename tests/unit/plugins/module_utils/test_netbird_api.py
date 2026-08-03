# -*- coding: utf-8 -*-
# Copyright: (c) 2024-2026, NetBird and contributors
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
"""Unit tests for the shared module_utils helpers.

Run via:
    ansible-test units --docker default

These tests are deliberately scoped to pure-Python helpers that do not
make API calls. Integration coverage of API-touching code lives in the
external ansible-netbird-testing harness.
"""

from __future__ import absolute_import, division, print_function
__metaclass__ = type

import pytest

from ansible_collections.community.ansible_netbird.plugins.module_utils.netbird_api import (
    NetBirdAPIError,
    extract_ids,
    find_one_by_name,
)


class TestExtractIds:
    """`extract_ids` normalises the two shapes the API returns for related
    objects -- dicts with an `id` key, and plain ID strings -- into a flat
    list of strings so callers can safely use `set()` for comparison."""

    def test_empty_input_returns_empty_list(self):
        assert extract_ids([]) == []
        assert extract_ids(None) == []

    def test_dict_items_extract_id_field(self):
        items = [{"id": "abc", "name": "alpha"}, {"id": "def", "name": "beta"}]
        assert extract_ids(items) == ["abc", "def"]

    def test_string_items_pass_through(self):
        assert extract_ids(["abc", "def"]) == ["abc", "def"]

    def test_mixed_items_normalise(self):
        items = [{"id": "abc"}, "def", {"id": "ghi", "name": "x"}]
        assert extract_ids(items) == ["abc", "def", "ghi"]


class TestNetBirdAPIError:
    """The exception type used by the API client to surface HTTP / SSL /
    connectivity failures back to modules."""

    def test_message_is_propagated(self):
        e = NetBirdAPIError("boom")
        assert str(e) == "boom"
        assert e.message == "boom"

    def test_status_code_and_response_are_stored(self):
        e = NetBirdAPIError("nope", status_code=404, response={"error": "Not Found"})
        assert e.status_code == 404
        assert e.response == {"error": "Not Found"}

    def test_defaults_are_none(self):
        e = NetBirdAPIError("just a string")
        assert e.status_code is None
        assert e.response is None


class _FailJson(Exception):
    """Raised by the stub module so a failed lookup is observable."""


class _StubModule:
    def __init__(self):
        self.fail_msg = None

    def fail_json(self, msg=None, **kwargs):
        self.fail_msg = msg
        raise _FailJson(msg)


class _StubAPI:
    def __init__(self):
        self.module = _StubModule()


class TestFindOneByName:
    """Name lookups must refuse an ambiguous match rather than pick one.

    The API does not enforce unique names, so a by-name lookup can match
    several objects. Returning the first silently rewrites one the caller
    never identified.
    """

    def test_returns_the_single_match(self):
        api = _StubAPI()
        items = [{'name': 'a', 'id': '1'}, {'name': 'b', 'id': '2'}]
        assert find_one_by_name(api, items, 'b', 'group') == {'name': 'b', 'id': '2'}

    def test_returns_none_when_absent(self):
        api = _StubAPI()
        assert find_one_by_name(api, [{'name': 'a'}], 'missing', 'group') is None

    def test_tolerates_none_and_empty(self):
        api = _StubAPI()
        assert find_one_by_name(api, None, 'a', 'group') is None
        assert find_one_by_name(api, [], 'a', 'group') is None

    def test_fails_on_duplicate_names(self):
        api = _StubAPI()
        items = [{'name': 'dup', 'id': '1'}, {'name': 'dup', 'id': '2'}]
        with pytest.raises(_FailJson):
            find_one_by_name(api, items, 'dup', 'group')

    def test_failure_message_states_count_kind_and_remedy(self):
        api = _StubAPI()
        items = [{'name': 'dup', 'id': str(i)} for i in range(3)]
        with pytest.raises(_FailJson):
            find_one_by_name(api, items, 'dup', 'policies')
        msg = api.module.fail_msg
        assert '3' in msg
        assert 'policies' in msg
        assert 'dup' in msg
        assert 'id' in msg          # tells the caller how to disambiguate

    def test_the_kind_is_used_verbatim(self):
        """Callers pass the plural. Deriving it here is how you get "policys",
        and "setup keies" from the naive y-to-ies rule that fixes it."""
        api = _StubAPI()
        items = [{'name': 'dup'}, {'name': 'dup'}]
        with pytest.raises(_FailJson):
            find_one_by_name(api, items, 'dup', 'setup keys')
        assert 'setup keys named' in api.module.fail_msg

    def test_does_not_fail_on_a_duplicate_of_another_name(self):
        """Only the requested name matters — duplicates elsewhere are not
        this lookup's problem."""
        api = _StubAPI()
        items = [
            {'name': 'other', 'id': '1'},
            {'name': 'other', 'id': '2'},
            {'name': 'wanted', 'id': '3'},
        ]
        assert find_one_by_name(api, items, 'wanted', 'group')['id'] == '3'


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
