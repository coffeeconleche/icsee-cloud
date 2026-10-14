"""Signed/encrypted account API; raw account responses are never written to disk."""
import json
import re
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from urllib.parse import quote_plus, unquote
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from . import protocol

REGIONS = {
    'sa': ('https://sa-ams.jftechws.com', 'https://caps-sa.jftechws.com'),
    'global': ('https://rs.jftechws.com', 'https://caps.jftechws.com'),
}


class CloudError(RuntimeError):
    """Sanitized cloud failure, without tokens, response bodies or request URLs."""


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
    def __init__(self, identity, region='sa', timeout=25):
        if region not in REGIONS: raise CloudError('Unsupported region; configure a known host mapping')
        self.identity = identity
        self.host, self.caps_host = REGIONS[region]
        self.timeout = timeout
        self.counter = 0
        self.token = ''

    def invoke(self, method, plaintext='', token=''):
        self.counter = self.counter % 9999999 + 1
        nonce = protocol.nonce(self.counter)
        i = self.identity
        signature, key = protocol.request_parameters(i.uuid, i.app_key, i.app_secret, i.moved_card, nonce)
        encoder = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
        body = (encoder.update(protocol.padded_body(plaintext)) + encoder.finalize()).hex().upper().encode()
        headers = {'uuid': i.uuid, 'appKey': i.app_key, 'Content-Type': 'application/x-www-form-urlencoded',
                   'Accept-Charset': 'utf-8', 'User-Agent': 'xmshop/7.9.4_G', 'Authorization': token}
        request = urllib.request.Request(self.host + protocol.request_path(method, nonce, signature), data=body, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout, context=ssl.create_default_context()) as response:
                raw = response.read(4*1024*1024)
        except urllib.error.HTTPError as error:
            raise CloudError(f'Cloud HTTP failure ({error.code})') from None
        except OSError:
            raise CloudError('Cloud network request failed') from None
        text = unquote(raw.decode('utf8', errors='replace').strip())
        if re.fullmatch('[0-9a-fA-F]+', text) and len(text) % 32 == 0:
            decoder = Cipher(algorithms.AES(key), modes.ECB()).decryptor()
            decrypted = decoder.update(bytes.fromhex(text)) + decoder.finalize()
            if decrypted and 1 <= decrypted[-1] <= 16 and decrypted.endswith(bytes([decrypted[-1]])*decrypted[-1]):
                decrypted = decrypted[:-decrypted[-1]]
            text = decrypted.decode('utf8', errors='replace')
        try: return json.loads(text)
        except ValueError: raise CloudError('Cloud returned an unsupported response') from None

    def login(self, username, password):
        if not username or not password: raise CloudError('Configure account username and password locally')
        result = self.invoke('loginExist', protocol.login_plaintext(quote_plus(username), password))
        data = result.get('data', {}) if isinstance(result, dict) else {}
        self.token = data.get('accessToken', '') if isinstance(data, dict) else ''
        if not self.token: raise CloudError('Account login failed')

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
