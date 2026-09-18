from __future__ import annotations

from dataclasses import dataclass
import hashlib
from html.parser import HTMLParser
import ipaddress
from pathlib import Path
import re
import socket
import subprocess
import tempfile
from urllib import error, parse, request


MAX_PDF_BYTES = 60 * 1024 * 1024
MAX_HTML_BYTES = 3 * 1024 * 1024
USER_AGENT = "PaperDataAgent/1.0 (public academic paper importer)"
PROXY_FAKE_IP_RANGE = ipaddress.ip_network("198.18.0.0/15")


@dataclass(slots=True)
class DownloadedPaper:
    path: Path
    source_url: str
    resolved_url: str
    title: str
    sha256: str


@dataclass(slots=True)
class PublicURLStatus:
    available: bool
    status_code: int
    final_url: str


class _PaperPageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.pdf_candidates: list[str] = []
        self.title = ""
        self._in_title = False
        self._title_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): value or "" for key, value in attrs}
        if tag.lower() == "meta":
            name = (values.get("name") or values.get("property") or "").lower()
            content = values.get("content", "")
            if name in {"citation_pdf_url", "eprints.document_url", "pdf_url"} and content:
                self.pdf_candidates.append(content)
            if name in {"citation_title", "dc.title", "og:title"} and content and not self.title:
                self.title = content.strip()
        elif tag.lower() == "a":
            href = values.get("href", "")
            if href and (".pdf" in href.lower() or "/pdf/" in href.lower()):
                self.pdf_candidates.append(href)
        elif tag.lower() == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self._in_title = False
            if not self.title:
                self.title = " ".join(self._title_parts).strip()

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_parts.append(data.strip())


def _validate_public_url(url: str, allow_private: bool = False) -> parse.ParseResult:
    parsed = parse.urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("只支持完整的 http 或 https 公开网址")
    if parsed.username or parsed.password:
        raise ValueError("网址不能包含用户名或密码")
    if not allow_private:
        hostname_is_ip = False
        try:
            ipaddress.ip_address(parsed.hostname)
            hostname_is_ip = True
        except ValueError:
            pass
        try:
            addresses = {item[4][0] for item in socket.getaddrinfo(parsed.hostname, parsed.port or 443)}
        except socket.gaierror as exc:
            raise ValueError(f"无法解析网站地址：{parsed.hostname}") from exc
        for value in addresses:
            address = ipaddress.ip_address(value)
            if not hostname_is_ip and address in PROXY_FAKE_IP_RANGE:
                continue
            if not address.is_global:
                raise ValueError("只允许访问公开网站，不能访问本机或内网地址")
    return parsed


def _fetch_with_curl(url: str, max_bytes: int, allow_private: bool) -> tuple[bytes, str, str]:
    marker = "__PAPER_AGENT_META__"
    completed = subprocess.run(
        ["curl.exe", "--proxy", "", "--location", "--silent", "--show-error",
         "--max-time", "45", "--max-filesize", str(max_bytes),
         "--user-agent", USER_AGENT,
         "--header", "Accept: application/pdf,text/html;q=0.9,*/*;q=0.5",
         "--output", "-", "--write-out", f"%{{stderr}}\n{marker}%{{url_effective}}\t%{{content_type}}", url],
        capture_output=True, timeout=50, check=False,
    )
    stderr = completed.stderr.decode("utf-8", errors="replace")
    metadata = stderr.rsplit(marker, 1)[-1].strip().split("\t", 1) if marker in stderr else []
    if completed.returncode != 0 or len(metadata) != 2:
        detail = stderr.replace(marker, "").strip()[-500:]
        raise ValueError("公开论文下载失败：" + (detail or f"curl {completed.returncode}"))
    final_url, content_type = metadata
    _validate_public_url(final_url, allow_private=allow_private)
    return completed.stdout, final_url, content_type.split(";", 1)[0].strip().lower()


