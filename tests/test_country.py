"""Country discovery stays offline and uses synthetic client/account fixtures."""
import io
import json
import urllib.error
import urllib.request
import urllib.response
from email.message import Message
from urllib.parse import parse_qs, quote, urlsplit
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from icsee_cloud import config, protocol
from icsee_cloud.cloud import ClientIdentity, CloudClient, CloudError

IDENTITY = ClientIdentity('fixture-uuid', 'fixture-key', 'fixture-secret', 7)
HOST = 'https://eu-ams.jftechws.com'
CAPS = 'https://caps-eu.jftechws.com'


def discovery_result(**entry_overrides):
    return {'code': 2000, 'data': {
        'defaultCountry': {'countryNo': 'CN', 'amsUrl': 'https://ams.jftechws.com'},
        'regionUrl': [{'countryNo': 'GB', 'amsUrl': HOST, 'capsUrl': CAPS, **entry_overrides}]}}


def install_transport(monkeypatch, result, encrypted=False, login_result=None):
    requests = []

    def respond(opener, request, timeout):
        requests.append(request)
        if '/phoneAndUrlByCountry/' in request.full_url:
            body = result
        elif '/loginExist/' in request.full_url:
            body = login_result if login_result is not None else {'code': 2000, 'data': {'accessToken': 'fixture-token'}}
        elif '/msdlistCode/' in request.full_url:
            body = {'code': 2000, 'data': {'mine': [], 'share': []}}
        else:
            pytest.fail('Unexpected endpoint')
        raw = json.dumps(body).encode()
        if encrypted:
            nonce = request.full_url.split('/')[-2]
            _, key = protocol.request_parameters(
                IDENTITY.uuid, IDENTITY.app_key, IDENTITY.app_secret, IDENTITY.moved_card, nonce)
            encoder = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
            raw = (encoder.update(protocol.padded_body(raw.decode())) + encoder.finalize()).hex().upper().encode()
        # Both plain JSON and encrypted responses can be URL-encoded by the service.
        return io.BytesIO(quote(raw.decode()).encode())

    monkeypatch.setattr(urllib.request.OpenerDirector, 'open', respond)
    return requests


@pytest.mark.parametrize('encrypted', [False, True])
def test_country_discovery_precedes_login_and_ignores_location_default(monkeypatch, encrypted):
    requests = install_transport(monkeypatch, discovery_result(), encrypted)
    cloud = CloudClient(IDENTITY, region='sa', country=' gb ')
    cloud.login('fixture@example.invalid', 'fixture-password')
    assert cloud.list_devices() == []
    assert cloud.host == HOST and cloud.caps_host == CAPS
    lookup, login, listing = requests
    assert urlsplit(lookup.full_url).netloc == 'ams.jftechws.com'
    assert parse_qs(lookup.data.decode(), keep_blank_values=True) == {'isoCode': ['GB'], 'urlVersion': ['']}
    assert 'fixture@example.invalid' not in lookup.full_url + lookup.data.decode()
    assert 'fixture-password' not in lookup.full_url + lookup.data.decode()
    assert 'authorization' not in dict((k.lower(), v) for k, v in lookup.header_items())
    assert urlsplit(login.full_url).netloc == 'eu-ams.jftechws.com'
    assert urlsplit(listing.full_url).netloc == 'eu-ams.jftechws.com'
    assert dict((k.lower(), v) for k, v in listing.header_items())['authorization'] == 'fixture-token'
    cloud.login('fixture@example.invalid', 'fixture-password')
    assert sum('/phoneAndUrlByCountry/' in request.full_url for request in requests) == 1


