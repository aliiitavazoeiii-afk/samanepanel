from types import SimpleNamespace
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.urls import resolve, reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from . import sister_sales

# The production runtime runs collectstatic before serving requests, whereas
# a standalone SimpleTestCase deliberately does not create a staticfiles manifest.
# Use the non-manifest storage backend ONLY for test rendering so we verify
# channel routes and HTML without depending on a built asset manifest.
@override_settings(STORAGES={
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
})
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

    def test_definitions_routes_and_five_categories(self):
        self.assertEqual(reverse("settings_products"), "/settings/products/")
        self.assertEqual(reverse("settings_product_new"), "/settings/products/new/")
        self.assertEqual(reverse("sister_product_digikala"), "/settings/products/digikala/")
        self.assertEqual(reverse("inventory_stock"), "/inventory/stock/")
        self.assertEqual(resolve("/inventory/stock/").func, sister_sales.digikala_proxy)
        from . import sister_master
        request = RequestFactory().get("/settings/products/")
        request.user = SimpleNamespace(is_authenticated=True)
        response = sister_master.products(request)
        self.assertEqual(response.status_code, 200)
        html = response.content.decode("utf-8")
        for category in ("زیرپوش دارما", "شورت زنانه دارما",
                         "شورت زنانه دیا", "بادیگارد", "قالب"):
            self.assertIn(category, html)
        self.assertIn("محصولات دیجی‌کالا", html)

    def test_master_proxy_requires_auth(self):
        for url in ("/settings/products/new/", "/settings/products/digikala/",
                    "/inventory/stock/", "/sales/digikala/master/add"):
            self.assertEqual(self.client.get(url).status_code, 302)

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
