from __future__ import annotations

import logging
import re
import csv
from pathlib import Path
from typing import List, Optional, Dict

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
    languages = argostranslate.translate.get_installed_languages()
    from_lang = next((l for l in languages if l.code == src_lang), None)
    to_lang = next((l for l in languages if l.code == dest_lang), None)
    if not from_lang or not to_lang:
        raise RuntimeError(f"Missing translation model {src_lang}->{dest_lang}")
    translator = from_lang.get_translation(to_lang)
    return translator.translate(text)


def parse_lang_templates(desc: str) -> Dict[str, str]:
    """Parse {{en|...}} style language templates into a dict."""
    langs = {}
    for m in re.finditer(r"\{\{\s*([a-zA-Z-]{2,10})\s*\|([^{}]+?)\}\}", desc, flags=re.DOTALL):
        lang = m.group(1).strip().lower()
        content = m.group(2).strip()
        # strip possible leading numbering like 1=
        if content.startswith("1="):
            content = content[2:].strip()
        langs[lang] = content
    return langs


def build_multilingual_desc(lang_map: Dict[str, str]) -> str:
    parts = [f"{lang}={text}" for lang, text in lang_map.items()]
    return "{{Multilingual description|" + "|".join(parts) + "}}"


def find_description_blocks(text: str):
    # capture description= ... until next |foo= or end of template
    pattern = re.compile(r"(description\s*=\s*)(.*?)(\n\|[a-zA-Z_]+\s*=|\n\}\})", re.IGNORECASE | re.DOTALL)
    return list(pattern.finditer(text))


def replace_description_block(text: str, match: re.Match, new_desc: str) -> str:
    prefix, _, suffix = match.groups()
    return text[: match.start()] + prefix + new_desc + suffix + text[match.end() :]


def strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text)


@app.command()
def main(
    category: str = typer.Option(..., "--category", help="Category name (without 'Category:' prefix)"),
    source_lang: str = typer.Option("en", "--source-lang", help="Source language code"),
    targets: List[str] = typer.Option(
        ["en", "es", "fr", "pt", "ru", "zh", "de"], "--target-lang", help="Target language codes (repeatable)"
    ),
    max_depth: int = typer.Option(1, "--max-depth", help="Category recursion depth"),
    apply: bool = typer.Option(False, "--apply", help="Apply edits (default: dry-run)"),
    log_csv: Optional[Path] = typer.Option(None, "--log-csv", help="Optional CSV log of actions"),
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
        level=logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("argostranslate").setLevel(logging.ERROR)
    logging.getLogger("argostranslate.utils").setLevel(logging.ERROR)
    if argostranslate is None:
        raise typer.Exit("argostranslate not installed. Run `pip install argostranslate` first.")
    for tgt in targets:
        ensure_model(source_lang, tgt)

    client = CommonsClient(commons_user, commons_pass)
    uploads = client.list_category_files(category, max_depth=max_depth)
    # Filter JPEGs only
    uploads = [u for u in uploads if u.title.lower().endswith((".jpg", ".jpeg"))]
    progress = tqdm(total=len(uploads), desc="Translating", unit="file", colour="magenta")
    log_rows = []
    updated = 0
    skipped = 0
    errors = 0
    def add_log(title: str, status: str, reason: str, source: str = "", desc: str = ""):
        log_rows.append(
            {
                "title": title,
                "status": status,
                "reason": reason,
                "source": source,
                "desc_raw": desc,
            }
        )
    try:
        for u in uploads:
            try:
                page = client._site.pages[u.title]  # type: ignore
                text = page.text()
                base_desc = None
                lang_map = {}
                target_match = None
                blocks = find_description_blocks(text)
                for m in blocks:
                    block = m.group(2).strip()
                    lang_map = parse_lang_templates(block)
                    if lang_map:
                        base_desc = lang_map.get(source_lang) or next(iter(lang_map.values()))
                        target_match = m
                        break
                    elif block:
                        raw = block
                        if raw.startswith("{{") and raw.endswith("}}"):
                            raw = re.sub(r"^\{\{|\}\}$", "", raw, flags=re.DOTALL).strip()
                            parts = raw.split("|", 1)
                            if len(parts) == 2:
                                raw = parts[1].strip()
                        base_desc = raw
                        target_match = m
                        break
                # capture a sample for logging
                sample_block = blocks[0].group(2).strip() if blocks else text[:200]
                if not base_desc:
                    # fallback to extmetadata or SDC (strip HTML)
                    if u.description:
                        base_desc = strip_html(u.description)
                    else:
                        desc = client.fetch_sdc_description(u.title, source_lang)
                        base_desc = strip_html(desc) if desc else None
                    if base_desc and not target_match and blocks:
                        target_match = blocks[0]
                if not base_desc or not target_match:
                    skipped += 1
                    reason = "no description field, extmetadata, or SDC"
                    progress.write(f"Skipping {u.title}: {reason}")
                    add_log(u.title, "skipped", reason, source="none", desc=sample_block)
                    progress.update(1)
                    continue
                if not lang_map:
                    lang_map = {source_lang: base_desc}
                else:
                    lang_map.setdefault(source_lang, base_desc)
                added = 0
                for tgt in targets:
                    if tgt in lang_map:
                        continue
                    lang_map[tgt] = translate_text(source_lang, tgt, base_desc)
                    added += 1
                if added == 0:
                    skipped += 1
                    reason = "all target languages present"
                    progress.write(f"Skipping {u.title}: {reason}")
                    add_log(u.title, "skipped", reason, source="wikitext/extmeta/SDC", desc=base_desc)
                    progress.update(1)
                    continue
                new_desc = build_multilingual_desc(lang_map)
                new_text = replace_description_block(text, target_match, new_desc)
                if not new_text:
                    skipped += 1
                    reason = "could not rewrite safely"
                    progress.write(f"Skipping {u.title}: {reason}")
                    add_log(u.title, "skipped", reason, source="wikitext/extmeta/SDC", desc=base_desc)
                    progress.update(1)
                    continue
                if apply:
                    page.save(new_text, summary=f"Add machine translation ({','.join(targets)}) to description")
                    updated += 1
                    add_log(u.title, "updated", "", source="wikitext/extmeta/SDC", desc=base_desc)
                else:
                    progress.write(f"Dry-run {u.title}: added {added} languages")
                    updated += 1
                    add_log(u.title, "dry-run", f"added {added}", source="wikitext/extmeta/SDC", desc=base_desc)
            except Exception as exc:
                errors += 1
                progress.write(f"Error on {u.title}: {exc}")
                logging.exception("Error translating %s", u.title)
                add_log(u.title, "error", str(exc), source="", desc="")
            progress.update(1)
    except KeyboardInterrupt:
        progress.write("Interrupted by user.")
    progress.close()
    client.cleanup()
    if log_csv:
        with log_csv.open("w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=["title", "status", "reason", "source", "desc_raw"])
            writer.writeheader()
            for row in log_rows:
                writer.writerow(row)
    print(f"Done. Updated (or previewed): {updated}, skipped: {skipped}, errors: {errors}")


if __name__ == "__main__":
    app()
