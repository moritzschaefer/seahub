# -*- coding: utf-8 -*-
import os
import posixpath
import logging

from django.core.urlresolvers import reverse
from django.contrib.sites.models import RequestSite
from django.db.models import F
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import render_to_response
from django.template import RequestContext
from django.template.loader import render_to_string
from django.utils.translation import ugettext as _
from django.utils.http import urlquote

import seaserv
from seaserv import seafile_api

from seahub.auth.decorators import login_required
from seahub.avatar.templatetags.avatar_tags import avatar
from seahub.avatar.templatetags.group_avatar_tags import grp_avatar
from seahub.contacts.models import Contact
from seahub.forms import RepoPassowrdForm
from seahub.options.models import UserOptions, CryptoOptionNotSetError
from seahub.share.models import FileShare, UploadLinkShare, \
    check_share_link_access, set_share_link_access
from seahub.share.forms import SharedLinkPasswordForm
from seahub.views import gen_path_link, get_repo_dirents, \
    check_repo_access_permission, get_repo_dirents_with_perm, \
    get_system_default_repo_id

from seahub.utils import gen_file_upload_url, is_org_context, \
    get_fileserver_root, gen_dir_share_link, gen_shared_upload_link, \
    get_max_upload_file_size, new_merge_with_no_conflict, \
    get_commit_before_new_merge, user_traffic_over_limit, render_error, \
    get_file_type_and_ext
from seahub.settings import ENABLE_SUB_LIBRARY, FORCE_SERVER_CRYPTO, \
    ENABLE_UPLOAD_FOLDER, ENABLE_RESUMABLE_FILEUPLOAD, ENABLE_THUMBNAIL, \
    THUMBNAIL_ROOT, THUMBNAIL_DEFAULT_SIZE, THUMBNAIL_SIZE_FOR_GRID
from seahub.utils import gen_file_get_url
from seahub.utils.file_types import IMAGE
from seahub.thumbnail.utils import get_thumbnail_src, \
    allow_generate_thumbnail, get_share_link_thumbnail_src

# Get an instance of a logger
logger = logging.getLogger(__name__)

def get_repo(repo_id):
    return seafile_api.get_repo(repo_id)

def get_commit(repo_id, repo_version, commit_id):
    return seaserv.get_commit(repo_id, repo_version, commit_id)

def get_repo_size(repo_id):
    return seafile_api.get_repo_size(repo_id)

def is_password_set(repo_id, username):
    return seafile_api.is_password_set(repo_id, username)

# def check_dir_access_permission(username, repo_id, path):
#     """Check user has permission to view the directory.
#     1. check whether this directory is private shared.
#     2. if failed, check whether the parent of this directory is private shared.
#     """

#     pfs = PrivateFileDirShare.objects.get_private_share_in_dir(username,
#                                                                repo_id, path)
#     if pfs is None:
#         dirs = PrivateFileDirShare.objects.list_private_share_in_dirs_by_user_and_repo(username, repo_id)
#         for e in dirs:
#             if path.startswith(e.path):
#                 return e.permission
#         return None
#     else:
#         return pfs.permission

def get_path_from_request(request):
    path = request.GET.get('p', '/')
    if path[-1] != '/':
        path = path + '/'
    return path

def get_next_url_from_request(request):
    return request.GET.get('next', None)

def get_nav_path(path, repo_name):
    return gen_path_link(path, repo_name)

def get_shared_groups_by_repo_and_user(repo_id, username):
    """Get all groups which this repo is shared.
    """
    repo_shared_groups = seaserv.get_shared_groups_by_repo(repo_id)

    # Filter out groups that user is joined.
    groups = [x for x in repo_shared_groups if seaserv.is_group_user(x.id, username)]
    return groups

def is_no_quota(repo_id):
    return True if seaserv.check_quota(repo_id) < 0 else False

def get_upload_url(request, repo_id):
    username = request.user.username
    if check_repo_access_permission(repo_id, request.user) == 'rw':
        token = seafile_api.get_fileserver_access_token(repo_id, 'dummy',
                                                        'upload', username)
        return gen_file_upload_url(token, 'upload')
    else:
        return ''

