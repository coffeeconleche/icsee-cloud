import pytest
from icsee_cloud import protocol


def test_native_nonce_and_input_boundaries():
    assert protocol.nonce(7, 1234567890123) == '00000071234567890123'
    with pytest.raises(ValueError): protocol.nonce(0, 1)
    with pytest.raises(ValueError): protocol.request_parameters('a'*512, '', '', 1, '123')


def test_login_password_encoding_is_distinct_from_username_encoding():
    assert protocol.login_plaintext('demo%2Bcamera%40example.test', 'a b+&/c') == (
        'account=demo%2Bcamera%40example.test&pass=a%20b%2B%26/c')


def test_full_block_padding_and_native_key_length():
    assert protocol.padded_body('a'*16) == b'a'*16 + bytes([16])*16
    assert protocol.padded_body('') == bytes([16])*16
    signature, key = protocol.request_parameters('test-uuid', 'test-key', 'test-secret', 7, protocol.nonce(1, 1234567890123))
    # Synthetic vector from the earlier native-analysis reconstruction.
    assert signature == 'e1b4fb4465bf6ce46120bccc6529fe26'
    assert key.hex() == '34353637383930313233746573742d73'