def probe_public_url(url: str, timeout_seconds: int = 15) -> PublicURLStatus:
    """Check that a public paper page still exists without downloading its body."""
    _validate_public_url(url)
    zenodo = re.search(r"(?:zenodo\.|/records/|zenodo/)(\d+)", url, re.I)
    probe_url = f"https://zenodo.org/api/records/{zenodo.group(1)}" if zenodo else url
    marker = "__PAPER_AGENT_PROBE__"
    completed = subprocess.run(
        ["curl.exe", "--proxy", "", "--location", "--silent", "--show-error",
         "--max-time", str(max(3, min(int(timeout_seconds), 30))),
         "--max-filesize", str(1024 * 1024), "--range", "0-65535",
         "--write-out", f"%{{stderr}}\n{marker}%{{http_code}}\t%{{url_effective}}", probe_url],
        capture_output=True,
        timeout=max(8, min(int(timeout_seconds) + 5, 35)), check=False,
    )
    stderr = completed.stderr.decode("utf-8", errors="replace")
    metadata = stderr.rsplit(marker, 1)[-1].strip() if marker in stderr else ""
    parts = metadata.rsplit("\t", 1)
    try:
        status = int(parts[0]) if parts else 0
    except ValueError:
        status = 0
    final_url = parts[1] if len(parts) == 2 else probe_url
    _validate_public_url(final_url)
    sample = completed.stdout.decode("utf-8", errors="replace").casefold()
    removed_markers = (
        "record you are trying to access was removed",
        "page you are trying to access has been removed",
        '"is_deleted": true',
        '"deletion_status": {"is_deleted": true',
        '"status": 410',
        '"removal_reason"',
    )
    removed = any(marker_text in sample for marker_text in removed_markers)
    available = 200 <= status < 400 and not removed
    return PublicURLStatus(available, status, url if available and zenodo else final_url)