@pytest.mark.parametrize('result', [
    {'code': 4000, 'data': {}},
    {'code': 2000, 'data': None},
    {'code': 2000, 'data': {'regionUrl': None}},
    {'code': 2000, 'data': {'defaultCountry': {'countryNo': 'GB', 'amsUrl': HOST, 'capsUrl': CAPS}}},
    discovery_result(countryNo='US'),
    {'code': 2000, 'data': {'regionUrl': [
        {'countryNo': 'GB', 'amsUrl': HOST, 'capsUrl': CAPS},
        {'countryNo': 'GB', 'amsUrl': HOST, 'capsUrl': CAPS}]}},
])
def test_failed_or_ambiguous_discovery_never_attempts_login_or_region_fallback(monkeypatch, result):
    requests = install_transport(monkeypatch, result)
    cloud = CloudClient(IDENTITY, region='sa', country='GB')
    with pytest.raises(CloudError):
        cloud.login('fixture@example.invalid', 'fixture-password')
    assert len(requests) == 1 and '/phoneAndUrlByCountry/' in requests[0].full_url
    assert cloud.host == cloud.caps_host == cloud.token == ''


@pytest.mark.parametrize('field', ['amsUrl', 'capsUrl'])
@pytest.mark.parametrize('address', [
    None, 'http://eu-ams.jftechws.com', 'https://jftechws.com.example.invalid',
    'https://other.example.invalid', 'https://fixture@eu-ams.jftechws.com',
    'https://eu-ams.jftechws.com:444', 'https://eu-ams.jftechws.com/path',
    'https://eu-ams.jftechws.com?query=value', 'https://eu-ams.jftechws.com#fragment',
])
def test_invalid_server_addresses_cannot_receive_credentials(monkeypatch, field, address):
    requests = install_transport(monkeypatch, discovery_result(**{field: address}))
    cloud = CloudClient(IDENTITY, country='GB')
    with pytest.raises(CloudError, match='invalid server address'):
        cloud.login('fixture@example.invalid', 'fixture-password')
    assert len(requests) == 1 and cloud.host == cloud.caps_host == ''


@pytest.mark.parametrize('country', ['G', 'GBR', 'G1', 'https://example.invalid', None])
def test_invalid_country_rejected_before_network(monkeypatch, country):
    monkeypatch.setattr(urllib.request.OpenerDirector, 'open', lambda *args, **kw: pytest.fail('Network request'))
    with pytest.raises(CloudError, match='two-letter'):
        CloudClient(IDENTITY, country=country)


def test_missing_credentials_do_not_even_start_country_discovery(monkeypatch):
    requests = install_transport(monkeypatch, discovery_result())
    with pytest.raises(CloudError):
        CloudClient(IDENTITY, country='GB').login('', '')
    assert requests == []


def test_legacy_region_skips_discovery(monkeypatch):
    requests = install_transport(monkeypatch, discovery_result())
    cloud = CloudClient(IDENTITY, region='global')
    cloud.login('fixture@example.invalid', 'fixture-password')
    assert len(requests) == 1 and urlsplit(requests[0].full_url).netloc == 'rs.jftechws.com'
    assert cloud.caps_host == 'https://caps.jftechws.com'


def test_discovery_network_failure_is_sanitized_and_does_not_fall_back(monkeypatch):
    requests = []

    def fail(opener, request, timeout):
        requests.append(request)
        raise urllib.error.URLError('private-fixture-error-detail')

    monkeypatch.setattr(urllib.request.OpenerDirector, 'open', fail)
    with pytest.raises(CloudError, match='Cloud network request failed') as error:
        CloudClient(IDENTITY, country='GB').login('fixture@example.invalid', 'fixture-password')
    assert 'private-fixture-error-detail' not in str(error.value)
    assert len(requests) == 1


def test_redirects_cannot_forward_account_requests_to_another_server(monkeypatch):
    requests = []

    class RedirectingServer(urllib.request.BaseHandler):
        handler_order = 100

        def https_open(self, request):
            requests.append(request)
            headers = Message()
            headers['Location'] = 'https://other.example.invalid/fixture'
            response = urllib.response.addinfourl(io.BytesIO(b''), headers, request.full_url, 302)
            response.msg = 'Found'
            return response

    build_opener = urllib.request.build_opener
    monkeypatch.setattr(urllib.request, 'build_opener', lambda *handlers: build_opener(RedirectingServer(), *handlers))
    with pytest.raises(CloudError, match=r'Cloud HTTP failure \(302\)'):
        CloudClient(IDENTITY, region='global').login('fixture@example.invalid', 'fixture-password')
    assert len(requests) == 1
    assert urlsplit(requests[0].full_url).netloc == 'rs.jftechws.com'


