from html.parser import HTMLParser
from pathlib import Path

import yaml


ROOT = Path(__file__).parents[1]
GUIDE = ROOT / "docs" / "guide"
STEPS = (
    "01_open_app", "02_choose_image_provider", "03_configure_comfyui",
    "04_configure_local_vision", "05_install_quality_tools",
    "06_configure_training", "07_create_dataset", "08_import_photos",
    "09_review_corpus", "10_choose_anchors", "11_review_coverage",
    "12_set_primary_reference", "13_generate_missing_views",
    "14_curate_images", "15_caption_images", "16_score_face_similarity",
    "17_export_dataset", "18_train_lora", "19_review_checkpoints",
    "20_test_studio", "21_back_up_dataset",
)


class GuidePageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.h1_count = 0
        self.main_count = 0
        self.scripts = 0
        self.iframes = 0
        self.images = []
        self.links = []
        self.stylesheets = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "h1":
            self.h1_count += 1
        elif tag == "main":
            self.main_count += 1
        elif tag == "script":
            self.scripts += 1
        elif tag == "iframe":
            self.iframes += 1
        elif tag == "img":
            self.images.append((values.get("src", ""), values.get("alt", "")))
        elif tag == "a":
            self.links.append(values.get("href", ""))
        elif tag == "link" and values.get("rel") == "stylesheet":
            self.stylesheets.append(values.get("href", ""))


def parse(path):
    parser = GuidePageParser()
    parser.feed(path.read_text(encoding="utf-8"))
    return parser


def assert_local_links_exist(page_path, page):
    for target in page.links:
        if not target or target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        destination = (page_path.parent / target.split("#", 1)[0]).resolve()
        assert destination.is_file(), f"{page_path.name}: {target}"


def test_flat_html_guide_has_one_static_page_and_genuine_screenshot_per_step():
    index = parse(GUIDE / "getting-started.html")
    step_links = [link for link in index.links if link.startswith("steps/") and link.endswith(".html")]
    assert index.scripts == 0
    assert index.iframes == 0
    assert index.stylesheets == ["first-run.css"]
    assert_local_links_exist(GUIDE / "getting-started.html", index)
    assert step_links == [f"steps/{step}.html" for step in STEPS]

    manifest = yaml.safe_load(
        (ROOT / "docs" / "screenshots" / "manifest.yml").read_text(encoding="utf-8")
    )
    current = {
        entry["path"] for entry in manifest["screenshots"]
        if entry.get("status") == "current"
    }

    for index, step in enumerate(STEPS):
        page_path = GUIDE / "steps" / f"{step}.html"
        assert page_path.is_file(), step
        page = parse(page_path)
        assert page.scripts == 0, step
        assert page.iframes == 0, step
        assert page.stylesheets == ["../first-run.css"], step
        assert_local_links_exist(page_path, page)
        assert page.main_count == 1, step
        assert page.h1_count == 1, step
        assert len(page.images) == 1, step
        image_src, image_alt = page.images[0]
        assert image_src == f"../../screenshots/guide/{step}.jpg", step
        assert image_alt.strip(), step
        assert (page_path.parent / image_src).resolve().is_file(), step
        assert f"guide/{step}.jpg" in current, step
        if index:
            assert f"{STEPS[index - 1]}.html" in page.links, step
        if index < len(STEPS) - 1:
            assert f"{STEPS[index + 1]}.html" in page.links, step