def _fetch(url: str, max_bytes: int, allow_private: bool) -> tuple[bytes, str, str]:
    _validate_public_url(url, allow_private=allow_private)
    req = request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/pdf,text/html;q=0.9,*/*;q=0.5"})
    try:
        with request.urlopen(req, timeout=30) as response:
            final_url = response.geturl()
            _validate_public_url(final_url, allow_private=allow_private)
            content_type = response.headers.get_content_type()
            declared = response.headers.get("Content-Length")
            if declared and int(declared) > max_bytes:
                raise ValueError("远程文件过大，已拒绝下载")
            data = response.read(max_bytes + 1)
    except (error.URLError, error.HTTPError, TimeoutError, OSError):
        # Windows Python may inherit a stale TLS/proxy chain while curl can reach
        # the same public resource directly. Keep redirects and the effective URL
        # visible so the public-address check still applies.
        data, final_url, content_type = _fetch_with_curl(url, max_bytes, allow_private)
    # A few publishers return a bot/interstitial HTML page to urllib for a
    # direct PDF URL while the same public URL works via the system curl stack.
    parsed_path = parse.urlparse(url).path.lower()
    if content_type in {"text/html", "application/xhtml+xml"} and (
        parsed_path.endswith(".pdf") or "/pdf/" in parsed_path
    ):
        try:
            curl_data, curl_url, curl_type = _fetch_with_curl(url, max_bytes, allow_private)
            if curl_data.startswith(b"%PDF") or curl_type == "application/pdf":
                data, final_url, content_type = curl_data, curl_url, curl_type
        except (ValueError, subprocess.SubprocessError, OSError):
            pass
    if len(data) > max_bytes:
        raise ValueError("远程文件超过大小限制")
    return data, final_url, content_type


def _safe_title(value: str) -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", " ", value).strip(" .")
    return re.sub(r"\s+", " ", cleaned)[:160] or "downloaded-paper"


def _pmc_article_url(url: str) -> str:
    """Return the stable PMC article page for a PMC PDF/page URL."""
    match = re.search(r"pmc\.ncbi\.nlm\.nih\.gov/articles/(PMC\d+)", url, re.I)
    return f"https://pmc.ncbi.nlm.nih.gov/articles/{match.group(1).upper()}/" if match else ""


def _render_public_html_pdf(html: bytes, base_url: str) -> bytes:
    """Render a public full-text HTML article to a readable PDF snapshot.

    PMC now places a JavaScript proof-of-work page in front of some PDF files.
    Its public article HTML remains available, so this fallback prints that full
    article instead of saving the challenge page or pretending no paper exists.
    JavaScript is disabled; images and styles may still load from public URLs.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise ValueError("PMC 正文可读取，但本机缺少 HTML 转 PDF 组件") from exc
    text = html.decode("utf-8", errors="replace")
    if len(re.sub(r"<[^>]+>", " ", text)) < 5000:
        raise ValueError("PMC 页面不是完整论文正文，未生成替代 PDF")
    base = f'<base href="{base_url}">'
    text = re.sub(r"<head(\s[^>]*)?>", lambda match: match.group(0) + base, text, count=1, flags=re.I)
    with tempfile.TemporaryDirectory(prefix="paper-agent-pmc-") as directory:
        output = Path(directory) / "article.pdf"
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                context = browser.new_context(java_script_enabled=False, viewport={"width": 1200, "height": 900})
                page = context.new_page()
                page.set_content(text, wait_until="domcontentloaded", timeout=45_000)
                page.wait_for_timeout(1_500)
                page.pdf(
                    path=str(output), format="A4", print_background=True,
                    margin={"top": "12mm", "right": "12mm", "bottom": "12mm", "left": "12mm"},
                )
                browser.close()
        except Exception as exc:
            raise ValueError(f"PMC 正文读取成功，但生成本地阅读副本失败：{exc}") from exc
        rendered = output.read_bytes()
    if not rendered.startswith(b"%PDF") or len(rendered) > MAX_PDF_BYTES:
        raise ValueError("PMC 正文的本地阅读副本无效或过大")
    return rendered


def _pmc_html_fallback(url: str, allow_private: bool) -> tuple[bytes, str, str, str]:
    article_url = _pmc_article_url(url)
    if not article_url:
        raise ValueError("不是可识别的 PMC 论文地址")
    html, resolved, content_type = _fetch(article_url, MAX_HTML_BYTES, allow_private)
    if content_type not in {"text/html", "application/xhtml+xml", "text/plain"}:
        raise ValueError("PMC 正文页未返回 HTML")
    parser = _PaperPageParser()
    parser.feed(html.decode("utf-8", errors="replace"))
    return _render_public_html_pdf(html, resolved), resolved, "application/pdf", parser.title


def download_public_paper(url: str, destination: Path, allow_private: bool = False) -> DownloadedPaper:
    """Download a public PDF directly or discover the PDF linked by a paper page."""
    source_url = url.strip()
    fetch_url = source_url
    if "nature.com/articles/" in fetch_url.lower() and fetch_url.lower().endswith("_reference.pdf"):
        fetch_url = fetch_url[:-len("_reference.pdf")] + ".pdf"
    cell = re.search(r"cell\.com/action/showPdf\?pii=([A-Za-z0-9]+)", fetch_url, re.I)
    if cell:
        fetch_url = f"https://www.cell.com/cell/pdf/{cell.group(1)}.pdf"
    arxiv = re.search(r"arxiv\.org/abs/([^?#]+)", fetch_url, re.I)
    if arxiv:
        fetch_url = f"https://arxiv.org/pdf/{arxiv.group(1)}"
    data, resolved_url, content_type = _fetch(fetch_url, MAX_PDF_BYTES, allow_private)
    title = ""
    is_pdf = data.startswith(b"%PDF") or content_type == "application/pdf"
    if not is_pdf:
        if content_type not in {"text/html", "application/xhtml+xml", "text/plain"}:
            raise ValueError(f"网页返回的不是 PDF 或 HTML：{content_type}")
        if len(data) > MAX_HTML_BYTES:
            raise ValueError("论文网页过大，无法安全解析")
        parser = _PaperPageParser()
        parser.feed(data.decode("utf-8", errors="replace"))
        title = parser.title
        if not parser.pdf_candidates:
            if _pmc_article_url(resolved_url):
                data, resolved_url, content_type, title = _pmc_html_fallback(resolved_url, allow_private)
                is_pdf = True
            else:
                raise ValueError("该网页中没有发现公开 PDF 链接")
        errors: list[str] = []
        for candidate in parser.pdf_candidates[:12] if not is_pdf else []:
            pdf_url = parse.urljoin(resolved_url, candidate)
            try:
                pdf_data, pdf_resolved, pdf_type = _fetch(pdf_url, MAX_PDF_BYTES, allow_private)
            except Exception as exc:
                errors.append(str(exc))
                continue
            if pdf_data.startswith(b"%PDF") or pdf_type == "application/pdf":
                data, resolved_url, is_pdf = pdf_data, pdf_resolved, True
                break
        if not is_pdf:
            if _pmc_article_url(resolved_url):
                data, resolved_url, content_type, title = _pmc_html_fallback(resolved_url, allow_private)
                is_pdf = True
            else:
                detail = errors[-1] if errors else "候选地址返回了网页而非 PDF"
                raise ValueError(f"网页包含 PDF 候选链接，但均未返回有效 PDF：{detail}")

    digest = hashlib.sha256(data).hexdigest()
    if not title:
        stem = Path(parse.unquote(parse.urlparse(resolved_url).path)).stem
        title = stem or f"paper-{digest[:8]}"
    title = _safe_title(title)
    destination.mkdir(parents=True, exist_ok=True)
    output = destination / f"{title}-{digest[:10]}.pdf"
    if not output.exists():
        output.write_bytes(data)
    return DownloadedPaper(output, source_url, resolved_url, title, digest)
