"""Interface de linha de comando do pylibre."""

from __future__ import annotations

import argparse
import os
import re
import sys
import zipfile
from pathlib import Path

from .epub import read_book

_INVALID_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def _safe_name(name: str) -> str:
    """Deixa um nome de arquivo seguro (sem caracteres inválidos, curto e sem espaços extras)."""
    name = _INVALID_CHARS.sub(" ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name[:80].rstrip(" .")


def _chapter_filename(index: int, title: str, width: int) -> str:
    safe = _safe_name(title)
    if safe:
        return f"{index:0{width}d} - {safe}.txt"
    return f"{index:0{width}d}.txt"


def _unique_name(name: str, used: set[str]) -> str:
    if name not in used:
        used.add(name)
        return name
    stem, ext = os.path.splitext(name)
    n = 2
    while f"{stem} ({n}){ext}" in used:
        n += 1
    result = f"{stem} ({n}){ext}"
    used.add(result)
    return result


def _parse_selection(raw: str, total: int) -> list[int]:
    """Converte a entrada do usuário em índices 1-based (ordenados).

    Aceita: "t"/"a"/"*"/vazio (todos), "1,3,5", "1-5", combinações "1-3,7".
    Lança ValueError para entradas inválidas.
    """
    s = raw.strip().lower()
    if s in ("", "t", "a", "todos", "all", "*"):
        return list(range(1, total + 1))
    selected: set[int] = set()
    for part in re.split(r"[,\s]+", s):
        if not part:
            continue
        if "-" in part:
            sides = part.split("-")
            if len(sides) != 2 or not all(x.isdigit() for x in sides):
                raise ValueError(f"faixa inválida: '{part}'")
            a, b = int(sides[0]), int(sides[1])
            lo, hi = (a, b) if a <= b else (b, a)
        else:
            if not part.isdigit():
                raise ValueError(f"entrada inválida: '{part}'")
            lo = hi = int(part)
        if lo < 1 or hi > total:
            raise ValueError(f"número fora do intervalo (1-{total})")
        selected.update(range(lo, hi + 1))
    if not selected:
        raise ValueError("nenhum capítulo selecionado")
    return sorted(selected)


def _prompt_selection(book) -> list[int] | None:
    """Lista os capítulos numerados e pergunta ao usuário quais extrair.

    Retorna índices 1-based; None se o usuário cancelar ("q") ou fechar a entrada.
    """
    total = len(book.chapters)
    nome = book.title or "(sem título)"
    print(f"\n{nome} — {total} capítulo(s):")
    for i, ch in enumerate(book.chapters, 1):
        titulo = ch.title or f"capítulo {i}"
        if len(titulo) > 60:
            titulo = titulo[:57] + "..."
        print(f"  {i:>3}. {titulo}")
    while True:
        try:
            raw = input(
                "Seleção (ex.: 1,3,5 | 1-5 | t = todos | q = cancelar) [Enter = todos]: "
            )
        except EOFError:
            return None
        if raw.strip().lower() in ("q", "quit", "sair", "c"):
            return None
        try:
            return _parse_selection(raw, total)
        except ValueError as exc:
            print(f"  entrada inválida: {exc}")


def convert(
    src: str,
    out: str | None = None,
    include_meta: bool = True,
    capitulos: bool = False,
    multi: bool = False,
    selecionar: list[int] | None = None,
) -> tuple[str, str]:
    """Converte um EPUB em texto puro.

    - Modo padrão: gera um único `.txt` e devolve (caminho, "N caracteres").
    - Modo capítulos (`capitulos=True`): gera uma pasta com um `.txt` por
      capítulo e devolve (pasta, "N capítulos").
    - `selecionar`: índices 1-based dos capítulos a extrair (None = todos).
      A numeração original do livro é preservada nos nomes dos arquivos.
    """
    with zipfile.ZipFile(src) as zf:
        book = read_book(zf)

    indices = selecionar or list(range(1, len(book.chapters) + 1))
    chapters = [
        (i, book.chapters[i - 1]) for i in indices if 1 <= i <= len(book.chapters)
    ]
    if not chapters:
        raise ValueError("nenhum capítulo selecionado")

    if not capitulos:
        blocks: list[str] = []
        if include_meta and (book.title or book.authors):
            head = book.title or "(sem título)"
            if book.authors:
                head += "\n" + ", ".join(book.authors)
            blocks.append(head)
        blocks.extend(ch.text for _, ch in chapters)
        text = "\n\n".join(blocks).strip() + "\n"
        destino = Path(out) if out else Path(os.path.splitext(src)[0] + ".txt")
        destino.write_text(text, encoding="utf-8")
        return str(destino), f"{len(text)} caracteres"

    stem = os.path.splitext(os.path.basename(src))[0]
    if out:
        folder = Path(out) / stem if multi else Path(out)
    else:
        folder = Path(os.path.dirname(os.path.abspath(src))) / stem
    folder.mkdir(parents=True, exist_ok=True)

    width = max(2, len(str(max(i for i, _ in chapters))))
    used: set[str] = set()
    for i, chapter in chapters:
        name = _unique_name(_chapter_filename(i, chapter.title, width), used)
        (folder / name).write_text(chapter.text.strip() + "\n", encoding="utf-8")
    return str(folder) + "/", f"{len(chapters)} capítulos"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="pylibre",
        description="Converte arquivos EPUB em texto puro (.txt).",
    )
    parser.add_argument("epub", nargs="+", help="arquivo(s) .epub para converter")
    parser.add_argument(
        "-o", "--output",
        help=(
            "arquivo de saída (modo padrão) ou pasta de saída (--capitulos); "
            "com vários EPUBs e --capitulos, funciona como pasta-base"
        ),
    )
    parser.add_argument(
        "--no-meta", action="store_true",
        help="não incluir título e autor no início do arquivo (ignorado com --capitulos)",
    )
    parser.add_argument(
        "--capitulos", action="store_true",
        help="gera uma pasta com um .txt por capítulo (em vez de um único arquivo)",
    )
    parser.add_argument(
        "--escolher", action="store_true",
        help="lista os capítulos numerados e pergunta quais extrair "
             "(1,3,5 | 1-5 | t = todos | q = cancelar)",
    )
    args = parser.parse_args(argv)

    multi = len(args.epub) > 1
    if multi and args.output and not args.capitulos:
        parser.error("--output só é válido com um único EPUB de entrada")

    failed = 0
    for src in args.epub:
        selecionar = None
        if args.escolher:
            try:
                with zipfile.ZipFile(src) as zf:
                    book = read_book(zf)
            except Exception as exc:
                print(f"erro ao listar capítulos de {src}: {exc}", file=sys.stderr)
                failed += 1
                continue
            try:
                selecionar = _prompt_selection(book)
            except KeyboardInterrupt:
                selecionar = None
            if selecionar is None:
                print(f"cancelado: {src}")
                continue
        try:
            saida, resumo = convert(
                src,
                out=args.output,
                include_meta=not args.no_meta,
                capitulos=args.capitulos,
                multi=multi,
                selecionar=selecionar,
            )
        except FileNotFoundError:
            print(f"erro: arquivo não encontrado: {src}", file=sys.stderr)
        except zipfile.BadZipFile:
            print(f"erro: {src} não parece um EPUB válido (não é um ZIP)", file=sys.stderr)
        except (ValueError, KeyError, OSError) as exc:
            print(f"erro: {src}: {exc}", file=sys.stderr)
        except Exception as exc:  # falha inesperada: mostra, mas continua com os demais
            print(f"erro inesperado em {src}: {type(exc).__name__}: {exc}", file=sys.stderr)
        else:
            print(f"ok: {src} -> {saida} ({resumo})")
            continue
        failed += 1
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
