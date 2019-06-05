import json
import logging
from unittest.mock import MagicMock

from pykube import Namespace
from pykube.objects import NamespacedAPIObject

from kube_janitor.janitor import matches_resource_filter, handle_resource_on_ttl, handle_resource_on_expiry, clean_up, \
    delete
from kube_janitor.rules import Rule

ALL = frozenset(['all'])


def test_matches_resource_filter():
    foo_ns = Namespace(None, {'metadata': {'name': 'foo'}})
    assert not matches_resource_filter(foo_ns, [], [], [], [])
    assert not matches_resource_filter(foo_ns, ALL, [], [], [])
    assert matches_resource_filter(foo_ns, ALL, [], ALL, [])
    assert not matches_resource_filter(foo_ns, ALL, [], ALL, ['foo'])
    assert not matches_resource_filter(foo_ns, ALL, ['namespaces'], ALL, [])
    assert matches_resource_filter(foo_ns, ALL, ['deployments'], ALL, ['kube-system'])


def test_delete_namespace(caplog):
    caplog.set_level(logging.INFO)
    mock_api = MagicMock()
    foo_ns = Namespace(mock_api, {'metadata': {'name': 'foo'}})
    delete(foo_ns, dry_run=False)
    assert 'Deleting Namespace foo..' in caplog.messages
    mock_api.delete.assert_called_once()


def test_handle_resource_no_ttl():
    resource = Namespace(None, {'metadata': {'name': 'foo'}})
    counter = handle_resource_on_ttl(resource, [], None, dry_run=True, tiller=None)
    assert counter == {'resources-processed': 1}


def test_handle_resource_no_expiry():
    resource = Namespace(None, {'metadata': {'name': 'foo'}})
    counter = handle_resource_on_expiry(resource, [], None, dry_run=True, tiller=None)
    assert counter == {}


def test_handle_resource_ttl_annotation():
    # TTL is far in the future
    resource = Namespace(None, {'metadata': {'name': 'foo', 'annotations': {'janitor/ttl': '999w'}, 'creationTimestamp': '2019-01-17T20:59:12Z'}})
    counter = handle_resource_on_ttl(resource, [], None, dry_run=True, tiller=None)
    assert counter == {'resources-processed': 1, 'namespaces-with-ttl': 1}


def test_handle_resource_expiry_annotation():
    # TTL is far in the future
    resource = Namespace(None, {'metadata': {
        'name': 'foo',
        'annotations': {'janitor/expires': '2050-09-26T01:51:42Z'}}})
    counter = handle_resource_on_expiry(resource, [], None, dry_run=True, tiller=None)
    assert counter == {'namespaces-with-expiry': 1}


def test_handle_resource_ttl_expired():
    resource = Namespace(None, {'metadata': {'name': 'foo', 'annotations': {'janitor/ttl': '1s'}, 'creationTimestamp': '2019-01-17T20:59:12Z'}})
    counter = handle_resource_on_ttl(resource, [], None, dry_run=True, tiller=None)
    assert counter == {'resources-processed': 1, 'namespaces-with-ttl': 1, 'namespaces-deleted': 1}


def test_handle_resource_expiry_expired():
    resource = Namespace(None, {'metadata': {
        'name': 'foo',
        'annotations': {'janitor/expires': '2001-09-26T01:51:42Z'}}})
    counter = handle_resource_on_expiry(resource, [], None, dry_run=True, tiller=None)
    assert counter == {'namespaces-with-expiry': 1, 'namespaces-deleted': 1}


def test_clean_up_default():
    api_mock = MagicMock(spec=NamespacedAPIObject, name='APIMock')

    def get(**kwargs):
        if kwargs.get('url') == 'namespaces':
            # kube-system is skipped
            data = {'items': [{'metadata': {'name': 'default'}}, {'metadata': {'name': 'kube-system'}}]}
        elif kwargs['version'] == 'v1':
            data = {'resources': []}
        elif kwargs['version'] == '/apis':
            data = {'groups': []}
        else:
            data = {}
        response = MagicMock()
        response.json.return_value = data
        return response
    api_mock.get = get
    counter = clean_up(api_mock, ALL, [], ALL, ['kube-system'], [], None, dry_run=False)

    assert counter['resources-processed'] == 1


