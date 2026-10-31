from types import SimpleNamespace
from django.test import RequestFactory, SimpleTestCase
from django.urls import resolve, reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from . import sister_sales

class SalesChannelRoutesTest(SimpleTestCase):
    def test_sales_path_is_channels_and_all_four_named(self):
        self.assertEqual(reverse("sale_start"), "/sales/")
        self.assertEqual(resolve("/sales/").url_name, "sale_start")
        for route in ("sister_sales_digikala", "sister_sales_site",
                      "sister_sales_basalam", "sister_sales_ghaleb"):
            self.assertTrue(reverse(route).startswith("/sales/"))

    def test_authenticated_cards_without_old_brand_seed(self):
        request = RequestFactory().get("/sales/")
        request.user = SimpleNamespace(is_authenticated=True)
        response = sister_sales.channels(request)
        text = response.content.decode("utf-8")
        for word in ("فروش دیجی‌کالا", "فروش سایت", "فروش باسلام", "فروش قالب"):
            self.assertIn(word, text)
        self.assertEqual(response.status_code, 200)

    def test_proxy_requires_auth(self):
        response = self.client.get("/sales/digikala/")
        self.assertEqual(response.status_code,302)

    def test_post_form_has_csrf_token(self):
        request = RequestFactory().get("/sales/digikala/")
        html = sister_sales.add_csrf(request,'<form action="/x" method="post"><button>ok</button></form>')
        self.assertIn('name="csrfmiddlewaretoken"',html)

    def test_multipart_preserves_uploaded_xlsx(self):
        upload=SimpleUploadedFile("sample.xlsx",b"example-bytes",content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        request=RequestFactory().post("/sales/digikala/preview",{"sale_date":"2026-10-31","files":upload})
        payload,mime=sister_sales.multipart_body(request)
        self.assertIn(b"example-bytes",payload)
        self.assertIn(b"sample.xlsx",payload)
        self.assertTrue(mime.startswith("multipart/form-data"))
