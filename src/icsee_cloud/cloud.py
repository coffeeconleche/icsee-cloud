"""Signed/encrypted account API; raw account responses are never written to disk."""
import json
import hashlib
import os
import re
import ssl
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote_plus, unquote, urlencode, urlsplit
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from . import protocol

REGIONS = {
    'sa': ('https://sa-ams.jftechws.com', 'https://caps-sa.jftechws.com'),
    'global': ('https://rs.jftechws.com', 'https://caps.jftechws.com'),
}
DISCOVERY_HOST = 'https://ams.jftechws.com'


class CloudError(RuntimeError):
    """Sanitized cloud failure, without tokens, response bodies or request URLs."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Select the region before login, never through an account-request redirect.
        return None


def _server_origin(value):
    """Only accept vendor HTTPS origins before using account credentials there."""
    if not isinstance(value, str):
        raise CloudError('Country discovery returned an invalid server address')
    try:
        parts = urlsplit(value)
        valid = (parts.scheme == 'https' and parts.hostname
                 and parts.hostname.endswith('.jftechws.com')
                 and not parts.username and not parts.password
                 and parts.port in (None, 443) and parts.path in ('', '/')
                 and not parts.query and not parts.fragment)
    except ValueError:
        valid = False
    if not valid:
        raise CloudError('Country discovery returned an invalid server address')
    return f'https://{parts.hostname}'


@dataclass(frozen=True)
class ClientIdentity:
    uuid: str = field(repr=False)
    app_key: str = field(repr=False)
    app_secret: str = field(repr=False)
    moved_card: int = field(repr=False)

    @classmethod
    def load(cls, path):
        if not path.exists(): raise CloudError('Configure a local client identity file')
        data = json.loads(path.read_text(encoding='utf8'))
        return cls(data['uuid'], data['app_key'], data['app_secret'], int(data['moved_card']))


class CloudClient:
    def __init__(self, identity, region='auto', timeout=25, *, country='', cache_path=None):
        if not isinstance(country, str):
            raise CloudError('Configure a two-letter account country code')
        country = country.strip().upper()
        self._automatic = country == 'AUTO' or (not country and region == 'auto')
        self.country = '' if country == 'AUTO' else country
        if self.country and not re.fullmatch('[A-Z]{2}', self.country):
            raise CloudError('Configure a two-letter account country code')
        if not self.country and not self._automatic and region not in REGIONS:
            raise CloudError('Unsupported region; configure an account country or known region')
        self.identity = identity
        self.host, self.caps_host = ('', '') if self.country or self._automatic else REGIONS[region]
        self._servers_resolved = not (self.country or self._automatic)
        self._lookup_country = self.country
        self.resolved_country = ''
        self.cache_path = Path(cache_path) if cache_path is not None else None
        self._account_key = None
        self.timeout = timeout
        self.counter = 0
        self.token = ''

    def resolve_servers(self):
        """Resolve a saved/explicit country or the app's automatic default."""
        if self._servers_resolved:
            return
        nonce = str(int(time.time() * 1000))
        i = self.identity
        signature, key = protocol.request_parameters(i.uuid, i.app_key, i.app_secret, i.moved_card, nonce)
        # The app uses CN for this request when there is no saved country,
        # then selects defaultCountry, which need not be CN.
        body = urlencode({'isoCode': self._lookup_country or 'CN', 'urlVersion': ''}).encode()
        headers = {'uuid': i.uuid, 'appKey': i.app_key, 'Accept-Language': 'en',
                   'versionName': '7.9.4_G', 'Content-Type': 'application/x-www-form-urlencoded'}
        request = urllib.request.Request(
            f'{DISCOVERY_HOST}/phoneAndUrlByCountry/va1/{nonce}/{signature}.rs', data=body, headers=headers)
        result = self._exchange(request, key)
        data = result.get('data')
        if result.get('code') != 2000 or not isinstance(data, dict):
            raise CloudError('Account country discovery failed')
        if self._lookup_country:
            regions = data.get('regionUrl')
            if not isinstance(regions, list):
                raise CloudError('No unique server mapping for the selected account country')
            matches = [entry for entry in regions if isinstance(entry, dict)
                       and entry.get('countryNo') == self._lookup_country]
            if len(matches) != 1:
                raise CloudError('No unique server mapping for the selected account country')
            selected = matches[0]
        else:
            selected = data.get('defaultCountry')
            if not isinstance(selected, dict):
                raise CloudError('Country discovery returned no automatic default; set ICSEE_COUNTRY')
        resolved_country = selected.get('countryNo', '')
        if not isinstance(resolved_country, str) or not re.fullmatch('[A-Z]{2}', resolved_country):
            raise CloudError('Country discovery returned an invalid country code')
        host = _server_origin(selected.get('amsUrl'))
        caps_host = _server_origin(selected.get('capsUrl'))
        self.host, self.caps_host = host, caps_host
        self.resolved_country = resolved_country
        self._servers_resolved = True

    def _cached_accounts(self):
        if self.cache_path is not None:
            try:
                value = json.loads(self.cache_path.read_text(encoding='utf8'))
                if isinstance(value, dict) and value.get('version') == 1 and isinstance(value.get('accounts'), dict):
                    return value['accounts']
            except (OSError, ValueError):
                pass
        return {}

    def _prepare_account(self, username):
        # Cache routing per account/client identity without storing email or password.
        key = hashlib.sha256((self.identity.uuid + '\0' + username).encode()).hexdigest()
        if key == self._account_key:
            return
        self._account_key = key
        if self._automatic:
            saved = self._cached_accounts().get(key)
            self._lookup_country = saved if isinstance(saved, str) and re.fullmatch('[A-Z]{2}', saved) else ''
            self.host = self.caps_host = self.resolved_country = ''
            self._servers_resolved = False

    def _remember_country(self):
        if self.cache_path is None or not self.resolved_country:
            return
        temporary = None
        try:
            accounts = self._cached_accounts()
            accounts[self._account_key] = self.resolved_country
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            # Both completed and interrupted cache files match *.local.json ignores.
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf8', prefix='.account-',
                                             suffix='.local.json', dir=self.cache_path.parent,
                                             delete=False) as output:
                temporary = Path(output.name)
                json.dump({'version': 1, 'accounts': accounts}, output, indent=2)
            os.replace(temporary, self.cache_path)
        except OSError:
            # Read-only configuration directories must not turn a valid login into a failure.
            pass
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass

    def invoke(self, method, plaintext='', token=''):
        self.resolve_servers()
        self.counter = self.counter % 9999999 + 1
        nonce = protocol.nonce(self.counter)
        i = self.identity
        signature, key = protocol.request_parameters(i.uuid, i.app_key, i.app_secret, i.moved_card, nonce)
        encoder = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
        body = (encoder.update(protocol.padded_body(plaintext)) + encoder.finalize()).hex().upper().encode()
        headers = {'uuid': i.uuid, 'appKey': i.app_key, 'Content-Type': 'application/x-www-form-urlencoded',
                   'Accept-Charset': 'utf-8', 'User-Agent': 'xmshop/7.9.4_G', 'Authorization': token}
        request = urllib.request.Request(self.host + protocol.request_path(method, nonce, signature), data=body, headers=headers)
        return self._exchange(request, key)

    def _exchange(self, request, key):
        opener = urllib.request.build_opener(
            _NoRedirect(), urllib.request.HTTPSHandler(context=ssl.create_default_context()))
        try:
            with opener.open(request, timeout=self.timeout) as response:
                raw = response.read(4*1024*1024 + 1)
        except urllib.error.HTTPError as error:
            raise CloudError(f'Cloud HTTP failure ({error.code})') from None
        except OSError:
            raise CloudError('Cloud network request failed') from None
        if len(raw) > 4*1024*1024:
            raise CloudError('Cloud response exceeded the supported size')
        text = unquote(raw.decode('utf8', errors='replace').strip())
        if re.fullmatch('[0-9a-fA-F]+', text) and len(text) % 32 == 0:
            decoder = Cipher(algorithms.AES(key), modes.ECB()).decryptor()
            decrypted = decoder.update(bytes.fromhex(text)) + decoder.finalize()
            if decrypted and 1 <= decrypted[-1] <= 16 and decrypted.endswith(bytes([decrypted[-1]])*decrypted[-1]):
                decrypted = decrypted[:-decrypted[-1]]
            text = decrypted.decode('utf8', errors='replace')
        try: result = json.loads(text)
        except ValueError: raise CloudError('Cloud returned an unsupported response') from None
        if not isinstance(result, dict):
            raise CloudError('Cloud returned an unsupported response')
        return result

    def login(self, username, password):
        if not username or not password: raise CloudError('Configure account username and password locally')
        self.token = ''
        self._prepare_account(username)
        result = self.invoke('loginExist', protocol.login_plaintext(quote_plus(username), password))
        data = result.get('data', {}) if isinstance(result, dict) else {}
        self.token = data.get('accessToken', '') if isinstance(data, dict) else ''
        if not isinstance(self.token, str) or not self.token:
            self.token = ''
            raise CloudError('Account login failed; check credentials, or set ICSEE_COUNTRY if the account belongs elsewhere')
        self._remember_country()

    def list_devices(self):
        if not self.token: raise CloudError('Sign in before requesting devices')
        result = self.invoke('msdlistCode', token=self.token)
        if result.get('code') != 2000: raise CloudError('Camera list request failed')
        data = result.get('data', {})
        return [item for kind in ('mine', 'share') for item in data.get(kind, [])]

    def select_device(self, name='', device_id=''):
        if not name and not device_id: raise CloudError('Configure ICSEE_DEVICE_NAME or ICSEE_DEVICE_ID')
        cameras = [camera for camera in self.list_devices()
                   if (not name or unquote(camera.get('nickname', '')).casefold() == name.casefold())
                   and (not device_id or camera.get('uuid') == device_id)]
        if len(cameras) != 1: raise CloudError('Camera selector must match exactly one authorized device')
        return cameras[0]
