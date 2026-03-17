from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import urllib.request
from dataclasses import dataclass
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import urljoin


PAGE_URL = "https://bip.uke.gov.pl/jak-uzyskac-rezerwacje--pozwolenie--zezwolenie-tresc/linie-radiowe,19.html"

LINK_RE = re.compile(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)
TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")
MODIFIED_RE = re.compile(r"Data ostatniej modyfikacji:\s*([0-9]{2}\.[0-9]{2}\.[0-9]{4}\s+[0-9]{2}:[0-9]{2})")


@dataclass(frozen=True)
class PublicationArtifact:
    kind: str
    label: str
    url: str
    filename: str


class MissingRarExtractorError(RuntimeError):
    pass


def _clean_label(value: str) -> str:
    text = TAG_RE.sub(" ", unescape(value))
    text = SPACE_RE.sub(" ", text).strip()
    return text


def fetch_page(url: str = PAGE_URL) -> str:
    with urllib.request.urlopen(url) as response:
        return response.read().decode("utf-8", errors="ignore")


def parse_publications(html: str, page_url: str = PAGE_URL) -> dict[str, Any]:
    artifacts: list[PublicationArtifact] = []
    for href, raw_label in LINK_RE.findall(html):
        label = _clean_label(raw_label)
        if not label:
            continue
        lower = label.lower()
        if "plik rar" not in lower:
            continue
        if "lr konsultacja" in lower:
            kind = "lr_konsultacja"
        elif "plany aranzacji kanalow" in lower:
            kind = "plany"
        else:
            continue
        url = urljoin(page_url, unescape(href))
        filename = Path(url).name
        artifacts.append(PublicationArtifact(kind=kind, label=label, url=url, filename=filename))

    plain_text = _clean_label(html)
    modified_match = MODIFIED_RE.search(plain_text)
    return {
        "page_url": page_url,
        "page_modified_at": modified_match.group(1) if modified_match else None,
        "artifacts": [
            {
                "kind": artifact.kind,
                "label": artifact.label,
                "url": artifact.url,
                "filename": artifact.filename,
            }
            for artifact in artifacts
        ],
    }


def download_file(url: str, dest_path: Path) -> None:
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url) as response, dest_path.open("wb") as fh:
        shutil.copyfileobj(response, fh)


def find_rar_extractor() -> tuple[str, list[str]]:
    candidates: list[tuple[str, list[str]]] = [
        ("unar", ["unar", "-force-overwrite"]),
        ("7z", ["7z", "x", "-y"]),
        ("unrar", ["unrar", "x", "-o+"]),
        ("bsdtar", ["bsdtar", "-xf"]),
    ]
    for tool_name, command in candidates:
        if shutil.which(tool_name):
            return tool_name, command
    raise MissingRarExtractorError(
        "Nie znaleziono ekstraktora RAR. "
        "Zainstaluj jedno z narzędzi: `unar`, `7z`, `unrar` albo `bsdtar`.\n"
        "Ubuntu/Debian: `sudo apt install unar` albo `sudo apt install p7zip-full`"
    )