def test_settings_loads_country_independently_of_legacy_region(monkeypatch, tmp_path):
    monkeypatch.setattr(config, 'ROOT', tmp_path)
    monkeypatch.setattr(config, 'local_values', lambda: {'ICSEE_COUNTRY': ' gb ', 'ICSEE_REGION': 'global'})
    settings = config.Settings.load()
    assert settings.country == 'GB' and settings.region == 'global'


def test_unset_routing_enables_automatic_default(monkeypatch, tmp_path):
    monkeypatch.setattr(config, 'ROOT', tmp_path)
    monkeypatch.setattr(config, 'local_values', lambda: {})
    settings = config.Settings.load()
    assert settings.country == '' and settings.region == 'auto'


def test_viewer_passes_discovered_servers_to_native_helper(monkeypatch, tmp_path):
    from icsee_cloud import viewer
    monkeypatch.setattr(viewer, 'ROOT', tmp_path)
    path = tmp_path / 'client.local.json'
    path.write_text(json.dumps({'uuid': IDENTITY.uuid, 'app_key': IDENTITY.app_key,
                               'app_secret': IDENTITY.app_secret, 'moved_card': IDENTITY.moved_card}))
    monkeypatch.setattr(viewer, 'SETTINGS', SimpleNamespace(
        identity_file=path, region='sa', country='GB', username='fixture@example.invalid',
        password='fixture-password', camera_name='Fixture camera', device_id='fixture-device'))
    monkeypatch.setattr(CloudClient, 'list_devices', lambda self: [
        {'nickname': 'Fixture%20camera', 'uuid': 'fixture-device'}])
    requests = install_transport(monkeypatch, discovery_result())
    result = viewer.LiveView(8766).account_config()
    assert result['miServer'] == HOST and result['capsServer'] == CAPS
    assert len(requests) == 2


def automatic_result():
    result = discovery_result()
    result['data']['defaultCountry'] = {'countryNo': 'GB', 'amsUrl': HOST, 'capsUrl': CAPS}
    # CN is a discovery request default, not necessarily the selected account region.
    result['data']['regionUrl'].append({'countryNo': 'CN', 'amsUrl': 'https://ams.jftechws.com',
                                       'capsUrl': 'https://caps.jftechws.com'})
    return result


@pytest.mark.parametrize('encrypted', [False, True])
def test_automatic_default_and_saved_country_work_without_an_explicit_country(monkeypatch, tmp_path, encrypted):
    cache = tmp_path / 'account.local.json'
    requests = install_transport(monkeypatch, automatic_result(), encrypted)
    first = CloudClient(IDENTITY, cache_path=cache)
    first.login('fixture@example.invalid', 'fixture-password')
    assert first.host == HOST and first.resolved_country == 'GB'
    assert parse_qs(requests[0].data.decode(), keep_blank_values=True)['isoCode'] == ['CN']
    saved = cache.read_text()
    assert 'fixture@example.invalid' not in saved and 'fixture-password' not in saved and 'fixture-token' not in saved

    moved = automatic_result()
    moved['data']['defaultCountry'] = {'countryNo': 'CN', 'amsUrl': 'https://ams.jftechws.com',
                                       'capsUrl': 'https://caps.jftechws.com'}
    requests = install_transport(monkeypatch, moved, encrypted)
    second = CloudClient(IDENTITY, cache_path=cache)
    second.login('fixture@example.invalid', 'fixture-password')
    assert second.host == HOST and second.resolved_country == 'GB'
    assert parse_qs(requests[0].data.decode(), keep_blank_values=True)['isoCode'] == ['GB']
    assert len(requests) == 2


