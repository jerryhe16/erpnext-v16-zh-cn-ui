"""Apply reviewed Simplified Chinese strings and optional desktop SVGs to Frappe v16."""

import argparse
import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re


def translations(path):
    entries = {}
    with path.open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            source, text = row["source_text"], row["translated_text"]
            key = (source, row["context"])
            placeholders = r"\{\d*\}"
            if not source or not text or key in entries:
                raise ValueError(f"Missing or duplicate translation: {key!r}")
            if sorted(re.findall(placeholders, source)) != sorted(re.findall(placeholders, text)):
                raise ValueError(f"Placeholder mismatch: {key!r}")
            entries[key] = text
    return entries


def translation_changes(requested, existing):
    additions = {key: value for key, value in requested.items() if key not in existing}
    conflicts = [key for key, value in requested.items() if key in existing and existing[key] != value]
    return additions, conflicts


def icons(root):
    entries = json.loads((root / "icons.json").read_text(encoding="utf-8"))
    for entry in entries.values():
        name = entry["file"]
        if not re.fullmatch(r"[a-z-]+\.svg", name) or not (root / "icons" / name).is_file():
            raise ValueError(f"Invalid icon asset: {name!r}")
    return entries


def run(frappe, site_path, package, with_icons, apply):
    from frappe.desk.doctype.desktop_icon.desktop_icon import clear_every_users_desktop_icons

    proposed = translations(package / "translations.csv")
    rows = frappe.get_all(
        "Translation",
        filters={"language": "zh", "source_text": ("in", sorted({key[0] for key in proposed}))},
        fields=["source_text", "context", "translated_text"],
    )
    current = {}
    for row in rows:
        key = (row.source_text, row.context or "")
        if key in proposed and key in current and current[key] != row.translated_text:
            raise ValueError(f"Conflicting site translations already exist: {key!r}")
        current[key] = row.translated_text
    additions, conflicts = translation_changes(proposed, current)

    directory = site_path / "public" / "files" / "desk-ui-v1"
    changes, missing, assets = [], [], {}
    if with_icons:
        for name, entry in icons(package).items():
            old = frappe.db.get_value(
                "Desktop Icon", name, ["name", "icon_type", "app", "logo_url"], as_dict=True
            )
            if not old or old.icon_type != "Link":
                missing.append(name)
                continue
            filename = entry["file"]
            url = f"/files/{directory.name}/{filename}"
            path = directory / filename
            content = (package / "icons" / filename).read_bytes()
            if path.exists() and (path.is_symlink() or path.read_bytes() != content):
                raise ValueError(f"Icon asset conflicts with an existing file: {filename}")
            assets[path] = content
            if old.logo_url != url or old.app:
                changes.append((dict(old), url))
    plan = {
        "insert_zh": len(additions), "preserved_conflicts": conflicts,
        "icon_updates": len(changes), "skipped_icons": missing,
        "new_assets": sum(not path.exists() for path in assets),
    }
    if not apply or not (additions or changes or plan["new_assets"]):
        return plan

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = site_path / "private" / "backups" / f"{timestamp}-zh-ui-before.json"
    backup.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump({"translation_keys_added": list(additions), "icons_before": [old for old, _ in changes],
                   "new_assets": [str(path.relative_to(site_path)) for path in assets if not path.exists()]},
                  stream, ensure_ascii=False, indent=2)

    written = []
    try:
        if assets:
            directory.mkdir(parents=True, exist_ok=True)
            if directory.is_symlink():
                raise ValueError("Icon directory must be local to the site")
        for path, content in assets.items():
            if not path.exists():
                with path.open("xb") as stream:
                    written.append(path)
                    stream.write(content)
        for (source, context), text in additions.items():
            frappe.get_doc({"doctype": "Translation", "language": "zh", "source_text": source,
                            "context": context, "translated_text": text}).insert()
        for old, url in changes:
            # An empty app makes Frappe use the explicit logo instead of its built-in SVG.
            # A Link icon still resolves route and permissions from its linked workspace.
            frappe.db.set_value("Desktop Icon", old["name"], {"app": None, "logo_url": url})
        frappe.db.commit()
    except BaseException:
        frappe.db.rollback()
        for path in written:
            path.unlink(missing_ok=True)
        raise
    clear_every_users_desktop_icons()
    frappe.clear_cache()
    plan["backup"] = backup.name
    return plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", required=True)
    parser.add_argument("--bench", type=Path, default=Path.cwd())
    parser.add_argument("--icons", action="store_true", help="Update existing matching Link icons")
    parser.add_argument("--apply", action="store_true", help="Apply the changes. Default is a preview.")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]*", args.site):
        parser.error("Invalid site name")

    import frappe

    package = Path(__file__).resolve().parent
    sites = args.bench.resolve() / "sites"
    site_path = sites / args.site
    os.chdir(sites)
    frappe.init(site=args.site, sites_path=str(sites))
    frappe.connect()
    try:
        if not frappe.__version__.startswith("16.") or not frappe.db.exists("Language", "zh"):
            parser.error("The package requires Frappe v16 and Simplified Chinese (zh)")
        frappe.set_user("Administrator")
        print(json.dumps(run(frappe, site_path, package, args.icons, args.apply),
                         ensure_ascii=False, indent=2))
    finally:
        frappe.destroy()


if __name__ == "__main__":
    main()