# def get_api_upload_url(request, repo_id):
#     """Get file upload url for web api.
#     """
#     username = request.user.username
#     if check_repo_access_permission(repo_id, request.user) == 'rw':
#         token = seafile_api.get_fileserver_access_token(repo_id, 'dummy',
#                                                         'upload', username)
#         return gen_file_upload_url(token, 'upload-api')
#     else:
#         return ''

# def get_api_update_url(request, repo_id):
#     username = request.user.username
#     if check_repo_access_permission(repo_id, request.user) == 'rw':
#         token = seafile_api.get_fileserver_access_token(repo_id, 'dummy',
#                                                         'update', username)
#         return gen_file_upload_url(token, 'update-api')
#     else:
#         return ''

def get_fileshare(repo_id, username, path):
    if path == '/':    # no shared link for root dir
        return None

    l = FileShare.objects.filter(repo_id=repo_id).filter(
        username=username).filter(path=path)
    return l[0] if len(l) > 0 else None

def get_dir_share_link(fileshare):
    # dir shared link
    if fileshare:
        dir_shared_link = gen_dir_share_link(fileshare.token)
    else:
        dir_shared_link = ''
    return dir_shared_link

def get_uploadlink(repo_id, username, path):
    if path == '/':    # no shared upload link for root dir
        return None

    l = UploadLinkShare.objects.filter(repo_id=repo_id).filter(
        username=username).filter(path=path)
    return l[0] if len(l) > 0 else None

def get_dir_shared_upload_link(uploadlink):
    # dir shared upload link
    if uploadlink:
        dir_shared_upload_link = gen_shared_upload_link(uploadlink.token)
    else:
        dir_shared_upload_link = ''
    return dir_shared_upload_link

def render_repo(request, repo):
    """Steps to show repo page:
    If user has permission to view repo
      If repo is encrypt and password is not set on server
        return decrypt repo page
      If repo is not encrypt or password is set on server
        Show repo direntries based on requested path
    If user does not have permission to view repo
      return permission deny page
    """
    username = request.user.username
    path = get_path_from_request(request)
    user_perm = check_repo_access_permission(repo.id, request.user)
    if user_perm is None:
        return render_error(request, _(u'Permission denied'))

    sub_lib_enabled = UserOptions.objects.is_sub_lib_enabled(username)

    server_crypto = False
    if repo.encrypted:
        try:
            server_crypto = UserOptions.objects.is_server_crypto(username)
        except CryptoOptionNotSetError:
            return render_to_response('options/set_user_options.html', {
                    }, context_instance=RequestContext(request))

        if (repo.enc_version == 1 or (repo.enc_version == 2 and server_crypto)) \
                and not is_password_set(repo.id, username):
            return render_to_response('decrypt_repo_form.html', {
                    'repo': repo,
                    'next': get_next_url_from_request(request) or reverse('repo', args=[repo.id]),
                    'force_server_crypto': FORCE_SERVER_CRYPTO,
                    }, context_instance=RequestContext(request))

    # query context args
    fileserver_root = get_fileserver_root()
    max_upload_file_size = get_max_upload_file_size()

    protocol = request.is_secure() and 'https' or 'http'
    domain = RequestSite(request).domain

    for g in request.user.joined_groups:
        g.avatar = grp_avatar(g.id, 20)

    head_commit = get_commit(repo.id, repo.version, repo.head_cmmt_id)
    if not head_commit:
        raise Http404

    if new_merge_with_no_conflict(head_commit):
        info_commit = get_commit_before_new_merge(head_commit)
    else:
        info_commit = head_commit

    repo_size = get_repo_size(repo.id)
    no_quota = is_no_quota(repo.id)
    if is_org_context(request):
        repo_owner = seafile_api.get_org_repo_owner(repo.id)
    else:
        repo_owner = seafile_api.get_repo_owner(repo.id)
    is_repo_owner = True if repo_owner == username else False
    if is_repo_owner and not repo.is_virtual:
        show_repo_settings = True
    else:
        show_repo_settings = False

    file_list, dir_list, dirent_more = get_repo_dirents_with_perm(
        request, repo, head_commit, path, offset=0, limit=100)
    more_start = None
    if dirent_more:
        more_start = 100
    zipped = get_nav_path(path, repo.name)
    repo_groups = get_shared_groups_by_repo_and_user(repo.id, username)
    if len(repo_groups) > 1:
        repo_group_str = render_to_string("snippets/repo_group_list.html",
                                          {'groups': repo_groups})
    else:
        repo_group_str = ''

    fileshare = get_fileshare(repo.id, username, path)
    dir_shared_link = get_dir_share_link(fileshare)
    uploadlink = get_uploadlink(repo.id, username, path)
    dir_shared_upload_link = get_dir_shared_upload_link(uploadlink)

    for f in file_list:
        file_path = posixpath.join(path, f.obj_name)
        if allow_generate_thumbnail(request, repo.id, file_path):
            f.allow_generate_thumbnail = True
            if os.path.exists(os.path.join(THUMBNAIL_ROOT, str(THUMBNAIL_DEFAULT_SIZE), f.obj_id)):
               src = get_thumbnail_src(repo.id, THUMBNAIL_DEFAULT_SIZE, file_path)
               f.encoded_thumbnail_src = urlquote(src)

    return render_to_response('repo.html', {
            'repo': repo,
            'user_perm': user_perm,
            'repo_owner': repo_owner,
            'is_repo_owner': is_repo_owner,
            'show_repo_settings': show_repo_settings,
            'current_commit': head_commit,
            'info_commit': info_commit,
            'password_set': True,
            'repo_size': repo_size,
            'dir_list': dir_list,
            'file_list': file_list,
            'dirent_more': dirent_more,
            'more_start': more_start,
            'path': path,
            'zipped': zipped,
            'groups': repo_groups,
            'repo_group_str': repo_group_str,
            'no_quota': no_quota,
            'max_upload_file_size': max_upload_file_size,
            'fileserver_root': fileserver_root,
            'protocol': protocol,
            'domain': domain,
            'fileshare': fileshare,
            'dir_shared_link': dir_shared_link,
            'uploadlink': uploadlink,
            'dir_shared_upload_link': dir_shared_upload_link,
            'ENABLE_SUB_LIBRARY': ENABLE_SUB_LIBRARY,
            'server_crypto': server_crypto,
            'sub_lib_enabled': sub_lib_enabled,
            'enable_upload_folder': ENABLE_UPLOAD_FOLDER,
            'ENABLE_THUMBNAIL': ENABLE_THUMBNAIL,
            }, context_instance=RequestContext(request))

