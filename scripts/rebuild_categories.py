#!/usr/bin/env python3
"""
rebuild_categories.py
=====================
Tự động scan toàn bộ bài viết dưới các folder blog/ và dich-vu/,
rồi rebuild lại trang category index.html tương ứng.

Cách dùng:
  python3 scripts/rebuild_categories.py

Cách hoạt động:
  - Scan mỗi sub-folder trong blog/{category}/ và dich-vu/{category}/
  - Đọc <title> và <meta description> từ mỗi file bài index.html
  - Tìm block markers <!-- ARTICLES_START --> ... <!-- ARTICLES_END -->
    trong file category index.html rồi replace nội dung bên trong
  - Nếu chưa có markers thì tự chèn trước </main>
"""

import os
import re
import sys
from pathlib import Path
from html.parser import HTMLParser

# ─── Cấu hình ────────────────────────────────────────────────────────────────

ROOT = Path(__file__).parent.parent  # thư mục gốc của project

# Các thư mục cần xử lý: (folder_cha, depth_category)
# depth=1 → blog/{category}/  mỗi sub-folder là một bài
# depth=2 → dich-vu/{category}/{sub-category}/ mỗi sub-folder của category là bài
SCAN_TARGETS = [
    {"parent": "blog",     "label_prefix": "Bài viết"},
    {"parent": "dich-vu",  "label_prefix": "Dịch vụ"},
]

MARKER_START = "<!-- ARTICLES_START -->"
MARKER_END   = "<!-- ARTICLES_END -->"

NAV_JS = """<script>
document.addEventListener("DOMContentLoaded",function(){
  document.querySelectorAll(".site-header").forEach(function(header){
    var btn=header.querySelector(".nav-toggle");
    var nav=header.querySelector(".main-nav");
    if(!btn||!nav)return;
    var closeMenu=function(){header.classList.remove("menu-open");btn.setAttribute("aria-expanded","false")};
    btn.addEventListener("click",function(){var open=header.classList.toggle("menu-open");btn.setAttribute("aria-expanded",open?"true":"false")});
    nav.querySelectorAll("a").forEach(function(link){link.addEventListener("click",function(){if(window.innerWidth<=860)closeMenu()})});
    window.addEventListener("resize",function(){if(window.innerWidth>860)closeMenu()})
  })
});
</script>"""

# ─── HTML Parser để đọc title + description ──────────────────────────────────

