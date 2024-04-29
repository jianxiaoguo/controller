from django.test import tag
from django.contrib.auth import get_user_model
from api.tests import DryccTestCase

User = get_user_model()


class TestAppPerms(DryccTestCase):

    fixtures = ['test_sharing.json']

    @tag('auth')
    def setUp(self):
        self.user = User.objects.get(username='autotest-1')
        self.token = self.get_or_create_token(self.user)
        # Always have first user authed coming into tests
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token)

        self.user2 = User.objects.get(username='autotest-2')
        self.token2 = self.get_or_create_token(self.user2)
        self.user3 = User.objects.get(username='autotest-3')
        self.token3 = self.get_or_create_token(self.user3)

    @tag('auth')
    def test_create(self):
        # check that user 1 sees her lone app and user 2's app
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token)
        response = self.client.get('/v2/apps')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(len(response.data['results']), 2)
        app_id = response.data['results'][0]['id']

        # check that user 2 can only see his app
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token2)
        response = self.client.get('/v2/apps')
        self.assertEqual(len(response.data['results']), 1)
        # check that user 2 can't see any of the app's builds, configs,
        # containers, limits, or releases
        for model in ['builds', 'config', 'pods', 'releases']:
            response = self.client.get("/v2/apps/{}/{}/".format(app_id, model))
            msg = "Failed: status '%s', and data '%s'" % (response.status_code, response.data)
            self.assertEqual(response.status_code, 403, msg=msg)
            self.assertEqual(response.data['detail'],
                             'You do not have permission to perform this action.', msg=msg)

        # TODO: test that git pushing to the app fails
        # give user 2 permission to user 1's app
        url = "/v2/apps/{}/perms".format(app_id)
        body = {'username': 'autotest-2'}
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token)
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 201, response.data)

        # check that user 2 can see the app
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token2)
        response = self.client.get('/v2/apps')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(len(response.data['results']), 2)

        # check that user 2 sees (empty) results now for builds, containers,
        # and releases. (config and limit will still give 404s since we didn't
        # push a build here.)
        for model in ['builds', 'releases']:
            response = self.client.get("/v2/apps/{}/{}/".format(app_id, model))
            self.assertEqual(len(response.data['results']), 0)
        # TODO:  check that user 2 can git push the app

    @tag('auth')
    def test_create_errors(self):
        # check that user 1 sees her lone app
        response = self.client.get('/v2/apps')
        app_id = response.data['results'][0]['id']

        # check that user 2 can't create a permission
        url = "/v2/apps/{}/perms".format(app_id)
        body = {'username': 'autotest-2'}
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token2)
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 403)

    @tag('auth')
    def test_delete(self):
        # give user 2 permission to user 1's app
        response = self.client.get('/v2/apps')
        app_id = response.data['results'][0]['id']
        url = "/v2/apps/{}/perms".format(app_id)
        body = {'username': 'autotest-2'}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 201, response.data)

        # check that user 2 can see the app as well as his own
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token2)
        response = self.client.get('/v2/apps')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(len(response.data['results']), 2)

        # delete permission to user 1's app
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token)
        url = "/v2/apps/{}/perms/{}".format(app_id, 'autotest-2')
        response = self.client.delete(url)
        self.assertEqual(response.status_code, 204, response.data)
        self.assertIsNone(response.data)

        # check that user 2 can only see his app
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token2)
        response = self.client.get('/v2/apps')
        self.assertEqual(len(response.data['results']), 1)

        # delete permission to user 1's app again, expecting an error
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token)
        response = self.client.delete(url)
        self.assertEqual(response.status_code, 403)

    @tag('auth')
    def test_list(self):
        # check that user 1 sees her lone app and user 2's app
        response = self.client.get('/v2/apps')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(len(response.data['results']), 2)
        app_id = response.data['results'][0]['id']

        # create a new object permission
        url = "/v2/apps/{}/perms".format(app_id)
        body = {'username': 'autotest-2'}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 201, response.data)

        # list perms on the app
        response = self.client.get("/v2/apps/{}/perms".format(app_id))
        self.assertEqual(response.data, {'users': ['autotest-2']})

    @tag('auth')
    def test_admin_can_list(self):
        """Check that an administrator can list an app's perms"""
        response = self.client.get('/v2/apps')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(len(response.data['results']), 2)

    @tag('auth')
    def test_list_errors(self):
        response = self.client.get('/v2/apps')
        app_id = response.data['results'][0]['id']

        # login as user 2, list perms on the app
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token2)
        response = self.client.get("/v2/apps/{}/perms".format(app_id))
        self.assertEqual(response.status_code, 403)

    @tag('auth')
    def test_unauthorized_user_cannot_modify_perms(self):
        """
        An unauthorized user should not be able to modify other apps' permissions.

        Since an unauthorized user should not know about the application at all, these
        requests should return a 404.
        """
        app_id = 'autotest'
        url = '/v2/apps'
        body = {'id': app_id}
        response = self.client.post(url, body)

        url = '{}/{}/perms'.format(url, app_id)
        body = {'username': self.user2.username}
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token2)
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 403)

    @tag('auth')
    def test_collaborator_cannot_share(self):
        """
        An collaborator should not be able to modify the app's permissions.
        """
        app_id = "autotest-1-app"
        owner_token = self.token
        collab = self.user2
        collab_token = self.token2
        url = '/v2/apps/{}/perms'.format(app_id)

        # Share app with collaborator
        body = {'username': collab.username}
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + owner_token)
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 201, response.data)

        # Collaborator should fail to share app
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + collab_token)
        body = {'username': self.user3.username}
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 403)

        # Collaborator can list
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.data)

        # Share app with user 3 for rest of tests
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + owner_token)
        response = self.client.post(url, body)
        self.assertEqual(response.status_code, 201, response.data)

        self.client.credentials(HTTP_AUTHORIZATION='Token ' + collab_token)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.data)

        # Collaborator cannot delete other collaborator
        url += "/{}".format(self.user3.username)
        response = self.client.delete(url)
        self.assertEqual(response.status_code, 403)

        # Collaborator can delete themselves
        url = '/v2/apps/{}/perms/{}'.format(app_id, collab.username)
        response = self.client.delete(url)
        self.assertEqual(response.status_code, 204, response.data)