@login_required
def repo(request, repo_id):
    """Show repo page and handle POST request to decrypt repo.
    """
    repo = get_repo(repo_id)

    if not repo:
        raise Http404

    if request.method == 'GET':
        return render_repo(request, repo)
    elif request.method == 'POST':
        form = RepoPassowrdForm(request.POST)
        next = get_next_url_from_request(request) or reverse('repo',
                                                             args=[repo_id])
        if form.is_valid():
            return HttpResponseRedirect(next)
        else:
            return render_to_response('decrypt_repo_form.html', {
                    'repo': repo,
                    'form': form,
                    'next': next,
                    'force_server_crypto': FORCE_SERVER_CRYPTO,
                    }, context_instance=RequestContext(request))

@login_required
def repo_history_view(request, repo_id):
    """View repo in history.
    """
    repo = get_repo(repo_id)
    if not repo:
        raise Http404

    username = request.user.username
    path = get_path_from_request(request)
    user_perm = check_repo_access_permission(repo.id, request.user)
    if user_perm is None:
        return render_error(request, _(u'Permission denied'))

    try:
        server_crypto = UserOptions.objects.is_server_crypto(username)
    except CryptoOptionNotSetError:
        # Assume server_crypto is ``False`` if this option is not set.
        server_crypto = False

    if repo.encrypted and \
        (repo.enc_version == 1 or (repo.enc_version == 2 and server_crypto)) \
        and not is_password_set(repo.id, username):
        return render_to_response('decrypt_repo_form.html', {
                'repo': repo,
                'next': get_next_url_from_request(request) or reverse('repo', args=[repo.id]),
                'force_server_crypto': FORCE_SERVER_CRYPTO,
                }, context_instance=RequestContext(request))

    commit_id = request.GET.get('commit_id', None)
    if commit_id is None:
        return HttpResponseRedirect(reverse('repo', args=[repo.id]))
    current_commit = get_commit(repo.id, repo.version, commit_id)
    if not current_commit:
        current_commit = get_commit(repo.id, repo.version, repo.head_cmmt_id)

    file_list, dir_list, dirent_more = get_repo_dirents(request, repo,
                                                        current_commit, path)
    zipped = get_nav_path(path, repo.name)

    repo_owner = seafile_api.get_repo_owner(repo.id)
    is_repo_owner = True if username == repo_owner else False

    return render_to_response('repo_history_view.html', {
            'repo': repo,
            "is_repo_owner": is_repo_owner,
            'user_perm': user_perm,
            'current_commit': current_commit,
            'dir_list': dir_list,
            'file_list': file_list,
            'path': path,
            'zipped': zipped,
            }, context_instance=RequestContext(request))

