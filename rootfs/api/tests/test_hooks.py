"""
Unit tests for the Drycc api app.

Run the tests with "./manage.py test api"
"""
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache

from api.tests import adapter, DryccTransactionTestCase
from api.models.app import app_permission_registry
import requests_mock

User = get_user_model()

RSA_PUBKEY = (
    "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQCfQkkUUoxpvcNMkvv7jqnfodgs37M2eBO"
    "APgLK+KNBMaZaaKB4GF1QhTCMfFhoiTW3rqa0J75bHJcdkoobtTHlK8XUrFqsquWyg3XhsT"
    "Yr/3RQQXvO86e2sF7SVDJqVtpnbQGc5SgNrHCeHJmf5HTbXSIjCO/AJSvIjnituT/SIAMGe"
    "Bw0Nq/iSltwYAek1hiKO7wSmLcIQ8U4A00KEUtalaumf2aHOcfjgPfzlbZGP0S0cuBwSqLr"
    "8b5XGPmkASNdUiuJY4MJOce7bFU14B7oMAy2xacODUs1momUeYtGI9T7X2WMowJaO7tP3Gl"
    "sgBMP81VfYTfYChAyJpKp2yoP autotest@autotesting comment"
)

RSA_PUBKEY2 = (
    "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQC4xELdubosJ2/bQuiSUyWclVVa71pXpmq"
    "aXTwfau/XFLgD5yE+TOFbVT22xvEr4AwZqS9w0TBMp4RLfi4pTdjoIK+lau2lDMuEpbF4xg"
    "PWAveAqKuLcKJbJrZQdo5VWn5//7+M1RHQCPqjeN2iS9I3C8yiPg3mMPT2mKuyZYB9VD3hK"
    "mhT4xRAsS6vfKZr7CmFHgAmRBqdaU1RetR5nfTj0R5yyAv7Z2BkE8UhUAseFZ0djBs6kzjs"
    "5ddgM4Gv2Zajs7qVvpVPzZpq3vFB16Q5TMj2YtoYF6UZFFf4u/4KAW8xfYJAFdpNsvh279s"
    "dJS08nTeElUg6pn83A3hqWX+J testing"
)

ECDSA_PUBKEY = (
    "ecdsa-sha2-nistp256 AAAAE2VjZHNhLXNoYTItbmlzdHAyNTYAAAAIbmlzdHAyNTYAAAB"
    "BBCGB0x9lmubbLJTF5NekCI0Cgjyip6jJh/t/qQQi1LAZisbREBJ8Wy+hwSn3tnbf/Imh9X"
    "+MQnrrza0jaQ3QUAQ= autotest@autotesting comment"
)

ED25519_PUBKEY = (
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIAPYa7ztrkGyl/LSpBxv0DjPej74GCSVItX"
    "9Y2+/zxc+ testing"
)

BAD_KEY = (
    "ssh-rsa foooooooooooooooooooooooooooooooooooooooooooooooooooobaaaaaaarrr"
    "rrrrr testing"
)


