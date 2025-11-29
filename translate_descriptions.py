from __future__ import annotations

import logging
import re
import csv
from pathlib import Path
from typing import List, Optional, Dict
import mwclient
import os
from pathlib import Path
import typer
from tqdm import tqdm

try:
    import argostranslate.package  # type: ignore
    import argostranslate.translate  # type: ignore
except ImportError:
    argostranslate = None  # type: ignore

from commons_client import CommonsClient

app = typer.Typer(add_completion=False)


def load_local_env():
    """Populate os.environ from a .env file if present (non-intrusive)."""
    env_path = Path(".env")
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        os.environ.setdefault(key, val)


def ensure_model(src: str, dest: str):
    if argostranslate is None:
        raise RuntimeError("argostranslate not installed. Install via `pip install argostranslate`.")
    available_packages = argostranslate.package.get_available_packages()
    installed_languages = argostranslate.translate.get_installed_languages()
    # install if the specific pair is missing
    has_pair = False
    to_lang = next((l for l in installed_languages if l.code == dest), None)
    for lang in installed_languages:
        if lang.code == src and to_lang and lang.get_translation(to_lang):
            has_pair = True
            break
    if not has_pair:
        for pkg in available_packages:
            if pkg.from_code == src and pkg.to_code == dest:
                argostranslate.package.install_from_path(pkg.download())
                break
        argostranslate.translate.load_installed_languages()
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
    # Some installs return None instead of raising when the model is missing.
    if translator is None or not hasattr(translator, "translate"):
        raise RuntimeError(f"Missing translation model {src_lang}->{dest_lang}")
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


def parse_multilingual_block(block: str) -> Dict[str, str]:
    """Parse Multilingual description|en=...|es=... into a lang map."""
    blk = block.strip()
    # strip braces if present
    if blk.startswith("{{") and blk.endswith("}}"):
        blk = blk[2:-2].strip()
    if not blk.lower().startswith("multilingual description"):
        return {}
    parts = blk.split("|")[1:]  # drop template name
    langs = {}
    for p in parts:
        if "=" not in p:
            continue
        k, v = p.split("=", 1)
        k = k.strip().lower()
        v = v.strip()
        if k and v:
            langs[k] = v
    return langs


def replace_description_block(text: str, match: re.Match, new_desc: str) -> str:
    prefix, _, suffix = match.groups()
    return text[: match.start()] + prefix + new_desc + suffix + text[match.end() :]


def strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text)