def test_ignore_invalid_ttl():
    api_mock = MagicMock(spec=NamespacedAPIObject, name='APIMock')

    def get(**kwargs):
        if kwargs.get('url') == 'namespaces':
            data = {'items': [{'metadata': {'name': 'ns-1'}}]}
        elif kwargs.get('url') == 'customfoos':
            data = {'items': [{'metadata': {
                'name': 'foo-1',
                'namespace': 'ns-1',
                'creationTimestamp': '2019-01-17T15:14:38Z',
                # invalid TTL (no unit suffix)
                'annotations': {'janitor/ttl': '123'}}}]}
        elif kwargs['version'] == 'v1':
            data = {'resources': []}
        elif kwargs['version'] == 'srcco.de/v1':
            data = {'resources': [{'kind': 'CustomFoo', 'name': 'customfoos', 'namespaced': True, 'verbs': ['delete']}]}
        elif kwargs['version'] == '/apis':
            data = {'groups': [{'preferredVersion': {'groupVersion': 'srcco.de/v1'}}]}
        else:
            data = {}
        response = MagicMock()
        response.json.return_value = data
        return response

    api_mock.get = get
    counter = clean_up(api_mock, ALL, [], ALL, [], [], None, dry_run=False)
    assert counter['resources-processed'] == 2
    assert counter['customfoos-with-ttl'] == 0
    assert counter['customfoos-deleted'] == 0
    assert not api_mock.delete.called


def test_ignore_invalid_expiry():
    api_mock = MagicMock(spec=NamespacedAPIObject, name='APIMock')

    def get(**kwargs):
        if kwargs.get('url') == 'namespaces':
            data = {'items': [{'metadata': {'name': 'ns-1'}}]}
        elif kwargs.get('url') == 'customfoos':
            data = {'items': [{'metadata': {
                'name': 'foo-1',
                'namespace': 'ns-1',
                # invalid expiry
                'annotations': {'janitor/expires': '123'}}}]}
        elif kwargs['version'] == 'v1':
            data = {'resources': []}
        elif kwargs['version'] == 'srcco.de/v1':
            data = {'resources': [{'kind': 'CustomFoo', 'name': 'customfoos', 'namespaced': True, 'verbs': ['delete']}]}
        elif kwargs['version'] == '/apis':
            data = {'groups': [{'preferredVersion': {'groupVersion': 'srcco.de/v1'}}]}
        else:
            data = {}
        response = MagicMock()
        response.json.return_value = data
        return response

    api_mock.get = get
    counter = clean_up(api_mock, ALL, [], ALL, [], [], None, dry_run=False)
    assert counter['resources-processed'] == 2
    assert counter['customfoos-with-expiry'] == 0
    assert counter['customfoos-deleted'] == 0
    assert not api_mock.delete.called


def test_clean_up_custom_resource_on_ttl():
    api_mock = MagicMock(name='APIMock')

    def get(**kwargs):
        if kwargs.get('url') == 'namespaces':
            data = {'items': [{'metadata': {'name': 'ns-1'}}]}
        elif kwargs.get('url') == 'customfoos':
            data = {'items': [{'metadata': {
                'name': 'foo-1',
                'namespace': 'ns-1',
                'creationTimestamp': '2019-01-17T15:14:38Z',
                'annotations': {'janitor/ttl': '10m'}}}]}
        elif kwargs['version'] == 'v1':
            data = {'resources': []}
        elif kwargs['version'] == 'srcco.de/v1':
            data = {'resources': [{'kind': 'CustomFoo', 'name': 'customfoos', 'namespaced': True, 'verbs': ['delete']}]}
        elif kwargs['version'] == '/apis':
            data = {'groups': [{'preferredVersion': {'groupVersion': 'srcco.de/v1'}}]}
        else:
            data = {}
        response = MagicMock()
        response.json.return_value = data
        return response

    api_mock.get = get
    counter = clean_up(api_mock, ALL, [], ALL, [], [], None, dry_run=False)

    # namespace ns-1 and object foo-1
    assert counter['resources-processed'] == 2
    assert counter['customfoos-with-ttl'] == 1
    assert counter['customfoos-deleted'] == 1

    api_mock.post.assert_called_once()
    _, kwargs = api_mock.post.call_args
    assert kwargs['url'] == 'events'
    data = json.loads(kwargs['data'])
    assert data['reason'] == 'TimeToLiveExpired'
    assert 'annotation janitor/ttl is set' in data['message']
    involvedObject = {'kind': 'CustomFoo', 'name': 'foo-1', 'namespace': 'ns-1', 'apiVersion': 'srcco.de/v1', 'resourceVersion': None, 'uid': None}
    assert data['involvedObject'] == involvedObject

    # verify that the delete call happened
    api_mock.delete.assert_called_once_with(data='{"propagationPolicy": "Foreground"}', namespace='ns-1', url='customfoos/foo-1', version='srcco.de/v1')


