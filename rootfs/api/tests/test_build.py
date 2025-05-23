"""
Unit tests for the Drycc api app.

Run the tests with "./manage.py test api"
"""
import json

from django.contrib.auth import get_user_model
from django.core.cache import cache
from unittest import mock

from api.models.build import Build
from api.models.app import App
from api.models.base import PTYPE_WEB
from scheduler import KubeException

from api.tests import adapter, DryccTransactionTestCase
import requests_mock

User = get_user_model()


@requests_mock.Mocker(real_http=True, adapter=adapter)
class BuildTest(DryccTransactionTestCase):

    """Tests build notification from build system"""

    fixtures = ['tests.json']

    def setUp(self):
        self.user = User.objects.get(username='autotest')
        self.token = self.get_or_create_token(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token)

    def tearDown(self):
        # make sure every test has a clean slate for k8s mocking
        cache.clear()

    def test_build(self, mock_requests):
        """
        Test that a null build is created and that users can post new builds
        """
        app_id = self.create_app()

        # check to see that no initial build was created
        url = f"/v2/apps/{app_id}/build"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.data)

        # post a new build
        body = {'image': 'autotest/example', 'stack': 'container'}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 201, response.data)
        build1 = response.data
        self.assertEqual(response.data['image'], body['image'])

        # read the build
        url = f"/v2/apps/{app_id}/build"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.data)
        build2 = response.data
        self.assertEqual(build1, build2)

        # post a new build
        url = f"/v2/apps/{app_id}/build"
        body = {'image': 'autotest/example', 'stack': 'container'}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 201, response.data)
        build3 = response.data
        self.assertEqual(response.data['image'], body['image'])
        self.assertNotEqual(build2['uuid'], build3['uuid'])

        # disallow put/patch/delete
        response = self.client.put(url)
        self.assertEqual(response.status_code, 405, response.content)
        response = self.client.patch(url)
        self.assertEqual(response.status_code, 405, response.content)
        response = self.client.delete(url)
        self.assertEqual(response.status_code, 405, response.content)

    def test_response_data(self, mock_requests):
        """Test that the serialized response contains only relevant data."""
        app_id = self.create_app()

        # post an image as a build
        url = f"/v2/apps/{app_id}/build"
        body = {'image': 'autotest/example', 'stack': 'container'}
        response = self.client.post(url, body)

        for key in response.data:
            self.assertIn(key, ['uuid', 'owner', 'created', 'updated', 'app', 'dockerfile',
                                'dryccfile', 'image', 'stack', 'procfile', 'sha'])
        expected = {
            'owner': self.user.username,
            'app': app_id,
            'dockerfile': '',
            'image': 'autotest/example',
            'stack': 'container',
            'procfile': {},
            'sha': ''
        }
        self.assertEqual(response.data, expected | response.data)

    def test_build_default_containers(self, mock_requests):
        app_id = self.create_app()

        # post an image as a build
        url = f"/v2/apps/{app_id}/build"
        body = {'image': 'autotest/example', 'stack': 'container'}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 201, response.data)

        url = f"/v2/apps/{app_id}/pods"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertPodContains(response.data['results'], app_id, 'web', "v2", "up")

        # post an image as a build with a procfile
        app_id = self.create_app()
        # post an image as a build
        url = f"/v2/apps/{app_id}/build"
        body = {
            'image': 'autotest/example',
            'stack': 'heroku-18',
            'procfile': {
                'web': 'node worker.js'
            }
        }
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 201, response.data)

        url = f"/v2/apps/{app_id}/pods/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertPodContains(response.data['results'], app_id, 'web', "v2", "up")

        # start with a new app
        app_id = self.create_app()
        # post a new build with procfile
        url = f"/v2/apps/{app_id}/build"
        body = {
            'image': 'autotest/example',
            'sha': 'a'*40,
            'stack': 'container',
            'dockerfile': "FROM scratch"
        }
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 201, response.data)

        url = f"/v2/apps/{app_id}/pods/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertPodContains(response.data['results'], app_id, 'web', "v2", "up")
        # start with a new app
        app_id = self.create_app()

        # post a new build with procfile
        url = f"/v2/apps/{app_id}/build"
        body = {
            'image': 'autotest/example',
            'sha': 'a'*40,
            'stack': 'container',
            'dockerfile': "FROM scratch",
            'procfile': {
                'worker': 'node worker.js'
            }
        }
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 201, response.data)

        url = f"/v2/apps/{app_id}/pods/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['results'], [])
        # start with a new app
        app_id = self.create_app()
        # post a new build with procfile

        url = f"/v2/apps/{app_id}/build"
        body = {
            'image': 'autotest/example',
            'sha': 'a'*40,
            'stack': 'heroku-18',
            'procfile': {
                'web': 'node server.js',
                'worker': 'node worker.js'
            }
        }
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 201, response.data)

        url = f"/v2/apps/{app_id}/pods/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertPodContains(response.data['results'], app_id, 'web', "v2", "up")

        # start with a new app
        app_id = self.create_app()
        # post a new build with procfile and no routable type

        url = f"/v2/apps/{app_id}/build"
        body = {
            'image': 'autotest/example',
            'sha': 'a'*40,
            'stack': 'heroku-18',
            'procfile': {
                'rake': 'node server.js',
                'worker': 'node worker.js'
            }
        }
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 201, response.data)

    def test_build_forgotten_procfile(self, mock_requests):
        """
        Test that when a user first posts a build with a Procfile
        and then later without it that missing process are actually
        scaled down
        """
        # start with a new app
        app_id = self.create_app()

        # post a new build with procfile
        url = f"/v2/apps/{app_id}/build"
        body = {
            'image': 'autotest/example',
            'sha': 'a'*40,
            'stack': 'heroku-18',
            'procfile': {
                'web': 'node server.js',
                'worker': 'node worker.js'
            }
        }
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 201, response.data)
        # verify web
        url = f"/v2/apps/{app_id}/pods/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertPodContains(response.data['results'], app_id, 'web', "v2", "up")

        # scale worker
        url = f"/v2/apps/{app_id}/ptypes/scale"
        body = {'worker': 1}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 204, response.data)

        # verify worker
        url = f"/v2/apps/{app_id}/pods/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertPodContains(response.data['results'], app_id, 'worker', "v2", "up")

        # do another deploy for this time forget Procfile
        url = f"/v2/apps/{app_id}/build"
        body = {'image': 'autotest/example', 'stack': 'container'}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 201, response.data)

        # verify worker is not there, only web
        url = f"/v2/apps/{app_id}/pods/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual([item for item in response.data['results'] if item["type"] != "web"], [])

        # look at the app structure
        url = f"/v2/apps/{app_id}"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.json()['structure'], {'web': 1})

        # do another deploy for this time forget Procfile
        url = f"/v2/apps/{app_id}/build"
        body = {'image': 'autotest/example:v3', 'stack': 'container'}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 201, response.data)

        # look at the app structure
        url = f"/v2/apps/{app_id}"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.json()['structure'], {'web': 1})

    def test_build_no_remove_process(self, mock_requests):
        """
        Specifically test PROCFILE_REMOVE_PROCS_ON_DEPLOY being turned off
        and a user posting a new build without a Procfile that was previously
        applied
        """
        # start with a new app
        app_id = self.create_app()
        # Set routable to false
        response = self.client.post(f'/v2/apps/{app_id}/settings', {'autodeploy': False})
        self.assertEqual(response.status_code, 201, response.data)

        # post a new build with procfile
        url = f"/v2/apps/{app_id}/build"
        body = {
            'image': 'autotest/example',
            'sha': 'a'*40,
            'stack': 'heroku-18',
            'procfile': {
                'web': 'node server.js',
                'task': 'node task.js',
                'worker': 'node worker.js'
            }
        }
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 201, response.data)

        # deploy
        response = self.client.post(f"/v2/apps/{app_id}/releases/deploy/")
        self.assertEqual(response.status_code, 204, response.data)

        # scale worker
        url = f"/v2/apps/{app_id}/ptypes/scale"
        body = {'worker': 1, 'task': 1}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 204, response.data)

        # verify worker
        url = f"/v2/apps/{app_id}/pods/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertPodContains(response.data['results'], app_id, 'task', "v2", "up")
        self.assertPodContains(response.data['results'], app_id, 'worker', "v2", "up")

        # do another deploy for this time forget Procfile
        url = f"/v2/apps/{app_id}/build"
        body = {'image': 'autotest/example:v10', 'stack': 'container'}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 201, response.data)

        # deploy
        response = self.client.post(f"/v2/apps/{app_id}/releases/deploy/")
        self.assertEqual(response.status_code, 204, response.data)

        # verify web
        url = f"/v2/apps/{app_id}/pods/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            set([item["type"] for item in response.data['results']]),
            set(["web", "task", "worker"]),
        )
        self.assertPodContains(response.data['results'], app_id, 'web', "v3", "up")

        # look at the app structure
        url = f"/v2/apps/{app_id}"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.json()['structure'], {'web': 1, 'task': 1, 'worker': 1})

        # clean worker, repicas 1 not allow
        response = self.client.post('/v2/apps/{}/ptypes/clean'.format(app_id), {"ptypes": "task"})
        self.assertEqual(response.status_code, 400, response.data)

        # scale task
        url = f"/v2/apps/{app_id}/ptypes/scale"
        body = {'task': 0}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 204, response.data)

        # clean worker, repicas 0 allow
        response = self.client.post('/v2/apps/{}/ptypes/clean'.format(app_id), {"ptypes": "task"})
        self.assertEqual(response.status_code, 204, response.data)

        # look at the app structure
        url = f"/v2/apps/{app_id}"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.json()['structure'], {'web': 1, 'worker': 1})

        # ptypes is a required field
        response = self.client.post('/v2/apps/{}/ptypes/clean'.format(app_id))
        self.assertEqual(response.status_code, 400, response.data)

        url = f"/v2/apps/{app_id}/ptypes/scale"
        body = {'worker': 0}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 204, response.data)

        # clean worker
        response = self.client.post(
            '/v2/apps/{}/ptypes/clean'.format(app_id),
            {"ptypes": "worker"})
        self.assertEqual(response.status_code, 204, response.data)

        # look at the app structure
        url = f"/v2/apps/{app_id}"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.json()['structure'], {'web': 1})

        # do another deploy for this time forget Procfile
        url = f"/v2/apps/{app_id}/build"
        body = {'image': 'autotest/example:v11', 'stack': 'container'}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 201, response.data)

        # deploy
        response = self.client.post(f"/v2/apps/{app_id}/releases/deploy/")
        self.assertEqual(response.status_code, 204, response.data)

        # look at the app structure
        url = f"/v2/apps/{app_id}"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.json()['structure'], {'web': 1})

    def test_build_str(self, mock_requests):
        """Test the text representation of a build."""
        app_id = self.create_app()

        # post a new build
        url = f"/v2/apps/{app_id}/build"
        body = {'image': 'autotest/example', 'stack': 'container'}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 201, response.data)
        build = Build.objects.get(uuid=response.data['uuid'])
        self.assertEqual(str(build), "{}-{}".format(
                         response.data['app'], str(response.data['uuid'])[:7]))

    def test_admin_can_create_builds_on_other_apps(self, mock_requests):
        """If a user creates an application, an administrator should be able
        to push builds.
        """
        # create app as non-admin
        user = User.objects.get(username='autotest2')
        token = self.get_or_create_token(user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)

        app_id = self.create_app()

        # post a new build as admin
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token)
        url = f"/v2/apps/{app_id}/build"
        body = {'image': 'autotest/example', 'stack': 'container'}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 201, response.data)

        build = Build.objects.get(uuid=response.data['uuid'])
        self.assertEqual(str(build), "{}-{}".format(
                         response.data['app'], str(response.data['uuid'])[:7]))

    def test_unauthorized_user_cannot_modify_build(self, mock_requests):
        """
        An unauthorized user should not be able to modify other builds.

        Since an unauthorized user can't access the application, these
        requests should return a 403.
        """
        app_id = self.create_app()

        unauthorized_user = User.objects.get(username='autotest2')
        unauthorized_token = self.get_or_create_token(unauthorized_user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + unauthorized_token)
        url = '/v2/apps/{}/build'.format(app_id)
        body = {'image': 'foo'}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 403)

    def test_new_build_does_not_scale_up_automatically(self, mock_requests):
        """
        After the first initial deploy, if the containers are scaled down to zero,
        they should stay that way on a new release.
        """
        app_id = self.create_app()

        # post a new build
        url = f"/v2/apps/{app_id}/build"
        body = {
            'image': 'autotest/example',
            'sha': 'a'*40,
            'stack': 'heroku-18',
            'procfile': {
                'web': 'node server.js',
                'worker': 'node worker.js'
            }
        }
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 201, response.data)

        url = f"/v2/apps/{app_id}/pods/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertPodContains(response.data['results'], app_id, 'web', "v2", "up")

        # scale to zero
        url = f"/v2/apps/{app_id}/ptypes/scale"
        body = {'web': 0}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 204, response.data)

        # post another build
        url = f"/v2/apps/{app_id}/build"
        body = {
            'image': 'autotest/example',
            'sha': 'a'*40,
            'stack': 'heroku-18',
            'procfile': {
                'web': 'node server.js',
                'worker': 'node worker.js'
            }
        }
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 201, response.data)
        url = f"/v2/apps/{app_id}/pods/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(len(response.data['results']), 0)

    def test_build_image_in_registry_ok(self, mock_requests):
        """When the image is already in the drycc registry no pull/tag/push happens"""
        app_id = self.create_app()

        # post an image as a build using registry hostname
        url = f"/v2/apps/{app_id}/build"
        image = 'registry.drycc.cc:5000/autotest/example'
        body = {'image': image, 'stack': 'container'}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 201, response.data)

        build = Build.objects.get(uuid=response.data['uuid'])
        release = build.app.release_set.latest()
        self.assertEqual(release.get_deploy_image(PTYPE_WEB), image)

        # post an image as a build using registry hostname + port
        url = f"/v2/apps/{app_id}/build"
        image = 'registry.drycc.cc:5000/autotest/example'
        body = {'image': image, 'stack': 'container'}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 201, response.data)

        build = Build.objects.get(uuid=response.data['uuid'])
        release = build.app.release_set.latest()
        self.assertEqual(release.get_deploy_image(PTYPE_WEB), image)

    def test_build_image_in_registry_err(self, mock_requests):
        """When the image is already in the drycc registry no pull/tag/push happens"""
        app_id = self.create_app()

        # post an image as a build using registry hostname
        url = f"/v2/apps/{app_id}/build"
        for host in ['127.0.0.1', 'localhost', 'localhost:5000', '127.0.0.1:5000']:
            image = f'{host}/autotest/example'
            body = {'image': image, 'stack': 'container'}
            response = self.client.post(url, body)
            self.assertEqual(response.status_code, 400, response.data)

    def test_build_image_in_registry_with_auth(self, mock_requests):
        """add authentication to the build"""
        app_id = self.create_app()

        # post an image as a build using registry hostname
        url = f"/v2/apps/{app_id}/build"
        image = 'autotest/example'
        response = self.client.post(url, {'image': image, 'stack': 'container'})
        self.assertEqual(response.status_code, 201, response.data)

        # add the required PORT information
        url = f'/v2/apps/{app_id}/config'
        body = {'values': [{"name": "PORT", "group": "global", "value": "80"}]}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 201, response.data)

        # set some registry information
        url = f'/v2/apps/{app_id}/config'
        body = {'registry': {'web': {'username': 'bob', 'password': 'zoomzoom'}}}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 201, response.data)

    def test_build_image_in_registry_with_auth_no_port(self, mock_requests):
        """add authentication to the build but with no PORT config"""
        app_id = self.create_app()

        # post an image as a build using registry hostname
        url = f"/v2/apps/{app_id}/build"
        image = 'autotest/example'
        response = self.client.post(url, {'image': image, 'stack': 'container'})
        self.assertEqual(response.status_code, 201, response.data)

        # set some registry information
        url = f'/v2/apps/{app_id}/config'
        body = {'registry': json.dumps({'web': {'username': 'bob', 'password': 'zoomzoom'}})}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 201, response.data)

    def test_release_create_failure(self, mock_requests):
        """
        Cause an Exception in app.deploy to cause a failed release in build.create
        """
        app_id = self.create_app()

        # deploy app to get a build
        url = f"/v2/apps/{app_id}/build"
        body = {'image': 'autotest/example', 'stack': 'container'}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['image'], body['image'])

        with mock.patch('api.models.app.App.deploy') as mock_deploy:
            mock_deploy.side_effect = Exception('Boom!')

            url = f"/v2/apps/{app_id}/build"
            body = {'image': 'autotest/example'}
            response = self.client.post(url, body)
            self.assertEqual(response.status_code, 400, response.data)

    def test_build_deploy_kube_failure(self, mock_requests):
        """
        Cause an Exception in scheduler.deploy
        """
        app_id = self.create_app()

        with mock.patch('scheduler.KubeHTTPClient.deploy') as mock_deploy:
            mock_deploy.side_effect = KubeException('Boom!')

            url = f"/v2/apps/{app_id}/build"
            body = {'image': 'autotest/example', 'stack': 'container'}
            response = self.client.post(url, body)
            self.assertEqual(response.status_code, 201, response.data)
            data = self.client.get(f"/v2/apps/{app_id}/releases/", body).json()
            self.assertEqual(data["results"][0]["state"], "crashed", data)

    def test_build_failures(self, mock_requests):
        app_id = self.create_app()
        app = App.objects.get(id=app_id)

        # deploy app to get a build
        url = f"/v2/apps/{app_id}/build"
        body = {'image': 'autotest/example', 'stack': 'container'}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['image'], body['image'])
        success_build = app.release_set.latest().build

        # create a failed build to check that failed release is created
        with mock.patch('api.models.app.App.deploy') as mock_deploy:
            mock_deploy.side_effect = Exception('Boom!')
            url = f"/v2/apps/{app_id}/build"
            body = {'image': 'autotest/example:v100', 'stack': 'container'}
            response = self.client.post(url, body)
            self.assertEqual(response.status_code, 201, response.data)
            data = self.client.get(f"/v2/apps/{app_id}/releases/", body).json()
            self.assertEqual(data["results"][0]["state"], "crashed", data)

        # create a config to see that the new release is created with the last successful build
        url = f"/v2/apps/{app_id}/config"
        body = {'values': [{"name": "Test", "group": "global", "value": "test"}]}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(app.release_set.latest().version, 4)
        self.assertEqual(app.release_set.latest().build, success_build)
        self.assertEqual(app.build_set.count(), 2)

    def test_build_validate_procfile(self, mock_requests):
        app_id = self.create_app()

        # deploy app with incorrect proctype
        url = f"/v2/apps/{app_id}/build"
        body = {
            'image': 'autotest/example',
            'stack': 'heroku-18',
            'sha': 'a'*40,
            'procfile': {
                'web': 'node server.js',
                'worker_test': 'node worker.js'
            }
        }
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 400, response.data)

        url = f"/v2/apps/{app_id}/build"
        body = {
            'image': 'autotest/example',
            'stack': 'heroku-18',
            'sha': 'a'*40,
            'procfile': {
                'web': 'node server.js',
                'Worker-test1': 'node worker.js'
            }
        }
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 400, response.data)

        url = f"/v2/apps/{app_id}/build"
        body = {
            'image': 'autotest/example',
            'stack': 'heroku-18',
            'sha': 'a'*40,
            'procfile': {
                'web': 'node server.js',
                '-': 'node worker.js'
            }
        }
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 400, response.data)

        url = f"/v2/apps/{app_id}/build"
        body = {
            'image': 'autotest/example',
            'stack': 'heroku-18',
            'sha': 'a'*40,
            'procfile': {
                'web': 'node server.js',
                'worker-': 'node worker.js'
            }
        }
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 400, response.data)
        url = f"/v2/apps/{app_id}/build"
        body = {
            'image': 'autotest/example',
            'stack': 'heroku-18',
            'sha': 'a'*40,
            'procfile': {
                'web': 'node server.js',
                '-worker': 'node worker.js'
            }
        }
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 400, response.data)
        # deploy app with empty command
        url = f"/v2/apps/{app_id}/build"
        body = {
            'image': 'autotest/example',
            'stack': 'heroku-18',
            'sha': 'a'*40,
            'procfile': {
                'web': 'node server.js',
                'worker': ''
            }
        }
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 400, response.data)

        url = f"/v2/apps/{app_id}/build"
        body = {
            'image': 'autotest/example',
            'stack': 'heroku-18',
            'sha': 'a'*40,
            'procfile': {
                'web': 'node server.js',
                'worker-test1': 'node worker.js'
            }
        }
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 201, response.data)

    def test_dryccfile_ok(self, mock_requests):
        app_id = self.create_app()
        url = f"/v2/apps/{app_id}/build"
        default_image = "autotest/example"
        run_image = "127.0.0.1:7070/myapp/run:git-123fsa1"
        web_image = "127.0.0.1:7070/myapp/web:git-123fsa1"
        worker_image = "127.0.0.1:7070/myapp/worker:git-123fsa1"
        body = {
            'image': 'autotest/example',
            'stack': 'heroku-18',
            'sha': 'a'*40,
            "dryccfile": {
                "pipeline": {
                    "web.yaml": {
                        "kind": "pipeline",
                        "ptype": "web",
                        "build": {
                            "docker": "Dockerfile",
                            "arg": {
                                "FOO": "bar",
                                "RAILS_ENV": "development",
                            },
                        },
                        "run": {"command": ["./deployment-tasks.sh"], "image": run_image},
                        "deploy": {
                            "command": ["bash", "-c"],
                            "args": ["bundle exec puma -C config/puma.rb"],
                            "image": "127.0.0.1:7070/myapp/web:git-123fsa1",
                        },
                    },
                    "worker.yaml": {
                        "kind": "pipeline",
                        "ptype": "worker",
                        "build": {
                            "docker": "worker/Dockerfile",
                            "arg": {
                                "FOO": "bar",
                                "RAILS_ENV": "development",
                            },
                        },
                        "run": {"command": ["./deployment-tasks.sh"], "image": run_image},
                        "deploy": {
                            "command": ["bash", "-c"],
                            "args": ["python myworker.py"],
                            "image": "127.0.0.1:7070/myapp/worker:git-123fsa1"
                        },
                    },
                },
            },
        }
        with mock.patch('scheduler.resources.pod.Pod.watch') as mock_kube:
            mock_kube.return_value = ['up', 'down']
            response = self.client.post(url, body)
            self.assertEqual(response.status_code, 201, response.data)
            data = self.client.get(f"/v2/apps/{app_id}/releases/", body).json()
            self.assertEqual(data["results"][0]["state"], "succeed", data)
            app = App.objects.get(id=app_id)
            for pod in app.list_pods():
                if pod['type'] == 'run':
                    self.assertEqual(pod["state"], "down", pod)
                elif pod['type'] == 'web':
                    self.assertEqual(pod["state"], "up", pod)
            release = self.client.get(f"/v2/apps/{app_id}/releases/", body).json()["results"][0]
            self.assertEqual(release["state"], "succeed", data)
            self.assertEqual(release["version"], 2, data)
            release_obj = app.release_set.filter(version=release["version"])[0]
            runners = release_obj.get_runners(["web"])
            self.assertEqual(len(runners), 1)
            self.assertEqual(runners[0]["image"], run_image, data)
            self.assertEqual(release_obj.get_deploy_image("web"), web_image, data)
            self.assertEqual(release_obj.get_deploy_image("worker"), worker_image, data)
            self.assertEqual(release_obj.get_deploy_image("noexist"), default_image, data)

    def test_dryccfile_format(self, mock_requests):
        body = {
            'image': 'autotest/example',
            'stack': 'heroku-18',
            'sha': 'a'*40,
            'dryccfile': {
                "pipeline": {
                    "web.yaml": {
                        "kind": "pipeline",
                        "ptype": "web",
                        "build": {
                            "docker": "Dockerfile",
                            "arg": {
                                "FOO": "bar",
                                "RAILS_ENV": "development",
                            },
                        },
                    },
                    "worker.yaml": {
                        "kind": "pipeline",
                        "ptype": "worker",
                        "build": {
                            "docker": "worker/Dockerfile",
                            "arg": {
                                "FOO": "bar",
                                "RAILS_ENV": "development",
                            },
                        },
                    },
                },
            },
        }
        with mock.patch('scheduler.resources.pod.Pod.watch') as mock_kube:
            mock_kube.return_value = ['up', 'down']
            app_id = self.create_app()
            url = f"/v2/apps/{app_id}/build"
            response = self.client.post(url, body)
            self.assertEqual(response.status_code, 400, response.data)
            body['dryccfile']['pipeline']["web.yaml"]['deploy'] = {'image': "127.0.0.1/cat/cat"}
            response = self.client.post(url, body)
            self.assertEqual(response.status_code, 400, response.data)
            body['dryccfile']['pipeline']["worker.yaml"]['deploy'] = {'image': "127.0.0.1/cat/cat"}
            response = self.client.post(url, body)
            self.assertEqual(response.status_code, 201, response.data)
            body['dryccfile']['pipeline']["web.yaml"]['run'] = {
                'command': ["bash", "-c"], 'args': ["ls /"]}
            body['dryccfile']['pipeline']["worker.yaml"]['run'] = {
                'command': ["bash", "-c"], 'args': ["ls /"]}
            response = self.client.post(url, body)
            self.assertEqual(response.status_code, 201, response.data)
            body['dryccfile']['pipeline']["web.yaml"] = {}
            response = self.client.post(url, body)
            self.assertEqual(response.status_code, 400, response.data)
            body['dryccfile'] = {}
            body['procfile'] = {
                'web': 'node server.js',
                'worker-test1': 'node worker.js'
            }
            response = self.client.post(url, body)
            self.assertEqual(response.status_code, 201, response.data)
