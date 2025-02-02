import requests
from mock import Mock
from mock import patch

from django.core.urlresolvers import reverse

from seahub.test_utils import BaseTestCase

class ViewLibFileTest(BaseTestCase):
    def setUp(self):
        # self.login_as(self.user)
        pass

    def tearDown(self):
        self.remove_repo(self.repo.id)

    def test_repo_not_exist(self):
        self.login_as(self.user)

        url = reverse('view_lib_file', args=[
            '4a3d8cbe-6c79-4dad-8234-76b000000000', '/'])

        resp = self.client.get(url)
        self.assertEqual(404, resp.status_code)

    def test_file_not_exist(self):
        self.login_as(self.user)

        url = reverse('view_lib_file', args=[
            self.repo.id, '/some_random_file'])

        resp = self.client.get(url)
        self.assertEqual(200, resp.status_code)
        self.assertTemplateUsed(resp, 'error.html')

    def test_file_permission_error(self):
        self.login_as(self.admin)

        url = reverse('view_lib_file', args=[
            self.repo.id, self.file])

        resp = self.client.get(url)
        self.assertEqual(200, resp.status_code)
        self.assertTemplateUsed(resp, 'permission_error.html')

    def test_invalid_file_extension(self):
        self.login_as(self.user)

        file_path = self.create_file(repo_id=self.repo.id, parent_dir='/',
                                     filename="foo.___", username=self.user.email)

        url = reverse('view_lib_file', args=[
            self.repo.id, file_path])

        resp = self.client.get(url)
        self.assertEqual(200, resp.status_code)
        self.assertTemplateUsed(resp, 'view_file_base.html')
        assert resp.context['err'] == 'invalid extension'

    @patch('seahub.views.file.FILE_PREVIEW_MAX_SIZE', -1)
    def test_file_size_exceeds_limit(self):
        self.login_as(self.user)

        url = reverse('view_lib_file', args=[
            self.repo.id, self.file])

        resp = self.client.get(url)
        self.assertEqual(200, resp.status_code)
        self.assertTemplateUsed(resp, 'view_file_base.html')
        assert resp.context['err'] == 'File size surpasses -1 bytes, can not be opened online.'

    def test_text_file(self):
        self.login_as(self.user)

        url = reverse('view_lib_file', args=[self.repo.id, self.file])

        resp = self.client.get(url)
        self.assertEqual(200, resp.status_code)
        self.assertTemplateUsed(resp, 'view_file_text.html')
        assert resp.context['filetype'].lower() == 'text'
        assert resp.context['err'] == ''
        assert resp.context['file_content'] == ''
        assert resp.context['encoding'] == 'utf-8'

        # token for text file is one time only
        raw_path = resp.context['raw_path']
        r = requests.get(raw_path)
        self.assertEqual(400, r.status_code)

    def test_ms_doc_without_office_converter(self):
        self.login_as(self.user)

        file_path = self.create_file(repo_id=self.repo.id, parent_dir='/',
                                     filename="foo.doc", username=self.user.email)
        url = reverse('view_lib_file', args=[self.repo.id, file_path])

        resp = self.client.get(url)
        self.assertEqual(200, resp.status_code)
        self.assertTemplateUsed(resp, 'view_file_unknown.html')
        assert resp.context['filetype'].lower() == 'unknown'
        assert resp.context['err'] == ''

        # token for doc file is one time only
        raw_path = resp.context['raw_path']
        r = requests.get(raw_path)
        self.assertEqual(200, r.status_code)
        r = requests.get(raw_path)
        self.assertEqual(400, r.status_code)

    # @patch('seahub.views.file.HAS_OFFICE_CONVERTER', True)
    # @patch('seahub.views.file.can_preview_file')
    # @patch('seahub.views.file.prepare_converted_html', create=True)
    # def test_ms_doc_with_office_converter(self, mock_prepare_converted_html,
    #                                       mock_can_preview_file):
    #     mock_prepare_converted_html.return_value = None
    #     mock_can_preview_file.return_value = (True, None)

    #     self.login_as(self.user)

    #     file_path = self.create_file(repo_id=self.repo.id, parent_dir='/',
    #                                  filename="foo.doc", username=self.user.email)
    #     url = reverse('view_lib_file', args=[self.repo.id, file_path])

    #     resp = self.client.get(url)
    #     self.assertEqual(200, resp.status_code)
    #     self.assertTemplateUsed(resp, 'view_file_document.html')
    #     assert resp.context['filetype'].lower() == 'document'
    #     assert resp.context['err'] == ''

    #     # token for doc file is one time only
    #     raw_path = resp.context['raw_path']
    #     r = requests.get(raw_path)
    #     self.assertEqual(200, r.status_code)
    #     r = requests.get(raw_path)
    #     self.assertEqual(400, r.status_code)

    @patch('seahub.views.file.get_file_size')
    def test_opendoc(self, mock_get_file_size):
        mock_get_file_size.return_value = 1

        self.login_as(self.user)

        file_path = self.create_file(repo_id=self.repo.id, parent_dir='/',
                                     filename="foo.odt", username=self.user.email)
        url = reverse('view_lib_file', args=[self.repo.id, file_path])

        resp = self.client.get(url)
        self.assertEqual(200, resp.status_code)
        self.assertTemplateUsed(resp, 'view_file_opendocument.html')
        assert resp.context['filetype'].lower() == 'opendocument'
        assert resp.context['err'] == ''

        # token for doc file is one time only
        raw_path = resp.context['raw_path']
        r = requests.get(raw_path)
        self.assertEqual(200, r.status_code)
        r = requests.get(raw_path)
        self.assertEqual(400, r.status_code)

    def test_pdf_file(self):
        self.login_as(self.user)

        file_path = self.create_file(repo_id=self.repo.id, parent_dir='/',
                                     filename="foo.pdf", username=self.user.email)
        url = reverse('view_lib_file', args=[self.repo.id, file_path])

        resp = self.client.get(url)
        self.assertEqual(200, resp.status_code)
        self.assertTemplateUsed(resp, 'view_file_pdf.html')
        assert resp.context['filetype'].lower() == 'pdf'
        assert resp.context['err'] == ''

        # token for doc file is one time only
        raw_path = resp.context['raw_path']
        r = requests.get(raw_path)
        self.assertEqual(200, r.status_code)
        r = requests.get(raw_path)
        self.assertEqual(400, r.status_code)

    def test_img_file(self):
        self.login_as(self.user)

        file_path = self.create_file(repo_id=self.repo.id, parent_dir='/',
                                     filename="foo.jpg", username=self.user.email)
        self.create_file(repo_id=self.repo.id, parent_dir='/',
                         filename="foo2.jpg", username=self.user.email)

        url = reverse('view_lib_file', args=[self.repo.id, file_path])

        resp = self.client.get(url)
        self.assertEqual(200, resp.status_code)
        self.assertTemplateUsed(resp, 'view_file_image.html')
        assert resp.context['filetype'].lower() == 'image'
        assert resp.context['err'] == ''
        assert resp.context['img_next'] == '/foo2.jpg'
        assert resp.context['img_prev'] is None

        # token for doc file is one time only
        raw_path = resp.context['raw_path']
        r = requests.get(raw_path)
        self.assertEqual(200, r.status_code)
        r = requests.get(raw_path)
        self.assertEqual(400, r.status_code)

    def test_video_file(self):
        self.login_as(self.user)

        file_path = self.create_file(repo_id=self.repo.id, parent_dir='/',
                                     filename="foo.mp4", username=self.user.email)
        url = reverse('view_lib_file', args=[self.repo.id, file_path])

        resp = self.client.get(url)
        self.assertEqual(200, resp.status_code)
        self.assertTemplateUsed(resp, 'view_file_video.html')
        assert resp.context['filetype'].lower() == 'video'
        assert resp.context['err'] == ''

        raw_path = resp.context['raw_path']
        for _ in range(3):      # token for video is not one time only
            r = requests.get(raw_path)
            self.assertEqual(200, r.status_code)

    def test_can_download(self):
        self.login_as(self.user)

        url = reverse('view_lib_file', args=[self.repo.id, self.file]) + '?dl=1'
        resp = self.client.get(url)
        self.assertEqual(302, resp.status_code)
        assert '8082/files/' in resp.get('location')
