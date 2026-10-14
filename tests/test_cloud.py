import pytest
from icsee_cloud.cloud import ClientIdentity, CloudClient, CloudError


def client():
    return CloudClient(ClientIdentity('test-uuid', 'test-key', 'test-secret', 7))


def test_secrets_are_not_in_identity_representation():
    assert 'test-secret' not in repr(client().identity)
    assert 'test-key' not in repr(client().identity)


def test_selection_must_match_one_camera_and_optional_serial(monkeypatch):
    cloud = client()
    monkeypatch.setattr(cloud, 'list_devices', lambda: [
        {'nickname': 'Front%20door', 'uuid': 'fixture-1'},
        {'nickname': 'front%20door', 'uuid': 'fixture-2'}])
    with pytest.raises(CloudError): cloud.select_device('Front door')
    assert cloud.select_device('Front door', 'fixture-2')['uuid'] == 'fixture-2'
    with pytest.raises(CloudError): cloud.select_device('', '')


def test_missing_credentials_never_make_a_request(monkeypatch):
    cloud = client()
    monkeypatch.setattr(cloud, 'invoke', lambda *args, **kwargs: pytest.fail('Unexpected network request'))
    with pytest.raises(CloudError): cloud.login('', '')