def test_explicit_country_can_correct_a_saved_default(monkeypatch, tmp_path):
    cache = tmp_path / 'account.local.json'
    install_transport(monkeypatch, automatic_result())
    CloudClient(IDENTITY, cache_path=cache).login('fixture@example.invalid', 'fixture-password')
    result = automatic_result()
    requests = install_transport(monkeypatch, result)
    explicit = CloudClient(IDENTITY, country='CN', cache_path=cache)
    explicit.login('fixture@example.invalid', 'fixture-password')
    assert explicit.resolved_country == 'CN' and explicit.host == 'https://ams.jftechws.com'
    assert parse_qs(requests[0].data.decode(), keep_blank_values=True)['isoCode'] == ['CN']
    automatic = CloudClient(IDENTITY, cache_path=cache)
    automatic.login('fixture@example.invalid', 'fixture-password')
    assert automatic.resolved_country == 'CN'


def test_failed_login_does_not_save_an_unverified_country(monkeypatch, tmp_path):
    cache = tmp_path / 'account.local.json'
    requests = install_transport(monkeypatch, automatic_result(), login_result={'code': 4025, 'data': ''})
    with pytest.raises(CloudError, match='ICSEE_COUNTRY'):
        CloudClient(IDENTITY, cache_path=cache).login('fixture@example.invalid', 'fixture-password')
    assert len(requests) == 2 and not cache.exists()


@pytest.mark.parametrize('contents', ['{broken', '[]', '{"version":1,"accounts":[]}'])
def test_unreadable_cache_uses_automatic_discovery(monkeypatch, tmp_path, contents):
    cache = tmp_path / 'account.local.json'
    cache.write_text(contents)
    requests = install_transport(monkeypatch, automatic_result())
    cloud = CloudClient(IDENTITY, cache_path=cache)
    cloud.login('fixture@example.invalid', 'fixture-password')
    assert cloud.resolved_country == 'GB'
    assert parse_qs(requests[0].data.decode(), keep_blank_values=True)['isoCode'] == ['CN']


def test_readonly_cache_does_not_fail_a_successful_login(monkeypatch, tmp_path):
    from icsee_cloud import cloud as module
    install_transport(monkeypatch, automatic_result())

    def fail(*args):
        raise PermissionError('fixture read-only cache')

    monkeypatch.setattr(module.os, 'replace', fail)
    cloud = CloudClient(IDENTITY, cache_path=tmp_path / 'account.local.json')
    cloud.login('fixture@example.invalid', 'fixture-password')
    assert cloud.token == 'fixture-token'
    assert not list(tmp_path.glob('*.local.json'))


def test_switching_accounts_does_not_reuse_another_accounts_country(monkeypatch, tmp_path):
    result = automatic_result()
    requests = install_transport(monkeypatch, result)
    cloud = CloudClient(IDENTITY, cache_path=tmp_path / 'account.local.json')
    cloud.login('first-fixture@example.invalid', 'fixture-password')
    assert cloud.resolved_country == 'GB'
    result['data']['defaultCountry'] = {'countryNo': 'CN', 'amsUrl': 'https://ams.jftechws.com',
                                       'capsUrl': 'https://caps.jftechws.com'}
    cloud.login('second-fixture@example.invalid', 'fixture-password')
    assert cloud.resolved_country == 'CN'
    assert len(requests) == 4
    assert len(json.loads((tmp_path / 'account.local.json').read_text())['accounts']) == 2


def test_explicit_auto_setting_overrides_a_fixed_legacy_region(monkeypatch):
    install_transport(monkeypatch, automatic_result())
    cloud = CloudClient(IDENTITY, region='sa', country='auto')
    cloud.login('fixture@example.invalid', 'fixture-password')
    assert cloud.resolved_country == 'GB' and cloud.host == HOST


def test_missing_automatic_default_stops_without_login(monkeypatch):
    result = discovery_result()
    del result['data']['defaultCountry']
    requests = install_transport(monkeypatch, result)
    with pytest.raises(CloudError, match='no automatic default'):
        CloudClient(IDENTITY).login('fixture@example.invalid', 'fixture-password')
    assert len(requests) == 1