@app.command()
def main(
    category: str = typer.Option(..., "--category", help="Category name (without 'Category:' prefix)"),
    apply: bool = typer.Option(False, "--apply", help="Apply edits (default: dry-run)"),
    log_csv: Optional[Path] = typer.Option(None, "--log-csv", help="Optional CSV log of actions"),
    max_edits: Optional[int] = typer.Option(None, "--max-edits", help="Stop after this many updates; process all if omitted"),
):
    """Translate descriptions for files in a category and optionally update wikitext.

    Uses first language found in the description as source; targets are fixed: es, fr, pt, ru, zh, de.
    Credentials are read from COMMONS_USER / COMMONS_PASS env vars.
    """
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("argostranslate").setLevel(logging.ERROR)
    logging.getLogger("argostranslate.utils").setLevel(logging.ERROR)
    targets = ["es", "fr", "pt", "ru", "zh", "de"]
    default_source_lang = os.getenv("DEFAULT_SOURCE_LANG", "en")
    if argostranslate is None:
        raise typer.Exit("argostranslate not installed. Run `pip install argostranslate` first.")

    # Pull credentials from .env if present (without overriding already-set env vars)
    load_local_env()
    commons_user = os.getenv("COMMONS_USER")
    commons_pass = os.getenv("COMMONS_PASS")
    if not commons_user or not commons_pass:
        raise typer.Exit("COMMONS_USER and COMMONS_PASS must be set in env.")

    client = CommonsClient(commons_user, commons_pass)
    uploads = client.list_category_files(category, max_depth=1)
    # Filter JPEGs only
    uploads = [u for u in uploads if u.title.lower().endswith((".jpg", ".jpeg"))]
    progress = tqdm(total=len(uploads), desc="Translating", unit="file", colour="magenta")
    updated = 0
    skipped = 0
    errors = 0
    log_rows = []
    stop_early = False
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
        if log_csv:
            # append incrementally
            exists = log_csv.exists()
            with log_csv.open("a", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=["title", "status", "reason", "source", "desc_raw"])
                if not exists:
                    writer.writeheader()
                writer.writerow(log_rows[-1])
    try:
        for u in uploads:
            try:
                full_title = u.title if u.title.startswith("File:") else f"File:{u.title}"
                page = client._site.pages[full_title]  # type: ignore
                text = client.fetch_wikitext(u.title) or page.text()
                base_desc = None
                lang_map = {}
                target_match = None
                source_lang = None
                blocks = find_description_blocks(text)
                for m in blocks:
                    block = m.group(2).strip()
                    lang_map = parse_multilingual_block(block)
                    if not lang_map:
                        # If it looks like a multilingual block but we can't parse, skip to avoid corruption
                        if "multilingual description" in block.lower():
                            lang_map = {}
                            break
                        lang_map = parse_lang_templates(block)
                    if lang_map:
                        source_lang = next(iter(lang_map.keys()))
                        base_desc = lang_map.get(source_lang) or next(iter(lang_map.values()))
                        target_match = m
                        break
                    elif "multilingual description" in block.lower():
                        # malformed multilingual block — do not touch
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
                sample_block = blocks[0].group(2).strip() if blocks else text[:2000]
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
                    add_log(u.title, "skipped", reason, source="none", desc=text[:2000])
                    progress.update(1)
                    continue
                if lang_map:
                    source_lang = next(iter(lang_map.keys()))
                else:
                    source_lang = default_source_lang if base_desc else None
                if not source_lang:
                    skipped += 1
                    reason = "no source language detected"
                    progress.write(f"Skipping {u.title}: {reason}")
                    add_log(u.title, "skipped", reason, source="none", desc=text[:2000])
                    progress.update(1)
                    continue
                # Avoid rewriting formatted / multiline descriptions (keep safe)
                if base_desc and base_desc.count("\n") > 1:
                    skipped += 1
                    reason = "multiline description, skipped for safety"
                    progress.write(f"Skipping {u.title}: {reason}")
                    add_log(u.title, "skipped", reason, source="wikitext/extmeta/SDC", desc=base_desc)
                    progress.update(1)
                    continue
                # If all targets already exist, skip
                if all(t in lang_map for t in targets):
                    skipped += 1
                    reason = "all target languages present"
                    progress.write(f"Skipping {u.title}: {reason}")
                    add_log(u.title, "skipped", reason, source="wikitext/extmeta/SDC", desc=base_desc or "")
                    progress.update(1)
                    continue
                lang_map.setdefault(source_lang, base_desc)
                added = 0
                for tgt in targets:
                    if tgt == source_lang or tgt in lang_map:
                        continue
                    try:
                        lang_map[tgt] = translate_text(source_lang, tgt, base_desc)
                        added += 1
                    except RuntimeError as e:
                        skipped += 1
                        reason = f"missing model {source_lang}->{tgt}"
                        progress.write(f"Skipping {u.title}: {reason}")
                        add_log(u.title, "skipped", reason, source="wikitext/extmeta/SDC", desc=base_desc)
                        progress.update(1)
                        break
                else:
                    pass  # only executed if loop not broken
                if added == 0:
                    continue
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
                    try:
                        page.save(new_text, summary=f"Add machine translation ({','.join(targets)}) to description")
                        updated += 1
                        add_log(u.title, "updated", "", source="wikitext/extmeta/SDC", desc=base_desc)
                    except mwclient.errors.APIError as e:
                        if e.args and e.args[0] == "abusefilter-warning":
                            skipped += 1
                            reason = f"abusefilter: {e.args[1]}"
                            progress.write(f"Skipping {u.title}: {reason}")
                            add_log(u.title, "skipped", reason, source="wikitext/extmeta/SDC", desc=base_desc)
                            progress.update(1)
                            continue
                        else:
                            raise
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
            if max_edits is not None and updated >= max_edits:
                progress.write(f"Reached max-edits={max_edits}; stopping early.")
                stop_early = True
                break
        if stop_early:
            pass
    except KeyboardInterrupt:
        progress.write("Interrupted by user.")
    progress.close()
    client.cleanup()
    print(f"Done. Updated (or previewed): {updated}, skipped: {skipped}, errors: {errors}")


if __name__ == "__main__":
    app()
