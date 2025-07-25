"""
Unit tests for the Drycc api app.

Run the tests with "./manage.py test api"
"""
import base64
import json
import logging
from unittest import mock
import random
import requests

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test.utils import override_settings

from api.models.app import App, app_permission_registry
from api.models.base import PTYPE_WEB
from api.models.config import Config
from scheduler import KubeException, KubeHTTPException

from api.exceptions import DryccException
from api.tests import adapter, DryccTestCase
import requests_mock

User = get_user_model()


def mock_none(*args, **kwargs):
    return None


def _mock_run(*args, **kwargs):
    return [0, 'mock']


@requests_mock.Mocker(real_http=True, adapter=adapter)
class AppTest(DryccTestCase):
    """Tests creation of applications"""

    fixtures = ['tests.json']

    def setUp(self):
        self.user = User.objects.get(username='autotest')
        self.token = self.get_or_create_token(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token)

    def tearDown(self):
        # make sure every test has a clean slate for k8s mocking
        cache.clear()

    def test_app(self, mock_requests):
        """
        Test that a user can create, read, update and delete an application
        """
        app_id = self.create_app()

        response = self.client.get('/v2/apps')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(len(response.data['results']), 1)

        url = f'/v2/apps/{app_id}'
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.data)

        body = {'id': 'new'}
        response = self.client.patch(url, body)
        self.assertEqual(response.status_code, 405, response.content)

        response = self.client.delete(url)
        self.assertEqual(response.status_code, 204, response.data)

    def test_app_name_length(self, mock_requests):
        """
        Test that the app name length cannot be longer than the maximum length dictated by
        Kubernetes' maximum service name length.
        """
        name = 'a' * 64
        body = {'id': name}
        response = self.client.post('/v2/apps', body)
        self.assertEqual(
            response.data,
            {'id': ['Ensure this field has no more than 63 characters.']}
        )
        self.assertEqual(response.status_code, 400)

    def test_response_data(self, mock_requests):
        """Test that the serialized response contains only relevant data."""
        body = {'id': 'app-{}'.format(random.randrange(1000, 10000))}
        response = self.client.post('/v2/apps', body)
        for key in response.data:
            self.assertIn(key, ['uuid', 'created', 'updated', 'id', 'owner', 'structure'])
        expected = {
            'id': body['id'],
            'owner': self.user.username,
            'structure': {}
        }
        self.assertEqual(response.data, expected | response.data)

    def test_app_override_id(self, mock_requests):
        app_id = self.create_app()

        response = self.client.post('/v2/apps', {'id': app_id})
        self.assertContains(response, 'Application with this id already exists.', status_code=400)

    @mock.patch('api.models.app.logger')
    def test_app_release_notes_in_logs(self, mock_requests, mock_logger):
        """Verifies that an app's release summary is dumped into the logs."""
        with mock.patch('api.models.release.logger') as release_logger:
            app_id = self.create_app()
            app = App.objects.get(id=app_id)
            # check release logs
            exp_msg = "[{app_id}]: {self.user.username} created initial release".format(
                **locals())
            release_logger.log.assert_any_call(logging.INFO, exp_msg)
            app.log('hello world')
            exp_msg = f"[{app_id}]: hello world"
            mock_logger.log.assert_any_call(logging.INFO, exp_msg)
            app.log('goodbye world', logging.WARNING)
            # assert logging with a different log level
            exp_msg = f"[{app_id}]: goodbye world"
            mock_logger.log.assert_any_call(logging.WARNING, exp_msg)

    def test_app_errors(self, mock_requests):
        response = self.client.post('/v2/apps', {'id': 'camelCase'})
        self.assertContains(
            response,
            'App name must start with an alphabetic character, cannot end with a hyphen and can '
            + 'only contain a-z (lowercase), 0-9 and hyphens.',
            status_code=400
        )

        response = self.client.post('/v2/apps', {'id': '123name-starts-with-numbers'})
        self.assertContains(
            response,
            'App name must start with an alphabetic character, cannot end with a hyphen and can '
            + 'only contain a-z (lowercase), 0-9 and hyphens.',
            status_code=400
        )

        response = self.client.post('/v2/apps', {'id': 'name-ends-with-hyphen-'})
        self.assertContains(
            response,
            'App name must start with an alphabetic character, cannot end with a hyphen and can '
            + 'only contain a-z (lowercase), 0-9 and hyphens.',
            status_code=400
        )

        app_id = self.create_app()
        url = f'/v2/apps/{app_id}'
        response = self.client.delete(url)
        self.assertEqual(response.status_code, 204, response.data)
        for endpoint in ('containers', 'config', 'releases', 'builds'):
            url = f'/v2/apps/{app_id}/{endpoint}'
            response = self.client.get(url)
            self.assertEqual(response.status_code, 404)

    def test_app_reserved_names(self, mock_requests):
        """Nobody should be able to create applications with names which are reserved."""
        reserved_names = ['fooooo', 'barrrrrr']
        with self.settings(RESERVED_NAME_PATTERNS=reserved_names):
            for name in reserved_names:
                response = self.client.post('/v2/apps', {'id': name})
                self.assertContains(
                    response,
                    '{} is a reserved name.'.format(name),
                    status_code=400)

    def test_app_structure_is_valid_json(self, mock_requests):
        """Application structures should be valid JSON objects."""
        response = self.client.post('/v2/apps')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertIn('id', response.data)
        self.assertIn('structure', response.data)
        self.assertEqual(response.data['structure'], {})
        app_id = response.data['id']
        app = App.objects.get(id=app_id)
        app.structure = {'web': 1}
        app.save()

        response = self.client.get('/v2/apps/{}'.format(app_id))
        self.assertIn('structure', response.data)
        self.assertEqual(response.data['structure'], {"web": 1})

    @mock.patch('api.models.release.logger')
    def test_admin_can_manage_other_apps(self, mock_requests, mock_logger):
        """Administrators of Drycc should be able to manage all applications.
        """
        # log in as non-admin user and create an app
        username = 'autotest2'
        user = User.objects.get(username=username)
        token = self.get_or_create_token(user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)
        app_id = self.create_app()

        # log in as admin, check to see if they have access
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token)
        url = '/v2/apps/{}'.format(app_id)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.data)
        # check app logs
        exp_msg = "[%s]: %s created initial release" % (app_id, username)
        mock_logger.log.assert_any_call(logging.INFO, exp_msg)
        # TODO: test run needs an initial build
        # delete the app
        url = '/v2/apps/{}'.format(app_id)
        response = self.client.delete(url)
        self.assertEqual(response.status_code, 204, response.data)

    def test_admin_can_see_other_apps(self, mock_requests):
        """If a user creates an application, the administrator should be able
        to see it.
        """
        # log in as non-admin user and create an app
        user = User.objects.get(username='autotest2')
        token = self.get_or_create_token(user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)
        self.create_app()

        # log in as admin
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token)
        response = self.client.get('/v2/apps')
        self.assertIn('count', response.data)
        self.assertEqual(response.data['count'], 1, response.data)

    def test_run_without_release_should_error(self, mock_requests):
        """
        A user should not be able to run a one-off command unless a release
        is present.
        """
        app_id = self.create_app()
        url = '/v2/apps/{}/run'.format(app_id)
        body = {'command': 'ls -al'}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(
            str(response.data["detail"]), 'no build available, please deploy a release')

    @mock.patch('api.models.app.App.run', _mock_run)
    @mock.patch('api.models.app.App.deploy', mock_none)
    def test_run(self, mock_requests):
        """
        A user should be able to run a one off command
        """
        app_id = self.create_app()

        # create build
        body = {'image': 'autotest/example', 'stack': 'container'}
        url = f'/v2/apps/{app_id}/build'
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 201, response.data)

        # cannot run command without body
        url = '/v2/apps/{}/run'.format(app_id)
        response = self.client.post(url, {})
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(
            response.data,
            {'detail': 'command is a required field, or it can be defined in Procfile'}
        )

        # run command
        body = {'command': 'ls -al'}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 204, response.data)

    def test_run_failure(self, mock_requests):
        """Raise a KubeException via scheduler.run"""
        app_id = self.create_app()

        # create build
        body = {'image': 'autotest/example', 'stack': 'container'}
        url = f'/v2/apps/{app_id}/build'
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 201, response.data)

        with mock.patch('scheduler.KubeHTTPClient.http_post') as kube_run:
            kube_run.side_effect = KubeException('boom!')
            # run command
            url = '/v2/apps/{}/run'.format(app_id)
            body = {'command': 'ls -al'}
            response = self.client.post(url, body)
            self.assertEqual(response.status_code, 503, response.data)

    def test_unauthorized_user_cannot_see_app(self, mock_requests):
        """
        An unauthorized user should not be able to access an app's resources.

        Since an unauthorized user can't access the application, these
        tests should return a 403, but currently return a 404. FIXME!
        """
        app_id = self.create_app()
        unauthorized_user = User.objects.get(username='autotest2')
        unauthorized_token = self.get_or_create_token(unauthorized_user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + unauthorized_token)

        url = '/v2/apps/{}/run'.format(app_id)
        body = {'command': 'foo'}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 403)

        url = '/v2/apps/{}'.format(app_id)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

        response = self.client.delete(url)
        self.assertEqual(response.status_code, 403)

    def test_app_info_not_showing_wrong_app(self, mock_requests):
        self.create_app()
        response = self.client.get('/v2/apps/foo')
        self.assertEqual(response.status_code, 404)

    def test_app_transfer(self, mock_requests):
        owner = User.objects.get(username='autotest2')
        owner_token = self.get_or_create_token(owner)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + owner_token)

        collaborator = User.objects.get(username='autotest3')

        app = App.objects.create(owner=owner)

        # pretend the owner and a collaborator added some config to the app to ensure
        # resources owned by the owner are transferred, but not resources owned by the
        # collaborator.

        config1 = Config.objects.create(
            owner=owner, app=app, values=[{"name": "FOO", "value": "bar", "group": "global"}])
        config2 = Config.objects.create(
            owner=collaborator, app=app,
            values=[{"name": "CAR", "value": "star", "group": "global"}])

        # Transfer App
        url = '/v2/apps/{}'.format(app.id)
        new_owner = User.objects.get(username='autotest4')
        new_owner_token = self.get_or_create_token(new_owner)
        body = {'owner': new_owner.username}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 200, response.data)

        # Original user can no longer access it
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

        # New owner can access it
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + new_owner_token)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['owner'], new_owner.username)

        # At this point config1.owner field is still the old owner, but the value in the database
        # was updated to the new owner when we performed the transfer. The object's updated values
        # needs to be reloaded from the database to get an accurate idea who owns the object.
        # https://docs.djangoproject.com/en/dev/ref/models/instances/#django.db.models.Model.refresh_from_db
        config1.refresh_from_db()
        config2.refresh_from_db()

        # New owner also is given ownership to all resources owned by the original user, but not
        # resources created by other users
        self.assertEqual(config1.owner, new_owner)
        self.assertEqual(config2.owner, collaborator)

        # Collaborators can't transfer
        body = {
            'username': owner.username,
            'permissions': ','.join(app_permission_registry.shortnames),
        }
        response = self.client.post(f'/v2/apps/{app.id}/perms/', body)
        self.assertEqual(response.status_code, 201, response.data)

        self.client.credentials(HTTP_AUTHORIZATION='Token ' + owner_token)
        body = {'owner': self.user.username}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 403)

        # Admins can transfer
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token)
        body = {'owner': self.user.username}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 200, response.data)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['owner'], self.user.username)

    def test_app_exists_in_kubernetes(self, mock_requests):
        """
        Create an app that has the same namespace as an existing kubernetes namespace
        """
        body = {'id': 'duplicate'}
        response = self.client.post('/v2/apps', body)
        self.assertContains(
            response,
            'duplicate already exists as a namespace in this kuberenetes setup',
            status_code=409
        )

    def test_app_delete_failure_kubernetes_destroy(self, mock_requests):
        """
        Create an app and then delete but have scheduler.ns.delete
        fail with an exception
        """
        # create
        app_id = self.create_app()

        with mock.patch('scheduler.resources.namespace.Namespace.delete') as mock_kube:
            # delete
            mock_kube.side_effect = KubeException('Boom!')
            response = self.client.delete('/v2/apps/{}'.format(app_id))
            self.assertEqual(response.status_code, 503, response.data)

    def test_app_delete_missing_namespace(self, mock_requests):
        """
        Create an app and then delete but have namespace missing
        Should still succeed
        """
        # create
        app_id = self.create_app()

        with mock.patch('scheduler.resources.namespace.Namespace.get') as mock_kube:
            # instead of full request mocking, fake it out in a simple way
            class Response(object):
                def json(self):
                    return '{}'

            response = Response()
            response.status_code = 404
            response.reason = "Not Found"
            kube_exception = KubeHTTPException(response, 'big boom')
            mock_kube.side_effect = kube_exception

            response = self.client.delete('/v2/apps/{}'.format(app_id))
            self.assertEqual(response.status_code, 204, response.data)

        # verify that app is gone
        response = self.client.get('/v2/apps/{}'.format(app_id))
        self.assertEqual(response.status_code, 404, response.data)

    def test_app_verify_application_health_success(self, mock_requests):
        """
        Create an application which in turn causes a health check to run against
        the router. Make it succeed on the 6th try
        """
        responses = [
            {'text': 'Not Found', 'status_code': 404},
            {'text': 'Not Found', 'status_code': 404},
            {'text': 'Not Found', 'status_code': 404},
            {'text': 'Not Found', 'status_code': 404},
            {'text': 'Not Found', 'status_code': 404},
            {'text': 'OK', 'status_code': 200}
        ]

        # create app
        app_id = self.create_app()
        hostname = 'http://{}.{}.svc:80/'.format(app_id, app_id)
        mr = mock_requests.register_uri('GET', hostname, responses)

        # deploy app to get verification
        url = "/v2/apps/{}/build".format(app_id)
        body = {'image': 'autotest/example', 'stack': 'container'}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['image'], body['image'])

        self.assertEqual(mr.called, True)
        self.assertEqual(mr.call_count, 6)

    def test_app_verify_application_health_failure_404(self, mock_requests):
        """
        Create an application which in turn causes a health check to run against
        the router. Make it fail with a 404 after 10 tries
        """
        # function tries to hit router 10 times
        responses = [
            {'text': 'Not Found', 'status_code': 404},
            {'text': 'Not Found', 'status_code': 404},
            {'text': 'Not Found', 'status_code': 404},
            {'text': 'Not Found', 'status_code': 404},
            {'text': 'Not Found', 'status_code': 404},
            {'text': 'Not Found', 'status_code': 404},
            {'text': 'Not Found', 'status_code': 404},
            {'text': 'Not Found', 'status_code': 404},
            {'text': 'Not Found', 'status_code': 404},
            {'text': 'Not Found', 'status_code': 404},
        ]

        # create app
        app_id = self.create_app()

        hostname = 'http://{}.{}.svc:80/'.format(app_id, app_id)
        mr = mock_requests.register_uri('GET', hostname, responses)
        # deploy app to get verification
        url = "/v2/apps/{}/build".format(app_id)
        body = {'image': 'autotest/example', 'stack': 'container'}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['image'], body['image'])

        self.assertEqual(mr.called, True)
        self.assertEqual(mr.call_count, 10)

    def test_app_verify_application_health_failure_exceptions(self, mock_requests):
        """
        Create an application which in turn causes a health check to run against
        the router. Make it fail with a python-requets exception
        """
        def _raise_exception(request, ctx):
            raise requests.exceptions.RequestException('Boom!')

        # create app
        app_id = self.create_app()
        # function tries to hit router 10 times
        hostname = 'http://{}.{}.svc:80/'.format(app_id, app_id)
        mr = mock_requests.register_uri('GET', hostname, text=_raise_exception)

        # deploy app to get verification
        url = "/v2/apps/{}/build".format(app_id)
        body = {'image': 'autotest/example', 'stack': 'container'}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['image'], body['image'])

        # Called 10 times due to the exception
        self.assertEqual(mr.called, True)
        self.assertEqual(mr.call_count, 10)

    def test_list_ordering(self, mock_requests):
        """
        Test that a list of apps is sorted by name
        """
        for name in ['zulua', 'tango', 'alpha', 'foxtrot']:
            response = self.client.post('/v2/apps', {'id': name})
            self.assertEqual(response.status_code, 201, response.data)

        response = self.client.get('/v2/apps')
        apps = response.data['results']
        self.assertEqual(apps[0]['id'], 'alpha')
        self.assertEqual(apps[1]['id'], 'foxtrot')
        self.assertEqual(apps[2]['id'], 'tango')
        self.assertEqual(apps[3]['id'], 'zulua')

    def test_get_private_registry_config(self, mock_requests):
        registry = {"web": {'username': 'test', 'password': 'test'}}
        auth = bytes('{}:{}'.format("test", "test"), 'UTF-8')
        encAuth = base64.b64encode(auth).decode(encoding='UTF-8')
        image = 'test/test'

        docker_config, name, create = App()._get_private_registry_config("web", image, registry.get("web", {}))  # noqa
        dockerConfig = json.loads(docker_config)
        expected = {"https://index.docker.io/v1/": {"auth": encAuth}}
        self.assertEqual(dockerConfig.get('auths'), expected)
        self.assertEqual(name, "private-registry-web")
        self.assertEqual(create, True)

        image = "quay.io/test/test"
        docker_config, name, create = App()._get_private_registry_config("web", image, registry.get("web", {}))  # noqa
        dockerConfig = json.loads(docker_config)
        expected = {"quay.io": {"auth": encAuth}}
        self.assertEqual(dockerConfig.get('auths'), expected)
        self.assertEqual(name, "private-registry-web")
        self.assertEqual(create, True)

    @override_settings(REGISTRY_LOCATION="off-cluster")
    def test_get_private_registry_config_off_cluster(self, mock_requests):
        registry = {}
        auth = bytes('{}:{}'.format("test", "test"), 'UTF-8')
        encAuth = base64.b64encode(auth).decode(encoding='UTF-8')
        image = "test.com/test/test"
        docker_config, name, create = App()._get_private_registry_config("web", image, registry.get("web", {}))  # noqa
        dockerConfig = json.loads(docker_config)
        expected = {"https://index.docker.io/v1/": {
            "auth": encAuth
        }}
        self.assertEqual(dockerConfig.get('auths'), expected)
        self.assertEqual(name, "private-registry-web-off-cluster")
        self.assertEqual(create, True)

    @override_settings(REGISTRY_LOCATION="ecra")
    def test_get_private_registry_config_bad_registry_location(self, mock_requests):
        registry = {}
        image = "test.com/test/test"
        docker_config, name, create = App()._get_private_registry_config("web", image, registry)
        self.assertEqual(docker_config, None)
        self.assertEqual(name, None)
        self.assertEqual(create, None)

    def test_build_env_vars(self, mock_requests):
        app = App.objects.create(owner=self.user)
        # Make sure an exception is raised when calling without a build available
        with self.assertRaises(DryccException):
            app._build_env_vars(app.release_set.latest(), PTYPE_WEB)
        data = {'image': 'autotest/example', 'stack': 'heroku-18'}
        url = f"/v2/apps/{app.id}/build"
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 201, response.data)
        time_created = app.release_set.latest().created
        self.assertEqual(
            app._build_env_vars(app.release_set.latest(), PTYPE_WEB),
            {
                'DRYCC_APP': app.id,
                'WORKFLOW_RELEASE': 'v2',
                'PORT': 5000,
                'SOURCE_VERSION': '',
                'WORKFLOW_RELEASE_SUMMARY': 'autotest deployed autotest/example',
                'WORKFLOW_RELEASE_CREATED_AT': str(time_created.strftime(
                    settings.DRYCC_DATETIME_FORMAT))
            })
        data['sha'] = 'abc1234'
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 201, response.data)
        time_created = app.release_set.latest().created
        self.assertEqual(
            app._build_env_vars(app.release_set.latest(), PTYPE_WEB),
            {
                'DRYCC_APP': app.id,
                'WORKFLOW_RELEASE': 'v3',
                'PORT': 5000,
                'SOURCE_VERSION': 'abc1234',
                'WORKFLOW_RELEASE_SUMMARY': 'autotest deployed abc1234',
                'WORKFLOW_RELEASE_CREATED_AT': str(time_created.strftime(
                    settings.DRYCC_DATETIME_FORMAT))
            })

    def test_gather_app_settings(self, mock_requests):
        app = App.objects.create(owner=self.user)
        app.save()
        data = {'image': 'autotest/example', 'stack': 'container'}
        url = f"/v2/apps/{app.id}/build"
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 201, response.data)
        Config.objects.create(
            owner=self.user,
            app=app,
            values=[
                {"name": "DRYCC_DEPLOY_TIMEOUT", "value": "60", "group": "global"},
                {"name": "DRYCC_DEPLOY_BATCHES", "value": "3", "group": "global"},
                {
                    "name": "KUBERNETES_POD_TERMINATION_GRACE_PERIOD_SECONDS",
                    "value": "60", "group": "global"
                },
            ]
        )
        s = app._gather_app_settings(app.release_set.latest(),
                                     app.appsettings_set.latest(),
                                     'web',
                                     3)
        assert isinstance(s['deploy_batches'], int)
        assert isinstance(s['deploy_timeout'], int)
        assert isinstance(s['pod_termination_grace_period_seconds'], int)

    def test_app_name_bad_regex(self, mock_requests):
        """
        Create a normal app and then try to do a build on it but include
        extra chars (equal for example) in the name and make sure no new
        apps are created and that the operation errors out
        """
        # create app
        app_id = self.create_app()

        # verify that there is only 1 app and it is the one expected
        response = self.client.get("/v2/apps")
        self.assertEqual(response.status_code, 200, response)
        self.assertEqual(response.data['count'], 1, response.data)
        self.assertEqual(response.data['results'][0]['id'], app_id, response.data)

        # deploy to an app that doesn't exist should fail with 404
        url = "/v2/apps/{}/build".format('={}'.format(app_id))
        body = {'image': 'autotest/example', 'stack': 'container'}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 404, response)

        # verify again that there is only 1 app
        response = self.client.get("/v2/apps")
        self.assertEqual(response.status_code, 200, response)
        self.assertEqual(response.data['count'], 1, response.data)


FAKE_LOG_DATA = bytes("""
2013-08-15 12:41:25 [33454] [INFO] Starting gunicorn 17.5
2013-08-15 12:41:25 [33454] [INFO] Listening at: http://0.0.0.0:5000 (33454)
2013-08-15 12:41:25 [33454] [INFO] Using worker: sync
2013-08-15 12:41:25 [33457] [INFO] Booting worker with pid 33457
""", 'utf-8')
