"""Extração de texto de EPUB usando apenas a biblioteca padrão."""

from __future__ import annotations

import posixpath
import re
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from html import unescape

_XML_ENTITIES = {"amp", "lt", "gt", "quot", "apos"}

_BLOCK_TAGS = {
    "address", "article", "aside", "blockquote", "br", "dd", "div", "dl",
    "dt", "figcaption", "figure", "footer", "h1", "h2", "h3", "h4", "h5",
    "h6", "header", "hr", "li", "main", "nav", "ol", "p", "pre", "section",
    "table", "tbody", "td", "tfoot", "th", "thead", "tr", "ul",
}
_SKIP_TAGS = {"head", "script", "style"}

NCX_NS = "http://www.daisy.org/z3986/2005/ncx/"


@dataclass
class Chapter:
    title: str = ""
    text: str = ""


@dataclass
class Book:
    title: str = ""
    authors: list[str] = field(default_factory=list)
    chapters: list[Chapter] = field(default_factory=list)


def _local(tag: object) -> str:
    """Nome local de uma tag, ignorando namespaces e comentários/PIs."""
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1].lower()


def _child(el: ET.Element, name: str) -> ET.Element | None:
    for child in el:
        if _local(child.tag) == name:
            return child
    return None


def _children(el: ET.Element, name: str) -> list[ET.Element]:
    return [child for child in el if _local(child.tag) == name]


def _fix_entities(data: bytes) -> bytes:
    """Converte entidades HTML (ex.: &nbsp;) em entidades numéricas válidas no XML."""

    def repl(match: re.Match) -> bytes:
        name = match.group(1).decode("ascii")
        if name in _XML_ENTITIES:
            return match.group(0)
        char = unescape(f"&{name};")
        if len(char) == 1:
            return f"&#{ord(char)};".encode("ascii")
        return b" "

    return re.sub(rb"&([A-Za-z][A-Za-z0-9]*);", repl, data)


def _normalize(text: str) -> str:
    text = text.replace("\xa0", " ")
    lines = [re.sub(r"[ \t\r\f]+", " ", line).strip() for line in text.split("\n")]
    out: list[str] = []
    for line in lines:
        if not line:
            if out and out[-1]:
                out.append("")
        else:
            out.append(line)
    while out and not out[-1]:
        out.pop()
    return "\n".join(out)


def extract_text(xhtml: bytes) -> str:
    """Extrai texto legível de um documento XHTML, preservando quebras de bloco."""
    root = ET.fromstring(_fix_entities(xhtml))
    chunks: list[str] = []

    def walk(el: ET.Element) -> None:
        name = _local(el.tag)
        if name in _SKIP_TAGS:
            return
        if name == "img":
            alt = (el.get("alt") or "").strip()
            if alt:
                chunks.append(f"[imagem: {alt}] ")
            return
        if name in _BLOCK_TAGS:
            chunks.append("\n")
        if el.text:
            chunks.append(el.text)
        for child in el:
            walk(child)
            if child.tail:
                chunks.append(child.tail)
        if name in _BLOCK_TAGS:
            chunks.append("\n")

    walk(root)
    return _normalize("".join(chunks))


def chapter_title(xhtml: bytes) -> str:
    """Retorna o <head><title> de um documento XHTML (ou vazio)."""
    try:
        root = ET.fromstring(_fix_entities(xhtml))
    except ET.ParseError:
        return ""
    head = _child(root, "head")
    el = _child(head, "title") if head is not None else None
    if el is None:
        return ""
    return " ".join("".join(el.itertext()).split())


def toc_titles(zf: zipfile.ZipFile, base: str, manifest: dict) -> dict[str, str]:
    """Mapeia caminho de cada arquivo de texto -> rótulo do sumário (NCX)."""
    href = None
    for item in manifest.values():
        if (item.get("media-type") or "").lower() == "application/x-dtbncx+xml":
            href = item.get("href")
            break
    if href is None:
        return {}
    path = posixpath.normpath(posixpath.join(base, href))
    try:
        root = ET.fromstring(zf.read(path))
    except (KeyError, ET.ParseError):
        return {}
    titles: dict[str, str] = {}
    for nav in root.iter(f"{{{NCX_NS}}}navPoint"):
        text = nav.findtext(f"{{{NCX_NS}}}navLabel/{{{NCX_NS}}}text")
        content = nav.find(f"{{{NCX_NS}}}content")
        if text is None or content is None:
            continue
        src = (content.get("src") or "").split("#", 1)[0]
        if not src:
            continue
        key = posixpath.normpath(posixpath.join(base, src))
        if key not in titles:
            titles[key] = " ".join(text.split())
    return titles


def _looks_like_placeholder(title: str) -> bool:
    """Heurística: título sem espaços, terminando em dígito e longo (ex.: 'ProblemaDosTresCorpos-3')."""
    return not any(c.isspace() for c in title) and title[-1:].isdigit() and len(title) >= 8


def _resolve_title(toc: dict[str, str], path: str, data: bytes, text: str) -> str:
    """Título do capítulo: sumário (NCX) -> <head><title> -> primeira linha -> vazio."""
    title = toc.get(path, "")
    if not title:
        head = chapter_title(data)
        if head and not _looks_like_placeholder(head):
            title = head
    if not title:
        first = next((line.strip() for line in text.splitlines() if line.strip()), "")
        if first and len(first) <= 60 and not re.search(r"[.!?…:]$", first):
            title = first
    return title


def _opf_path(zf: zipfile.ZipFile) -> str:
    try:
        container = ET.fromstring(zf.read("META-INF/container.xml"))
    except KeyError as exc:
        raise ValueError("arquivo não contém META-INF/container.xml") from exc
    for el in container.iter():
        if _local(el.tag) == "rootfile" and el.get("full-path"):
            return el.get("full-path")
    raise ValueError("container.xml não indica o arquivo OPF raiz")


def read_book(zf: zipfile.ZipFile) -> Book:
    """Lê um EPUB (ZipFile aberto) e devolve título, autores e capítulos em texto."""
    book = Book()
    opf_path = _opf_path(zf)
    base = posixpath.dirname(opf_path)
    root = ET.fromstring(zf.read(opf_path))

    metadata = _child(root, "metadata")
    if metadata is not None:
        for el in metadata:
            name = _local(el.tag)
            text = " ".join((el.text or "").split())
            if not text:
                continue
            if name == "title" and not book.title:
                book.title = text
            elif name == "creator":
                book.authors.append(text)

    manifest_el = _child(root, "manifest")
    manifest = {
        item.get("id"): item for item in _children(manifest_el, "item")
    } if manifest_el is not None else {}

    spine = _child(root, "spine")
    toc = toc_titles(zf, base, manifest)
    for ref in (_children(spine, "itemref") if spine is not None else []):
        item = manifest.get(ref.get("idref"))
        if item is None or not item.get("href"):
            continue
        media = (item.get("media-type") or "").lower()
        if "html" not in media:
            continue
        path = posixpath.normpath(posixpath.join(base, item.get("href")))
        try:
            data = zf.read(path)
            text = extract_text(data)
        except (ET.ParseError, KeyError):
            continue
        if not text:
            continue
        book.chapters.append(
            Chapter(title=_resolve_title(toc, path, data, text), text=text)
        )

    if not book.chapters:
        raise ValueError("nenhum capítulo com texto foi encontrado no EPUB")
    return book
