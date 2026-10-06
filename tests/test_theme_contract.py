"""Static contract checks complement the live browser theme validation."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ThemeContractTests(unittest.TestCase):
    def test_theme_preference_is_applied_before_dashboard_render(self):
        html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
        self.assertLess(html.index("localStorage.getItem('chepauk-theme')"),
                        html.index("<link rel=\"stylesheet\""))
        self.assertIn("prefers-color-scheme: light", html)
        self.assertIn('id="themeToggle"', html)

    def test_theme_switch_persists_and_updates_renderer(self):
        app = (ROOT / "ui" / "js" / "app.js").read_text(encoding="utf-8")
        renderer = (ROOT / "ui" / "js" / "renderer3d.js").read_text(encoding="utf-8")
        css = (ROOT / "ui" / "css" / "style.css").read_text(encoding="utf-8")
        self.assertIn("localStorage.setItem('chepauk-theme', selected)", app)
        self.assertIn("renderer.setTheme?.(selected)", app)
        self.assertIn("setTheme(theme)", renderer)
        self.assertIn('[data-theme="light"]', css)
        self.assertIn("--map-bg", css)


if __name__ == "__main__":
    unittest.main()
