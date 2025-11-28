from __future__ import annotations

import logging
import re
import csv
from pathlib import Path
from typing import List, Optional

import typer
from tqdm import tqdm

try:
    import argostranslate.package  # type: ignore
    import argostranslate.translate  # type: ignore
except ImportError:
    argostranslate = None  # type: ignore

from commons_client import CommonsClient

app = typer.Typer(add_completion=False)


def ensure_model(src: str, dest: str):
    if argostranslate is None:
        raise RuntimeError("argostranslate not installed. Install via `pip install argostranslate`.")
    available_packages = argostranslate.package.get_available_packages()
    installed_languages = argostranslate.translate.get_installed_languages()
    if not any(lang.code == src for lang in installed_languages):
        for pkg in available_packages:
            if pkg.from_code == src and pkg.to_code == dest:
                argostranslate.package.install_from_path(pkg.download())
                break
    argostranslate.translate.load_installed_languages()


def simple_replace_description(text: str, source_lang: str, src_desc: str, translations: dict) -> Optional[str]:
    """Replace description field in {{Information}} when it's plain text."""
    pattern = r"(description\s*=\s*)([^\n]+)"
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if not match:
        return None
    current = match.group(2).strip()
    # Only proceed if current description looks plain (no braces)
    if "{" in current or "}" in current:
        return None
    parts = [f"{source_lang}={current}"] + [f"{lang}={val}" for lang, val in translations.items()]
    new_desc = "{{Multilingual description|" + "|".join(parts) + "}}"
    return re.sub(pattern, rf"\1{new_desc}", text, flags=re.IGNORECASE)


def translate_text(src_lang: str, dest_lang: str, text: str) -> str:
    translator = argostranslate.translate.get_translation(src_lang, dest_lang)
    return translator.translate(text)


@app.command()
def main(
    category: str = typer.Option(..., "--category", help="Category name (without 'Category:' prefix)"),
    source_lang: str = typer.Option("en", "--source-lang", help="Source language code"),
    targets: List[str] = typer.Option(
        ["en", "es", "fr", "pt", "ru", "zh", "de"], "--target-lang", help="Target language codes (repeatable)"
    ),
    max_depth: int = typer.Option(1, "--max-depth", help="Category recursion depth"),
    apply: bool = typer.Option(False, "--apply", help="Apply edits (default: dry-run)"),
    commons_user: str = typer.Option(
        None,
        "--commons-user",
        envvar="COMMONS_USER",
        prompt="Commons username",
    ),
    commons_pass: str = typer.Option(
        None,
        "--commons-pass",
        envvar="COMMONS_PASS",
        prompt=True,
        hide_input=True,
    ),
):
    """Translate descriptions for files in a category and optionally update wikitext."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if argostranslate is None:
        raise typer.Exit("argostranslate not installed. Run `pip install argostranslate` first.")
    for tgt in targets:
        ensure_model(source_lang, tgt)

    client = CommonsClient(commons_user, commons_pass)
    uploads = client.list_category_files(category, max_depth=max_depth)
    # Filter JPEGs only
    uploads = [u for u in uploads if u.title.lower().endswith((".jpg", ".jpeg"))]
    progress = tqdm(total=len(uploads), desc="Translating", unit="file", colour="magenta")
    updated = 0
    skipped = 0
    errors = 0
    for u in uploads:
        try:
            page = client._site.pages[u.title]  # type: ignore
            text = page.text()
            desc_match = re.search(r"description\s*=\s*([^\n]+)", text, flags=re.IGNORECASE)
            if not desc_match:
                skipped += 1
                progress.write(f"Skipping {u.title}: no description field")
                progress.update(1)
                continue
            current_desc = desc_match.group(1).strip()
            if "{" in current_desc or "}" in current_desc:
                skipped += 1
                progress.write(f"Skipping {u.title}: complex description")
                progress.update(1)
                continue
            translations = {}
            for tgt in targets:
                translations[tgt] = translate_text(source_lang, tgt, current_desc)
            new_text = simple_replace_description(text, source_lang, current_desc, translations)
            if not new_text:
                skipped += 1
                progress.write(f"Skipping {u.title}: could not rewrite safely")
                progress.update(1)
                continue
            if apply:
                page.save(new_text, summary=f"Add machine translation ({','.join(targets)}) to description")
                updated += 1
            else:
                progress.write(f"Dry-run {u.title}: {translations}")
                updated += 1
        except Exception as exc:
            errors += 1
            progress.write(f"Error on {u.title}: {exc}")
            logging.exception("Error translating %s", u.title)
        progress.update(1)
    progress.close()
    client.cleanup()
    print(f"Done. Updated (or previewed): {updated}, skipped: {skipped}, errors: {errors}")


if __name__ == "__main__":
    app()