class ArticleMeta(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title = ""
        self.description = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == "title":
            self._in_title = True
        if tag == "meta":
            name = attrs_dict.get("name", "").lower()
            if name == "description":
                self.description = attrs_dict.get("content", "").strip()

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data


def extract_meta(filepath: Path) -> dict:
    """Đọc <title> và <meta description> từ file HTML."""
    try:
        content = filepath.read_text(encoding="utf-8")
        parser = ArticleMeta()
        parser.feed(content[:4000])  # chỉ cần đọc phần đầu
        title = parser.title.strip()
        # Bỏ phần " | Luật Thiên Bình" ở cuối title nếu có
        title = re.sub(r"\s*\|\s*Luật Thiên Bình\s*$", "", title).strip()
        return {
            "title": title or filepath.parent.name,
            "description": parser.description or "",
        }
    except Exception as e:
        print(f"  ⚠ Không đọc được {filepath}: {e}")
        return {"title": filepath.parent.name, "description": ""}


# ─── Tạo HTML cho từng card bài viết ─────────────────────────────────────────

def make_article_card(href: str, title: str, description: str) -> str:
    desc_html = f"<p>{description}</p>" if description else ""
    return (
        f'<a class="card link-card" href="{href}">'
        f"<h3>{title}</h3>"
        f"{desc_html}"
        f"</a>"
    )


def make_articles_block(articles: list, heading: str) -> str:
    """Tạo toàn bộ section chứa danh sách bài."""
    if not articles:
        return (
            f"\n{MARKER_START}\n"
            f'<section class="panel">'
            f"<h2>{heading}</h2>"
            f"<p>Chưa có bài viết nào trong chuyên mục này.</p>"
            f"</section>\n"
            f"{MARKER_END}\n"
        )

    cards_html = "\n".join(
        make_article_card(a["href"], a["title"], a["description"])
        for a in articles
    )
    return (
        f"\n{MARKER_START}\n"
        f'<section class="panel">\n'
        f"<h2>{heading}</h2>\n"
        f'<div class="grid cards-3">\n'
        f"{cards_html}\n"
        f"</div>\n"
        f"</section>\n"
        f"{MARKER_END}\n"
    )


# ─── Cập nhật file category index.html ───────────────────────────────────────

def update_category_page(category_path: Path, articles: list, heading: str):
    index_file = category_path / "index.html"
    if not index_file.exists():
        print(f"  ⚠ Không tìm thấy {index_file}, bỏ qua.")
        return

    content = index_file.read_text(encoding="utf-8")
    new_block = make_articles_block(articles, heading)

    if MARKER_START in content and MARKER_END in content:
        # Replace nội dung giữa markers
        pattern = re.compile(
            re.escape(MARKER_START) + r".*?" + re.escape(MARKER_END),
            re.DOTALL
        )
        new_content = pattern.sub(new_block.strip(), content)
        action = "cập nhật"
    else:
        # Chèn markers trước </main>
        if "</main>" in content:
            new_content = content.replace("</main>", new_block + "</main>", 1)
            action = "chèn mới"
        else:
            print(f"  ⚠ Không tìm thấy </main> trong {index_file}, bỏ qua.")
            return

    index_file.write_text(new_content, encoding="utf-8")
    print(f"  ✓ {index_file.relative_to(ROOT)} — {action} ({len(articles)} bài)")


# ─── Scan folder và thu thập bài viết ────────────────────────────────────────

def get_depth_for_parent(parent_name: str) -> int:
    """
    blog/  → article ngay trong {category}/{slug}/index.html (depth 1)
    dich-vu/ → article trong {category}/{slug}/index.html (depth 1 tính từ category)
    """
    return 1  # cả hai trường hợp đều depth 1 tính từ category folder


def scan_category(category_path: Path, parent_folder: str) -> list:
    """
    Trả về danh sách articles trong category này.
    Mỗi article là một sub-folder chứa index.html.
    """
    articles = []
    if not category_path.is_dir():
        return articles

    for entry in sorted(category_path.iterdir()):
        if not entry.is_dir():
            continue
        article_file = entry / "index.html"
        if not article_file.exists():
            continue
        meta = extract_meta(article_file)
        if not meta["title"]:
            continue

        # Tính relative href từ category index page
        # category index ở: {parent}/{category}/index.html
        # article ở:        {parent}/{category}/{slug}/index.html
        # → href relative = ../../{parent}/{category}/{slug}/
        # Nhưng vì link trong category page dùng relative path từ root của site,
        # ta dùng absolute path từ root (bắt đầu bằng /)
        # Hoặc relative từ vị trí của category index.html:
        href = f"{entry.name}/"

        articles.append({
            "href": href,
            "title": meta["title"],
            "description": meta["description"],
        })

    return articles


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    changed = 0
    errors  = 0

    for target in SCAN_TARGETS:
        parent_name = target["parent"]
        label_prefix = target["label_prefix"]
        parent_path = ROOT / parent_name

        if not parent_path.is_dir():
            print(f"⚠ Không tìm thấy folder {parent_path}, bỏ qua.")
            continue

        print(f"\n📁 Xử lý: {parent_name}/")

        for category_dir in sorted(parent_path.iterdir()):
            if not category_dir.is_dir():
                continue
            if not (category_dir / "index.html").exists():
                continue

            print(f"  📂 Category: {category_dir.name}/")
            articles = scan_category(category_dir, parent_name)

            if not articles:
                print(f"    (chưa có bài viết nào)")
                continue

            for a in articles:
                print(f"    – {a['title'][:60]}{'...' if len(a['title'])>60 else ''}")

            # Tiêu đề heading cho section bài viết
            if parent_name == "blog":
                heading = "Danh sách bài viết trong chuyên mục"
            else:
                heading = "Dịch vụ trong nhóm này"

            try:
                update_category_page(category_dir, articles, heading)
                changed += 1
            except Exception as e:
                print(f"  ✗ Lỗi khi cập nhật {category_dir}: {e}")
                errors += 1

    print(f"\n{'='*50}")
    print(f"✅ Hoàn tất — {changed} category đã cập nhật, {errors} lỗi.")
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
