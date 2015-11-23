from django.core.urlresolvers import reverse
from django.http.cookie import parse_cookie

from seahub.base.accounts import User
from seahub.options.models import (UserOptions, KEY_FORCE_PASSWD_CHANGE,
                                   VAL_FORCE_PASSWD_CHANGE)
from seahub.test_utils import BaseTestCase

from seaserv import ccnet_threaded_rpc

class UserToggleStatusTest(BaseTestCase):
    def setUp(self):
        self.login_as(self.admin)

    def test_can_activate(self):
        old_passwd = self.user.enc_password
        resp = self.client.post(
            reverse('user_toggle_status', args=[self.user.username]),
            {'s': 1},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(200, resp.status_code)
        self.assertContains(resp, '"success": true')

        u = User.objects.get(email=self.user.username)
        assert u.is_active is True
        assert u.enc_password == old_passwd

    def test_can_deactivate(self):
        old_passwd = self.user.enc_password
        resp = self.client.post(
            reverse('user_toggle_status', args=[self.user.username]),
            {'s': 0},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(200, resp.status_code)
        self.assertContains(resp, '"success": true')

        u = User.objects.get(email=self.user.username)
        assert u.is_active is False
        assert u.enc_password == old_passwd


class UserResetTest(BaseTestCase):
    def setUp(self):
        self.login_as(self.admin)

    def test_can_reset(self):
        assert len(UserOptions.objects.filter(
            email=self.user.username, option_key=KEY_FORCE_PASSWD_CHANGE)) == 0

        old_passwd = self.user.enc_password
        resp = self.client.post(
            reverse('user_reset', args=[self.user.email])
        )
        self.assertEqual(302, resp.status_code)

        u = User.objects.get(email=self.user.username)
        assert u.enc_password != old_passwd
        assert UserOptions.objects.get(
            email=self.user.username,
            option_key=KEY_FORCE_PASSWD_CHANGE).option_val == VAL_FORCE_PASSWD_CHANGE

class BatchUserMakeAdminTest(BaseTestCase):
    def setUp(self):
        self.login_as(self.admin)

    def test_can_make_admins(self):
        resp = self.client.post(
            reverse('batch_user_make_admin'), {
                'set_admin_emails': self.user.username
            }, HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )

        old_passwd = self.user.enc_password
        self.assertContains(resp, '"success": true')

        u = User.objects.get(email=self.user.username)
        assert u.is_staff is True
        assert u.enc_password == old_passwd


# class UserMakeAdminTest(TestCase, Fixtures):
#     def test_can_make_admin(self):
#         self.client.post(
#             reverse('auth_login'), {'username': self.admin.username,
#                                     'password': 'secret'}
#         )

#         resp = self.client.get(
#             reverse('user_make_admin', args=[self.user.id])
#         )

#         old_passwd = self.user.enc_password
#         self.assertEqual(302, resp.status_code)

#         u = User.objects.get(email=self.user.username)
#         assert u.is_staff is True
#         assert u.enc_password == old_passwd


class UserAddTest(BaseTestCase):
    def setUp(self):
        self.new_user = 'new_user@test.com'
        self.login_as(self.admin)
        self.remove_user(self.new_user)

    def test_can_add(self):
        assert len(UserOptions.objects.filter(
            email=self.new_user, option_key=KEY_FORCE_PASSWD_CHANGE)) == 0

        resp = self.client.post(
            reverse('user_add',), {
                'email': self.new_user,
                'password1': '123',
                'password2': '123',
            }, HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )

        self.assertEqual(200, resp.status_code)
        assert UserOptions.objects.get(
            email=self.new_user,
            option_key=KEY_FORCE_PASSWD_CHANGE).option_val == VAL_FORCE_PASSWD_CHANGE

class UserRemoveTest(BaseTestCase):
    def setUp(self):
        self.login_as(self.admin)

    def test_can_remove(self):
        # create one user
        username = self.user.username

        resp = self.client.post(
            reverse('user_remove', args=[username])
        )

        self.assertEqual(302, resp.status_code)
        assert 'Successfully deleted %s' % username in parse_cookie(resp.cookies)['messages']
        assert len(ccnet_threaded_rpc.search_emailusers('DB', username, -1, -1))  == 0


class SudoModeTest(BaseTestCase):
    def test_normal_user_raise_404(self):
        self.login_as(self.user)

        resp = self.client.get(reverse('sys_sudo_mode'))
        self.assertEqual(404, resp.status_code)

    def test_admin_get(self):
        self.login_as(self.admin)

        resp = self.client.get(reverse('sys_sudo_mode'))
        self.assertEqual(200, resp.status_code)
        self.assertTemplateUsed('sysadmin/sudo_mode.html')

    def test_admin_post(self):
        self.login_as(self.admin)

        resp = self.client.post(reverse('sys_sudo_mode'), {
            'username': self.admin.username,
            'password': self.admin_password,
        })
        self.assertEqual(302, resp.status_code)
        self.assertRedirects(resp, reverse('sys_useradmin'))