def extract_rar(archive_path: Path, dest_dir: Path) -> None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    tool_name, base_command = find_rar_extractor()

    if tool_name == "unar":
        command = [*base_command, "-output-directory", str(dest_dir), str(archive_path)]
    elif tool_name == "7z":
        command = [*base_command, f"-o{dest_dir}", str(archive_path)]
    elif tool_name == "unrar":
        command = [*base_command, str(archive_path), str(dest_dir)]
    elif tool_name == "bsdtar":
        command = [*base_command, str(archive_path), "-C", str(dest_dir)]
    else:
        raise RuntimeError(f"Nieobsługiwany ekstraktor RAR: {tool_name}")

    try:
        subprocess.run(
            command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
    except FileNotFoundError as exc:
        raise MissingRarExtractorError(
            "Nie znaleziono ekstraktora RAR podczas rozpakowywania. "
            "Zainstaluj `unar`, `7z`, `unrar` albo `bsdtar`."
        ) from exc
    except subprocess.CalledProcessError as exc:
        output = exc.stdout.decode("utf-8", errors="ignore") if isinstance(exc.stdout, bytes) else str(exc.stdout or "")
        raise RuntimeError(
            f"Nie udało się rozpakować archiwum RAR przy użyciu `{tool_name}`.\n{output.strip()}"
        ) from exc


def locate_mdb_files(extract_dir: Path) -> dict[str, str]:
    files = sorted(extract_dir.rglob("*.mdb"))
    result: dict[str, str] = {}
    for path in files:
        name = path.name.lower()
        if name.startswith("lr_konsultacja") and "lr_konsultacja" not in result:
            result["lr_konsultacja"] = str(path.resolve())
        elif name == "db1.mdb" and "db1" not in result:
            result["db1"] = str(path.resolve())
        elif name == "db2.mdb" and "db2" not in result:
            result["db2"] = str(path.resolve())
    return result


def current_artifact(artifacts: list[dict[str, Any]], kind: str) -> dict[str, Any] | None:
    matches = [artifact for artifact in artifacts if artifact["kind"] == kind]
    if not matches:
        return None
    return matches[0]


def main() -> None:
    parser = argparse.ArgumentParser(description="Sprawdza publikację UKE, pobiera najnowsze archiwum LR konsultacja i rozpakowuje MDB.")
    parser.add_argument("--page-url", default=PAGE_URL)
    parser.add_argument("--download-dir", default="data/uke_source/downloads")
    parser.add_argument("--extract-dir", default="data/uke_source/extracted")
    parser.add_argument("--state-file", default="data/uke_source/state.json")
    parser.add_argument("--force-download", action="store_true")
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--skip-plany", action="store_true")
    parser.add_argument("--out")
    args = parser.parse_args()

    download_dir = Path(args.download_dir).resolve()
    extract_root = Path(args.extract_dir).resolve()
    state_file = Path(args.state_file).resolve()
    state_file.parent.mkdir(parents=True, exist_ok=True)

    html = fetch_page(args.page_url)
    parsed = parse_publications(html, args.page_url)
    artifacts = parsed["artifacts"]
    lr_artifact = current_artifact(artifacts, "lr_konsultacja")
    plan_artifact = current_artifact(artifacts, "plany")
    if not lr_artifact:
        raise SystemExit("Nie znaleziono publikacji `lr konsultacja` na stronie UKE.")

    current_state: dict[str, Any] = {}
    if state_file.exists():
        current_state = json.loads(state_file.read_text(encoding="utf-8"))

    changed = args.force_download or (
        current_state.get("lr_konsultacja_url") != lr_artifact["url"]
        or current_state.get("page_modified_at") != parsed["page_modified_at"]
    )
    archive_path = download_dir / lr_artifact["filename"]
    extract_dir = extract_root / archive_path.stem
    plan_archive_path = download_dir / plan_artifact["filename"] if plan_artifact else None
    plan_extract_dir = extract_root / plan_archive_path.stem if plan_archive_path else None
    existing_mdb_files = locate_mdb_files(extract_dir) if extract_dir.exists() else {}
    missing_extract = not existing_mdb_files or not {"lr_konsultacja", "db1", "db2"}.issubset(existing_mdb_files)
    should_materialize = changed or not archive_path.exists() or missing_extract
    should_materialize_plany = bool(
        plan_artifact
        and not args.skip_plany
        and (
            args.force_download
            or current_state.get("plany_url") != plan_artifact["url"]
            or current_state.get("page_modified_at") != parsed["page_modified_at"]
            or not plan_archive_path.exists()
            or not plan_extract_dir.exists()
        )
    )

    plan_error: str | None = None

    if args.check_only:
        payload = {
            "page_url": parsed["page_url"],
            "page_modified_at": parsed["page_modified_at"],
            "lr_konsultacja": lr_artifact,
            "plany": plan_artifact,
            "changed": changed,
            "known_url": current_state.get("lr_konsultacja_url"),
            "known_page_modified_at": current_state.get("page_modified_at"),
        }
    else:
        if should_materialize:
            download_file(lr_artifact["url"], archive_path)
            if extract_dir.exists():
                shutil.rmtree(extract_dir)
            extract_rar(archive_path, extract_dir)
        mdb_files = locate_mdb_files(extract_dir)
        if should_materialize_plany and plan_artifact and plan_archive_path and plan_extract_dir:
            try:
                download_file(plan_artifact["url"], plan_archive_path)
                if plan_extract_dir.exists():
                    shutil.rmtree(plan_extract_dir)
                extract_rar(plan_archive_path, plan_extract_dir)
            except subprocess.CalledProcessError as exc:
                output = exc.stdout.decode("utf-8", errors="ignore") if isinstance(exc.stdout, bytes) else str(exc.stdout or "")
                plan_error = output.strip() or str(exc)
        payload = {
            "page_url": parsed["page_url"],
            "page_modified_at": parsed["page_modified_at"],
            "lr_konsultacja": lr_artifact,
            "plany": plan_artifact,
            "changed": changed,
            "materialized": should_materialize,
            "archive_path": str(archive_path),
            "extract_dir": str(extract_dir),
            "mdb_files": mdb_files,
            "plany_archive_path": str(plan_archive_path) if plan_archive_path else None,
            "plany_extract_dir": str(plan_extract_dir) if plan_extract_dir else None,
            "plany_materialized": should_materialize_plany,
            "plany_error": plan_error,
        }
        state_file.write_text(
            json.dumps(
                {
                    "page_url": parsed["page_url"],
                    "page_modified_at": parsed["page_modified_at"],
                    "lr_konsultacja_url": lr_artifact["url"],
                    "lr_konsultacja_label": lr_artifact["label"],
                    "archive_path": str(archive_path),
                    "extract_dir": str(extract_dir),
                    "mdb_files": mdb_files,
                    "plany_url": plan_artifact["url"] if plan_artifact else None,
                    "plany_label": plan_artifact["label"] if plan_artifact else None,
                    "plany_archive_path": str(plan_archive_path) if plan_archive_path else None,
                    "plany_extract_dir": str(plan_extract_dir) if plan_extract_dir else None,
                    "plany_error": plan_error,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text + "\n")


if __name__ == "__main__":
    try:
        main()
    except MissingRarExtractorError as exc:
        sys.stderr.write(str(exc) + "\n")
        raise SystemExit(2)
