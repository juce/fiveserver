"""Account lookup regression tests: share profile hydration, retain stored IDs."""

from types import SimpleNamespace

import pytest
from twisted.internet import defer

from fiveserver import errors
from fiveserver.config import FiveServerConfig
from fiveserver.model import user


def configuration(profile_indices):
    config = object.__new__(FiveServerConfig)
    account = user.User('existing-account-hash')
    account.id = 17
    account.username = 'ExactRegisteredID'
    profiles = []
    for index in profile_indices:
        profile = user.Profile(index)
        profile.id = 100 + index
        profile.userId = account.id
        profile.name = 'Slot_%d' % index
        profiles.append(profile)
    calls = []
    config.userData = SimpleNamespace(
        findByHash=lambda value: defer.succeed([account]),
        findByUsername=lambda value: defer.succeed([account]))

    def get_profiles(account_id):
        calls.append(account_id)
        return defer.succeed(profiles)

    config.profileData = SimpleNamespace(getByUserId=get_profiles)
    return config, account, profiles, calls


def resolved(result):
    values, failures = [], []
    result.addCallbacks(values.append, failures.append)
    assert not failures
    assert len(values) == 1
    return values[0]


@pytest.mark.parametrize('lookup', ['hash', 'username'])
@pytest.mark.parametrize('profile_indices', [[], [2], [0, 1, 2]])
def test_both_lookup_paths_share_the_three_profile_slot_hydration(lookup, profile_indices):
    config, account, profiles, calls = configuration(profile_indices)
    stored_hash = account.hash
    result = (config.getUser(stored_hash) if lookup == 'hash'
              else config.getUserByUsername(account.username))
    assert resolved(result) is account
    assert calls == [account.id]
    assert account.hash == stored_hash
    assert [profile.index for profile in account.profiles] == [0, 1, 2]
    for index in range(3):
        profile = account.profiles[index]
        assert profile.userId == account.id
        if index in profile_indices:
            assert profile is profiles[profile_indices.index(index)]
        else:
            assert profile.id == 0 and profile.name == ''


@pytest.mark.parametrize('database_returns_account', [False, True])
def test_username_lookup_rejects_missing_and_case_insensitive_match_privately(database_returns_account):
    config, account, _, calls = configuration([])
    username = 'exactregisteredid'
    config.userData.findByUsername = lambda value: defer.succeed(
        [account] if database_returns_account else [])
    failures = []
    config.getUserByUsername(username).addErrback(failures.append)
    assert len(failures) == 1 and failures[0].check(errors.UnknownUserError)
    assert username not in str(failures[0].value)
    assert account.hash not in str(failures[0].value)
    assert calls == []
    assert account.profiles == []


def test_legacy_hash_lookup_still_rejects_a_missing_account():
    config, _, _, calls = configuration([])
    config.userData.findByHash = lambda value: defer.succeed([])
    failures = []
    config.getUser('missing-hash').addErrback(failures.append)
    assert len(failures) == 1 and failures[0].check(errors.UnknownUserError)
    assert calls == []