def test_clean_up_custom_resource_on_expiry():
    api_mock = MagicMock(name='APIMock')

    def get(**kwargs):
        if kwargs.get('url') == 'namespaces':
            data = {'items': [{'metadata': {'name': 'ns-1'}}]}
        elif kwargs.get('url') == 'customfoos':
            data = {'items': [{'metadata': {
                'name': 'foo-1',
                'namespace': 'ns-1',
                'annotations': {'janitor/expires': '2001-01-17T15:14:38Z'}}}]}
        elif kwargs['version'] == 'v1':
            data = {'resources': []}
        elif kwargs['version'] == 'srcco.de/v1':
            data = {'resources': [{'kind': 'CustomFoo', 'name': 'customfoos', 'namespaced': True, 'verbs': ['delete']}]}
        elif kwargs['version'] == '/apis':
            data = {'groups': [{'preferredVersion': {'groupVersion': 'srcco.de/v1'}}]}
        else:
            data = {}
        response = MagicMock()
        response.json.return_value = data
        return response

    api_mock.get = get
    counter = clean_up(api_mock, ALL, [], ALL, [], [], None, dry_run=False)

    # namespace ns-1 and object foo-1
    assert counter['resources-processed'] == 2
    assert counter['customfoos-with-expiry'] == 1
    assert counter['customfoos-deleted'] == 1

    api_mock.post.assert_called_once()
    _, kwargs = api_mock.post.call_args
    assert kwargs['url'] == 'events'
    data = json.loads(kwargs['data'])
    assert data['reason'] == 'ExpiryTimeReached'
    assert 'annotation janitor/expires is set' in data['message']
    involvedObject = {'kind': 'CustomFoo', 'name': 'foo-1', 'namespace': 'ns-1', 'apiVersion': 'srcco.de/v1', 'resourceVersion': None, 'uid': None}
    assert data['involvedObject'] == involvedObject

    # verify that the delete call happened
    api_mock.delete.assert_called_once_with(data='{"propagationPolicy": "Foreground"}', namespace='ns-1', url='customfoos/foo-1', version='srcco.de/v1')


def test_clean_up_by_rule():
    api_mock = MagicMock(name='APIMock')

    rule = Rule.from_entry({'id': 'r1', 'resources': ['customfoos'], 'jmespath': "metadata.namespace == 'ns-1'", 'ttl': '10m'})

    def get(**kwargs):
        if kwargs.get('url') == 'namespaces':
            data = {'items': [{'metadata': {'name': 'ns-1'}}]}
        elif kwargs.get('url') == 'customfoos':
            data = {'items': [{'metadata': {
                'name': 'foo-1',
                'namespace': 'ns-1',
                'creationTimestamp': '2019-01-17T15:14:38Z',
            }}]}
        elif kwargs['version'] == 'v1':
            data = {'resources': []}
        elif kwargs['version'] == 'srcco.de/v1':
            data = {'resources': [{'kind': 'CustomFoo', 'name': 'customfoos', 'namespaced': True, 'verbs': ['delete']}]}
        elif kwargs['version'] == '/apis':
            data = {'groups': [{'preferredVersion': {'groupVersion': 'srcco.de/v1'}}]}
        else:
            data = {}
        response = MagicMock()
        response.json.return_value = data
        return response

    api_mock.get = get
    counter = clean_up(api_mock, ALL, [], ALL, [], [rule], None, dry_run=False)

    # namespace ns-1 and object foo-1
    assert counter['resources-processed'] == 2
    assert counter['rule-r1-matches'] == 1
    assert counter['customfoos-with-ttl'] == 1
    assert counter['customfoos-deleted'] == 1

    api_mock.post.assert_called_once()
    _, kwargs = api_mock.post.call_args
    assert kwargs['url'] == 'events'
    data = json.loads(kwargs['data'])
    assert data['reason'] == 'TimeToLiveExpired'
    assert 'rule r1 matches' in data['message']
    involvedObject = {'kind': 'CustomFoo', 'name': 'foo-1', 'namespace': 'ns-1', 'apiVersion': 'srcco.de/v1', 'resourceVersion': None, 'uid': None}
    assert data['involvedObject'] == involvedObject

    # verify that the delete call happened
    api_mock.delete.assert_called_once_with(data='{"propagationPolicy": "Foreground"}', namespace='ns-1', url='customfoos/foo-1', version='srcco.de/v1')