########## shared dir/uploadlink
def _download_dir_from_share_link(request, fileshare, repo, real_path):
    # check whether owner's traffic over the limit
    if user_traffic_over_limit(fileshare.username):
        return render_error(
            request, _(u'Unable to access file: share link traffic is used up.'))

    shared_by = fileshare.username
    if real_path == '/':
        dirname = repo.name
    else:
        dirname = os.path.basename(real_path.rstrip('/'))

    dir_id = seafile_api.get_dir_id_by_path(repo.id, real_path)
    if not dir_id:
        return render_error(
            request, _(u'Unable to download: folder not found.'))

    try:
        total_size = seaserv.seafserv_threaded_rpc.get_dir_size(
            repo.store_id, repo.version, dir_id)
    except Exception as e:
        logger.error(str(e))
        return render_error(request, _(u'Internal Error'))

    if total_size > seaserv.MAX_DOWNLOAD_DIR_SIZE:
        return render_error(request, _(u'Unable to download directory "%s": size is too large.') % dirname)

    token = seafile_api.get_fileserver_access_token(repo.id,
                                                    dir_id,
                                                    'download-dir',
                                                    request.user.username)

    try:
        seaserv.send_message('seahub.stats', 'dir-download\t%s\t%s\t%s\t%s' %
                             (repo.id, shared_by, dir_id, total_size))
    except Exception as e:
        logger.error('Error when sending dir-download message: %s' % str(e))

    return HttpResponseRedirect(gen_file_get_url(token, dirname))

