from types import SimpleNamespace
from unittest.mock import patch
import io
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

    def test_embedded_definition_uses_native_panel_without_second_html_shell(self):
        request = RequestFactory().get("/settings/products/new/")
        request.user = SimpleNamespace(is_authenticated=True)
        upstream = ('<!doctype html><html><head><title>پنل دوم</title></head>'
                    '<body><header>OLD STANDALONE HEADER</header><main>'
                    '<div class="hero"><div><h1>تعریف محصولات اصلی</h1></div></div>'
                    '<div class="panel"><form method="post" action="/sales/digikala/master/add">'
                    '<input name="code"><button>ثبت محصول</button></form></div>'
                    '<a href="/sales/digikala/catalog">محصولات دیجی‌کالا</a>'
                    '<form action="/sales/digikala/master" method="get"><input name="q"></form>'
                    '</main><footer>OLD FOOTER</footer></body></html>')
        result = sister_sales.embedded_response(request, upstream, "master")
        html = result.content.decode("utf-8")
        self.assertEqual(result.status_code, 200)
        self.assertIn('class="erp-sidebar"', html)
        self.assertIn('class="erp-main"', html)
        self.assertIn('DARMA General', html)
        self.assertIn('تعریف محصولات اصلی', html)
        self.assertIn('action="/sales/digikala/master/add"', html)
        self.assertIn('action="/settings/products/new/"', html)
        self.assertIn('href="/settings/products/digikala/"', html)
        self.assertIn('name="csrfmiddlewaretoken"', html)
        self.assertNotIn("OLD STANDALONE HEADER", html)
        self.assertNotIn("OLD FOOTER", html)
        self.assertEqual(html.count("<html "), 1)
        self.assertEqual(html.count("</html>"), 1)

    def test_canonical_get_redirects_but_not_post_endpoints(self):
        self.assertEqual(
            sister_sales.public_redirect_location("/daily-sales/master?category=%D9%82%D8%A7%D9%84%D8%A8"),
            "/settings/products/new/?category=%D9%82%D8%A7%D9%84%D8%A8",
        )
        self.assertEqual(
            sister_sales.public_redirect_location("/daily-sales/master/stock"),
            "/inventory/stock/",
        )
        self.assertIsNone(sister_sales.public_redirect_location("https://untrusted.example/x"))
        html = sister_sales.canonical_page_links(
            '<a href="/sales/digikala/master?category=x">test</a>'
            '<form action="/sales/digikala/master/edit" method="post"></form>'
        )
        self.assertIn('href="/settings/products/new/?category=x"', html)
        self.assertIn('action="/sales/digikala/master/edit"', html)

    def test_authenticated_proxy_embeds_backend_page_in_native_shell(self):
        class FakeUpstream(io.BytesIO):
            status = 200
            headers = {"Content-Type": "text/html; charset=utf-8"}
        markup = (b'<html><head></head><body><header>OTHER UI</header><main>'
                  b'<div class="hero"><div><h1>Products</h1></div></div>'
                  b'<div class="panel">OK</div></main></body></html>')
        request = RequestFactory().get("/settings/products/new/")
        request.user = SimpleNamespace(is_authenticated=True)
        opener = SimpleNamespace(open=lambda *args, **kwargs: FakeUpstream(markup))
        with patch.dict(sister_sales.os.environ, {"SALES_ADMIN_PASSWORD": "x"*32}), \
             patch.object(sister_sales.http_request, "build_opener", return_value=opener):
            response = sister_sales.digikala_proxy(request, tail="master")
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn('class="erp-sidebar"', html)
        self.assertIn("Products", html)
        self.assertNotIn("OTHER UI", html)

    def test_multipart_preserves_uploaded_xlsx(self):
        upload=SimpleUploadedFile("sample.xlsx",b"example-bytes",content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        request=RequestFactory().post("/sales/digikala/preview",{"sale_date":"2026-10-31","files":upload})
        payload,mime=sister_sales.multipart_body(request)
        self.assertIn(b"example-bytes",payload)
        self.assertIn(b"sample.xlsx",payload)
        self.assertTrue(mime.startswith("multipart/form-data"))