@requests_mock.Mocker(real_http=True, adapter=adapter)
class HookTest(DryccTransactionTestCase):

    """Tests API hooks used to trigger actions from external components"""

    fixtures = ['tests.json']

    def setUp(self):
        self.user = User.objects.get(username='autotest')
        self.token = self.get_or_create_token(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token)

    def tearDown(self):
        # make sure every test has a clean slate for k8s mocking
        cache.clear()

    def test_key_hook(self, mock_requests):
        """Test fetching keys for an app and a user"""

        # Create app to use
        app_id = self.create_app()

        # give user permission to app
        body = {
            'username': str(self.user),
            'permissions': ','.join(app_permission_registry.shortnames),
        }
        url = f'/v2/apps/{app_id}/perms/'
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 201, response.data)

        # Create rsa key
        body = {'id': str(self.user), 'public': RSA_PUBKEY}
        response = self.client.post('/v2/keys', body)
        self.assertEqual(response.status_code, 201, response.data)
        rsa_pub = response.data['public']

        # Create another rsa key
        body = {'id': str(self.user) + '-2', 'public': RSA_PUBKEY2}
        response = self.client.post('/v2/keys', body)
        self.assertEqual(response.status_code, 201, response.data)
        rsa_pub2 = response.data['public']

        # Create dsa key
        body = {'id': str(self.user) + '-3', 'public': ECDSA_PUBKEY}
        response = self.client.post('/v2/keys', body)
        self.assertEqual(response.status_code, 201, response.data)
        dsa_pub = response.data['public']

        # Create ed25519 key
        body = {'id': str(self.user) + '-4', 'public': ED25519_PUBKEY}
        response = self.client.post('/v2/keys', body)
        self.assertEqual(response.status_code, 201, response.data)
        ed25519_pub = response.data['public']

        # Attempt adding a bad SSH pubkey
        body = {'id': str(self.user) + '-5', 'public': BAD_KEY}
        response = self.client.post('/v2/keys', body)
        self.assertEqual(response.status_code, 400, response.data)

        # Make sure 404 is returned for a random app
        url = '/v2/hooks/keys/doesnotexist'
        response = self.client.get(url, HTTP_X_DRYCC_SERVICE_KEY=settings.SERVICE_KEY)
        self.assertEqual(response.status_code, 404)

        # Test app that exists
        url = '/v2/hooks/keys/{}'.format(app_id)
        response = self.client.get(url, HTTP_X_DRYCC_SERVICE_KEY=settings.SERVICE_KEY)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data, {"autotest": [
            {'key': rsa_pub, 'fingerprint': '54:6d:da:1f:91:b5:2b:6f:a2:83:90:c4:f9:73:76:f5'},
            {'key': rsa_pub2, 'fingerprint': '43:fd:22:bc:dc:ca:6a:28:ba:71:4c:18:41:1d:d1:e2'},
            {'key': dsa_pub, 'fingerprint': '28:dd:ef:f9:12:ab:f9:80:6f:4c:0a:e7:e7:a4:59:95'},
            {'key': ed25519_pub, 'fingerprint': '75:9a:b3:81:13:40:c2:78:32:aa:e3:b4:93:2a:12:c9'}
        ]})

        # Test against an app that exist but user does not
        url = '/v2/hooks/keys/{}/foooooo'.format(app_id)
        response = self.client.get(url, HTTP_X_DRYCC_SERVICE_KEY=settings.SERVICE_KEY)
        self.assertEqual(response.status_code, 404)

        # Test against an app that exists and user that does
        url = '/v2/hooks/keys/{}/{}'.format(app_id, str(self.user))
        response = self.client.get(url, HTTP_X_DRYCC_SERVICE_KEY=settings.SERVICE_KEY)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data, {"autotest": [
            {'key': rsa_pub, 'fingerprint': '54:6d:da:1f:91:b5:2b:6f:a2:83:90:c4:f9:73:76:f5'},
            {'key': rsa_pub2, 'fingerprint': '43:fd:22:bc:dc:ca:6a:28:ba:71:4c:18:41:1d:d1:e2'},
            {'key': dsa_pub, 'fingerprint': '28:dd:ef:f9:12:ab:f9:80:6f:4c:0a:e7:e7:a4:59:95'},
            {'key': ed25519_pub, 'fingerprint': '75:9a:b3:81:13:40:c2:78:32:aa:e3:b4:93:2a:12:c9'}

        ]})

        # Fetch a valid ssh key
        url = '/v2/hooks/key/54:6d:da:1f:91:b5:2b:6f:a2:83:90:c4:f9:73:76:f5'
        response = self.client.get(url, HTTP_X_DRYCC_SERVICE_KEY=settings.SERVICE_KEY)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data, {
            "username": str(self.user),
            "apps": [
                app_id
            ]
        })

        # Fetch an non-existent base64 encoded ssh key
        url = '/v2/hooks/key/54:6d:da:1f:91:b5:2b:6f:a2:83:90:c4:f9:73:76:wooooo'
        response = self.client.get(url, HTTP_X_DRYCC_SERVICE_KEY=settings.SERVICE_KEY)
        self.assertEqual(response.status_code, 404)

        # Fetch an invalid (not encoded) ssh key
        url = '/v2/hooks/key/nope'
        response = self.client.get(url, HTTP_X_DRYCC_SERVICE_KEY=settings.SERVICE_KEY)
        self.assertEqual(response.status_code, 404)

    def test_build_hook(self, mock_requests):
        """Test creating a Build via an API Hook"""
        app_id = self.create_app()
        url = '/v2/hooks/build'
        body = {'receive_user': 'autotest',
                'receive_repo': app_id,
                'image': f'{app_id}:v2',
                'stack': 'container'}
        # post the build without an auth token
        self.client.credentials()
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 401, response.data)
        # post the build with the service key
        response = self.client.post(url, body,
                                    HTTP_X_DRYCC_SERVICE_KEY=settings.SERVICE_KEY)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn('release', response.data)
        self.assertIn('version', response.data['release'])

    def test_build_hook_slug_url(self, mock_requests):
        """Test creating a slug_url build via an API Hook"""
        app_id = self.create_app()
        url = '/v2/hooks/build'
        body = {'receive_user': 'autotest',
                'receive_repo': app_id,
                'image': 'http://example.com/slugs/foo-12345354.tar.gz',
                'stack': 'container'}

        # post the build without an auth token
        self.client.credentials()
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 401, response.data)

        # post the build with the service key
        response = self.client.post(url, body,
                                    HTTP_X_DRYCC_SERVICE_KEY=settings.SERVICE_KEY)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn('release', response.data)
        self.assertIn('version', response.data['release'])

    def test_build_hook_procfile(self, mock_requests):
        """Test creating a Procfile build via an API Hook"""
        app_id = self.create_app()

        build = {'username': 'autotest', 'app': app_id}
        url = '/v2/hooks/build'
        PROCFILE = {'web': 'node server.js', 'worker': 'node worker.js'}
        SHA = 'ecdff91c57a0b9ab82e89634df87e293d259a3aa'
        body = {'receive_user': 'autotest',
                'receive_repo': app_id,
                'image': f'{app_id}:v2',
                'stack': 'heroku-18',
                'sha': SHA,
                'procfile': PROCFILE}

        # post the build with the service key
        response = self.client.post(url, body,
                                    HTTP_X_DRYCC_SERVICE_KEY=settings.SERVICE_KEY)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn('release', response.data)
        self.assertIn('version', response.data['release'])

        # make sure build fields were populated
        url = f'/v2/apps/{app_id}/build'
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.data)
        build = response.data
        self.assertEqual(build['sha'], SHA)
        self.assertEqual(build['procfile'], PROCFILE)

        # test listing/retrieving container info
        url = f"/v2/apps/{app_id}/pods/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertPodContains(response.data['results'], app_id, 'web', 'v2')

        # post the build without an auth token
        self.client.credentials()
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 401, response.data)

    def test_build_hook_dockerfile(self, mock_requests):
        """Test creating a Dockerfile build via an API Hook"""
        app_id = self.create_app()
        build = {'username': 'autotest', 'app': app_id}
        url = '/v2/hooks/build'
        SHA = 'ecdff91c57a0b9ab82e89634df87e293d259a3aa'
        DOCKERFILE = """FROM busybox
        CMD /bin/true"""

        body = {'receive_user': 'autotest',
                'receive_repo': app_id,
                'image': f'{app_id}:v2',
                'stack': 'container',
                'sha': SHA,
                'dockerfile': DOCKERFILE}
        # post the build with the service key
        response = self.client.post(url, body,
                                    HTTP_X_DRYCC_SERVICE_KEY=settings.SERVICE_KEY)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn('release', response.data)
        self.assertIn('version', response.data['release'])
        # make sure build fields were populated
        url = f'/v2/apps/{app_id}/build'
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.data)
        build = response.data
        self.assertEqual(build['sha'], SHA)
        self.assertEqual(build['dockerfile'], DOCKERFILE)
        # test default container
        url = f"/v2/apps/{app_id}/pods/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertPodContains(response.data['results'], app_id, 'web', 'v2')

        # post the build without an auth token
        self.client.credentials()
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 401, response.data)

    def test_config_hook(self, mock_requests):
        """Test reading Config via an API Hook"""
        app_id = self.create_app()
        url = f'/v2/apps/{app_id}/config'
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn('values', response.data)
        values = response.data['values']
        # prepare the config hook
        url = '/v2/hooks/config'
        body = {'receive_user': 'autotest',
                'receive_repo': app_id}
        # post without an auth token
        self.client.credentials()
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 401, response.data)
        # post with the service key
        response = self.client.post(url, body,
                                    HTTP_X_DRYCC_SERVICE_KEY=settings.SERVICE_KEY)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn('values', response.data)
        self.assertEqual(values, response.data['values'])

    def test_admin_can_hook(self, mock_requests):
        """Administrator should be able to create build hooks on non-admin apps.
        """
        """Test creating a Push via the API"""
        user = User.objects.get(username='autotest2')
        token = self.get_or_create_token(user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)

        app_id = self.create_app()
        # prepare a push body
        DOCKERFILE = """
        FROM busybox
        CMD /bin/true
        """
        body = {'receive_user': 'autotest',
                'receive_repo': app_id,
                'image': f'{app_id}:v2',
                'stack': 'container',
                'sha': 'ecdff91c57a0b9ab82e89634df87e293d259a3aa',
                'dockerfile': DOCKERFILE}
        url = '/v2/hooks/build'
        response = self.client.post(url, body,
                                    HTTP_X_DRYCC_SERVICE_KEY=settings.SERVICE_KEY)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['release']['version'], 2)
