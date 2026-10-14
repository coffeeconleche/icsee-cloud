"""Offline reconstruction from identified libFunSDK.so instructions.

No account/network access. Inputs must be the calling application's actual
uuid, appKey, appSecret, movedCard. These are not user credentials.
Signatures/keys intentionally not printed. Verified against the authorized account flow.
"""
import hashlib,time
from urllib.parse import quote

def nonce(counter=1,milliseconds=None):
    if not 1 <= counter < 10000000:
        raise ValueError('counter out of native range')
    return f'{counter:07d}{int(time.time()*1000) if milliseconds is None else milliseconds}'

def request_parameters(uuid,app_key,app_secret,moved_card,nonce_value):
    # IXMEncrypt::SetParmeValue stores uuid/key/secret at +0x10/+0x28/+0x40,
    # movedCard at +0x70. GetEncryptStr concatenates all three plus nonce.
    original=(uuid+app_key+app_secret+nonce_value).encode('utf-8')
    if len(original)>=512 or moved_card<0:
        raise ValueError('outside reconstructed native input boundary')
    changed=bytearray(original)
    length=len(changed)
    # 0xfc7e90..0xfc7f70: unusual full-length loop, not a conventional reverse.
    for i in range(length):
        j=length-1-i
        keep=moved_card and i%moved_card > (length-i)%moved_card
        tmp=changed[i] if keep else changed[j]
        changed[i]=changed[j]
        changed[j]=tmp
    digest=hashlib.md5(original+changed[::-1]).hexdigest()
    # KeyFilter 0xfc6b1c: substring from half of nonce, append secret, truncate16.
    aes_key=(nonce_value[len(nonce_value)//2:]+app_secret).encode('utf8')
    if len(aes_key)<16:
        for i in range(16-len(aes_key)):
            aes_key+=str(i).encode('ascii')
    return digest,aes_key[:16]

def request_path(method,nonce_value,signature,third_party=''):
    prefix='/'+third_party if third_party and third_party!='myphone' else ''
    return f'{prefix}/{method}/v3/{nonce_value}/{signature}.rs'

def padded_body(plaintext):
    body=plaintext.encode('utf8')
    padding=16-len(body)%16
    return body+bytes([padding])*padding

def login_plaintext(username,password):
    # Native EncodeURL 0xb15a7c explicitly preserves these punctuation bytes;
    # spaces are %20, not +. Username is used as-is by CustomLoginEx.
    return 'account='+username+'&pass='+quote(password,safe='/.!-_*()')

# Body: AES128_ECB(padded_body("account=<raw user>&pass=<EncodeURL pwd>"), key)
# => uppercase hexadecimal text. Native HexToStr 0xfc6f40 uses digits+A..F.
# Response: hexadecimal AES128_ECB encrypted UTF8 JSON, same key; PKCS padding.
# Header fields: uuid, appKey, Content-Type application/x-www-form-urlencoded,
# Accept-Charset utf-8, User-Agent actual init profile, optional Authorization.
