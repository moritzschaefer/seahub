import logging

from django.template.defaultfilters import filesizeformat

from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.throttling import UserRateThrottle
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import status

from pysearpc import SearpcError

import seaserv
from seaserv import seafile_api

from seahub.api2.utils import api_error
from seahub.api2.authentication import TokenAuthentication
from seahub.base.templatetags.seahub_tags import email2nickname, \
    translate_seahub_time, tsstr_sec
from seahub.avatar.templatetags.group_avatar_tags import grp_avatar
from seahub.utils import is_org_context
from seahub.group.utils import validate_group_name


logger = logging.getLogger(__name__)
json_content_type = 'application/json; charset=utf-8'


class Groups(APIView):

    authentication_classes = (TokenAuthentication, SessionAuthentication)
    permission_classes = (IsAuthenticated,)
    throttle_classes = (UserRateThrottle, )

    def _get_group_admins(self, group_id):
        members = seaserv.get_group_members(group_id)
        admin_members = filter(lambda m: m.is_staff, members)

        admins = []
        for u in admin_members:
            admins.append(u.user_name)
        return admins

    def _can_add_group(self, request):

        return request.user.permissions.can_add_group()

    def _get_group_num_limit(self, request):

        return getattr(request.user, 'num_of_groups', -1)

    def get(self, request):
        """ List all groups.
        """

        org_id = None
        username = request.user.username
        if is_org_context(request):
            org_id = request.user.org.org_id
            user_groups = seaserv.get_org_groups_by_user(org_id, username)
        else:
            user_groups = seaserv.get_personal_groups_by_user(username)

        try:
            size = int(request.GET.get('size', 36))
        except ValueError:
            size = 36

        with_repos = request.GET.get('with_repos')
        with_repos = True if with_repos == '1' else False

        groups = []
        for g in user_groups:
            group = {
                "id": g.id,
                "name": g.group_name,
                "creator": g.creator_name,
                "created_at": tsstr_sec(g.timestamp),
                "avatar": grp_avatar(g.id, size),
                "admins": self._get_group_admins(g.id),
            }

            if with_repos:
                if org_id:
                    group_repos = seafile_api.get_org_group_repos(org_id, g.id)
                else:
                    group_repos = seafile_api.get_repos_by_group(g.id)

                repos = []
                for r in group_repos:
                    repo = {
                        "id": r.id,
                        "name": r.name,
                        "desc": r.desc,
                        "size": r.size,
                        "size_formatted": filesizeformat(r.size),
                        "mtime": r.last_modified,
                        "mtime_relative": translate_seahub_time(r.last_modified),
                        "encrypted": r.encrypted,
                        "permission": r.permission,
                        "owner": r.user,
                        "owner_nickname": email2nickname(r.user),
                        "share_from_me": True if username == r.user else False,
                    }
                    repos.append(repo)

                group['repos'] = repos

            groups.append(group)

        return Response(groups)

    def post(self, request):
        """ Create a group
        """
        if not self._can_add_group(request):
            error_msg = 'You do not have permission to create group.'
            return api_error(status.HTTP_403_FORBIDDEN, error_msg)

        # check plan
        username = request.user.username
        num_of_groups = self._get_group_num_limit(request)
        if num_of_groups > 0:
            current_groups = len(seaserv.get_personal_groups_by_user(username))
            if current_groups >= num_of_groups:
                error_msg = 'You can only create %d groups.' % num_of_groups
                return api_error(status.HTTP_403_FORBIDDEN, error_msg)

        group_name = request.DATA.get('group_name', '')
        group_name = group_name.strip()
        if not validate_group_name(group_name):
            error_msg = 'Invalid group name. Group name can only contain letters, numbers, blank, hyphen or underscore.'
            return api_error(status.HTTP_400_BAD_REQUEST, error_msg)

        # Check whether group name is duplicated.
        if request.cloud_mode:
            checked_groups = seaserv.get_personal_groups_by_user(username)
        else:
            checked_groups = seaserv.get_personal_groups(-1, -1)
        for g in checked_groups:
            if g.group_name == group_name:
                error_msg = 'There is already a group with that name.'
                return api_error(status.HTTP_400_BAD_REQUEST, error_msg)

        # Group name is valid, create that group.
        try:
            group_id = seaserv.ccnet_threaded_rpc.create_group(group_name.encode('utf-8'),
                                                       username)

            g = seaserv.get_group(group_id)
            new_group = {
                "id": g.id,
                "name": g.group_name,
                "creator": g.creator_name,
                "created_at": tsstr_sec(g.timestamp),
                "avatar": grp_avatar(g.id),
                "admins": self._get_group_admins(g.id),
            }
            return Response(new_group)
        except SearpcError as e:
            logger.error(e)
            error_msg = 'Failed to create group.'
            return api_error(status.HTTP_500_INTERNAL_SERVER_ERROR, error_msg)
