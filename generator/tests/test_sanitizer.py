from django.test import SimpleTestCase

from generator.services.sanitizer import (
    document_from_html,
    document_from_text,
    sanitize_email_html,
)


class SanitizerTests(SimpleTestCase):
    def test_scripts_are_removed(self):
        dirty = '<p>Hello</p><script>alert(1)</script>'
        clean = sanitize_email_html(dirty)
        self.assertNotIn("<script", clean.lower())
        self.assertIn("Hello", clean)

    def test_event_handlers_are_removed(self):
        clean = sanitize_email_html('<p onclick="alert(1)">Click</p>')
        self.assertNotIn("onclick", clean.lower())

    def test_javascript_urls_are_removed(self):
        clean = sanitize_email_html('<a href="javascript:alert(1)">x</a>')
        self.assertNotIn("javascript:", clean.lower())

    def test_images_are_removed(self):
        clean = sanitize_email_html('<p>Hi</p><img src="https://tracker.example/pixel.gif">')
        self.assertNotIn("<img", clean.lower())
        self.assertIn("Hi", clean)

    def test_iframes_forms_and_meta_are_removed(self):
        dirty = (
            '<iframe src="https://evil.example"></iframe>'
            "<form action=\"https://evil.example\"><input name=\"x\"></form>"
            '<meta http-equiv="refresh" content="0;url=https://evil.example">'
            "<object data=\"x\"></object>"
        )
        clean = sanitize_email_html(dirty)
        for needle in ("<iframe", "<form", "<input", "<meta", "<object"):
            self.assertNotIn(needle, clean.lower())

    def test_style_attributes_and_blocks_are_removed(self):
        clean = sanitize_email_html('<style>body{display:none}</style><p style="color:red">x</p>')
        self.assertNotIn("<style", clean.lower())
        self.assertNotIn("style=", clean.lower())

    def test_formatting_survives(self):
        dirty = "<p><strong>Bold</strong> and <em>italic</em></p><ul><li>one</li></ul>"
        clean = sanitize_email_html(dirty)
        self.assertIn("<strong>Bold</strong>", clean)
        self.assertIn("<em>italic</em>", clean)
        self.assertIn("<li>one</li>", clean)

    def test_links_get_safe_rel(self):
        clean = sanitize_email_html('<a href="https://example.com">link</a>')
        self.assertIn("noopener", clean)
        self.assertIn("nofollow", clean)

    def test_empty_input(self):
        self.assertEqual(sanitize_email_html(""), "")

    def test_document_contains_no_sender_markup(self):
        doc = document_from_html(sanitize_email_html('<p onclick="x()">Body</p>'), title="T")
        self.assertIn("<!doctype html>", doc.lower())
        self.assertNotIn("onclick", doc.lower())

    def test_text_document_escapes_html(self):
        doc = document_from_text('<script>alert(1)</script>')
        self.assertNotIn("<script>", doc)
        self.assertIn("&lt;script&gt;", doc)