def view_shared_dir(request, token):
    assert token is not None    # Checked by URLconf

    fileshare = FileShare.objects.get_valid_dir_link_by_token(token)
    if fileshare is None:
        raise Http404

    if fileshare.is_encrypted():
        if not check_share_link_access(request, token):
            d = {'token': token, 'view_name': 'view_shared_dir', }
            if request.method == 'POST':
                post_values = request.POST.copy()
                post_values['enc_password'] = fileshare.password
                form = SharedLinkPasswordForm(post_values)
                d['form'] = form
                if form.is_valid():
                    set_share_link_access(request, token)
                else:
                    return render_to_response('share_access_validation.html', d,
                                              context_instance=RequestContext(request))
            else:
                return render_to_response('share_access_validation.html', d,
                                          context_instance=RequestContext(request))

    username = fileshare.username
    repo_id = fileshare.repo_id

    # Get path from frontend, use '/' if missing, and construct request path
    # with fileshare.path to real path, used to fetch dirents by RPC.
    req_path = request.GET.get('p', '/')
    if req_path[-1] != '/':
        req_path += '/'

    if req_path == '/':
        real_path = fileshare.path
    else:
        real_path = posixpath.join(fileshare.path, req_path.lstrip('/'))
    if real_path[-1] != '/':         # Normalize dir path
        real_path += '/'

    repo = get_repo(repo_id)
    if not repo:
        raise Http404

    # Check path still exist, otherwise show error
    if not seafile_api.get_dir_id_by_path(repo.id, fileshare.path):
        return render_error(request, _('"%s" does not exist.') % fileshare.path)

    # download shared dir
    if request.GET.get('dl', '') == '1':
        return _download_dir_from_share_link(request, fileshare, repo,
                                             real_path)

    if fileshare.path == '/':
        # use repo name as dir name if share whole library
        dir_name = repo.name
    else:
        dir_name = os.path.basename(real_path[:-1])

    current_commit = seaserv.get_commits(repo_id, 0, 1)[0]
    file_list, dir_list, dirent_more = get_repo_dirents(request, repo,
                                                        current_commit, real_path)

    # generate dir navigator
    if fileshare.path == '/':
        zipped = gen_path_link(req_path, repo.name)
    else:
        zipped = gen_path_link(req_path, os.path.basename(fileshare.path[:-1]))

    if req_path == '/':  # When user view the root of shared dir..
        # increase shared link view_cnt,
        fileshare = FileShare.objects.get(token=token)
        fileshare.view_cnt = F('view_cnt') + 1
        fileshare.save()

    traffic_over_limit = user_traffic_over_limit(fileshare.username)

    # mode to view dir/file items 
    mode = request.GET.get('mode', 'list')
    if mode != 'list':
        mode = 'grid'

    thumbnail_size = THUMBNAIL_DEFAULT_SIZE if mode == 'list' else THUMBNAIL_SIZE_FOR_GRID

    for f in file_list:

        file_type, file_ext = get_file_type_and_ext(f.obj_name)
        if file_type == IMAGE:
            f.is_img = True

        real_image_path = posixpath.join(real_path, f.obj_name)
        if allow_generate_thumbnail(request, repo_id, real_image_path):
            f.allow_generate_thumbnail = True
            if os.path.exists(os.path.join(THUMBNAIL_ROOT, str(thumbnail_size), f.obj_id)):
                req_image_path = posixpath.join(req_path, f.obj_name)
                src = get_share_link_thumbnail_src(token, thumbnail_size, req_image_path)
                f.encoded_thumbnail_src = urlquote(src)

    return render_to_response('view_shared_dir.html', {
            'repo': repo,
            'token': token,
            'path': req_path,
            'username': username,
            'dir_name': dir_name,
            'file_list': file_list,
            'dir_list': dir_list,
            'zipped': zipped,
            'traffic_over_limit': traffic_over_limit,
            'ENABLE_THUMBNAIL': ENABLE_THUMBNAIL,
            'mode': mode,
            'thumbnail_size': thumbnail_size,
            }, context_instance=RequestContext(request))

def view_shared_upload_link(request, token):
    assert token is not None    # Checked by URLconf

    uploadlink = UploadLinkShare.objects.get_valid_upload_link_by_token(token)
    if uploadlink is None:
        raise Http404

    if uploadlink.is_encrypted() and not check_share_link_access(
            request, token, is_upload_link=True):
        d = {'token': token, 'view_name': 'view_shared_upload_link', }
        if request.method == 'POST':
            post_values = request.POST.copy()
            post_values['enc_password'] = uploadlink.password
            form = SharedLinkPasswordForm(post_values)
            d['form'] = form
            if form.is_valid():
                set_share_link_access(request, token, is_upload_link=True)
            else:
                return render_to_response('share_access_validation.html', d,
                                          context_instance=RequestContext(request))
        else:
            return render_to_response('share_access_validation.html', d,
                                      context_instance=RequestContext(request))

    username = uploadlink.username
    repo_id = uploadlink.repo_id
    repo = get_repo(repo_id)
    if not repo:
        raise Http404

    path = uploadlink.path
    if path == '/':
        # use repo name as dir name if share whole library
        dir_name = repo.name
    else:
        dir_name = os.path.basename(path[:-1])

    repo = get_repo(repo_id)
    if not repo:
        raise Http404

    uploadlink.view_cnt = F('view_cnt') + 1
    uploadlink.save()

    no_quota = True if seaserv.check_quota(repo_id) < 0 else False

    return render_to_response('view_shared_upload_link.html', {
            'repo': repo,
            'path': path,
            'username': username,
            'dir_name': dir_name,
            'max_upload_file_size': seaserv.MAX_UPLOAD_FILE_SIZE,
            'no_quota': no_quota,
            'uploadlink': uploadlink,
            'enable_upload_folder': ENABLE_UPLOAD_FOLDER,
            'enable_resumable_fileupload': ENABLE_RESUMABLE_FILEUPLOAD,
            }, context_instance=RequestContext(request))
