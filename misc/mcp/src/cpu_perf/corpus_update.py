"""Keep the list current without a reinstall.

Once a day (across every process sharing the data directory) ask GitHub for
the newest commit of the list. If it is newer than the copy being served,
download that commit's tarball, keep only the list's own files (the same
allowlist the wheel bundles), check that they parse, and point the server at
them. Downloaded files are data: they are parsed, never imported or run."""

from __future__ import annotations

import gzip
import io
import json
import logging
import os
import re
import shutil
import tarfile
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from . import manifest
from .library.crawler import CrawlLock
from .locate import CorpusReader, _utc, downloaded
from .net import Fetcher

log = logging.getLogger("cpu_perf.update")

DEFAULT_UPSTREAM = "usamahz/cpu-performance-engineering"
REPO_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DAY = 86400.0
MAX_TARBALL = 50 * 1024 * 1024
MAX_MEMBER = 5 * 1024 * 1024
MAX_KEPT = 20 * 1024 * 1024
KEEP = 2  # corpora kept on disk: the one served and the one before


class UpdateError(RuntimeError):
    pass


def upstream() -> str:
    repo = os.environ.get("CPU_PERF_UPSTREAM", DEFAULT_UPSTREAM).strip()
    if not REPO_RE.match(repo) or ".." in repo:
        log.warning("CPU_PERF_UPSTREAM %r is not owner/repo; using %s", repo, DEFAULT_UPSTREAM)
        return DEFAULT_UPSTREAM
    return repo


def safe_member_path(name: str) -> str | None:
    """The repository-relative path of a tarball member, or None if it is unsafe or not ours."""
    if "\x00" in name or "\\" in name or name.startswith("/"):
        return None
    parts = name.split("/")
    if len(parts) < 2:
        return None  # the archive's top folder itself
    rel = "/".join(parts[1:])
    if not rel or any(p in ("", ".", "..") for p in rel.split("/")):
        return None
    return rel if manifest.matches(rel) else None


def extract(tarball: bytes, dest: Path) -> tuple[list[str], str | None]:
    """Write the list's files from a GitHub tarball into dest. Returns (files, commit date).

    Only regular files on the allowlist are kept; sizes are checked before
    reading; names that collide by case are refused; links, devices and
    anything outside the archive's folder are skipped."""
    files: list[str] = []
    seen_lower: set[str] = set()
    kept = 0
    newest = 0
    raw = gzip.GzipFile(fileobj=io.BytesIO(tarball))
    with tarfile.open(fileobj=raw, mode="r|") as tar:
        for member in tar:
            rel = safe_member_path(member.name)
            if rel is None or not member.isreg():
                continue
            if member.size > MAX_MEMBER:
                raise UpdateError(f"{rel} is larger than {MAX_MEMBER} bytes")
            if rel.lower() in seen_lower:
                raise UpdateError(f"{rel} collides with another file by case")
            kept += member.size
            if kept > MAX_KEPT:
                raise UpdateError("the list's files are larger than expected")
            fh = tar.extractfile(member)
            if fh is None:
                continue
            data = fh.read(MAX_MEMBER + 1)
            if len(data) > MAX_MEMBER:
                raise UpdateError(f"{rel} is larger than {MAX_MEMBER} bytes")
            target = dest.joinpath(*rel.split("/"))
            if dest.resolve() not in target.resolve().parents:
                raise UpdateError(f"{rel} escapes the corpus folder")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            seen_lower.add(rel.lower())
            files.append(rel)
            newest = max(newest, int(member.mtime or 0))
    date = datetime.fromtimestamp(newest, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if newest else None
    return sorted(files), date


class CorpusUpdater:
    def __init__(
        self,
        data_dir,
        fetcher: Fetcher | None = None,
        *,
        repo: str | None = None,
        branch: str = "main",
        interval: float = DAY,
        api_base: str = "https://api.github.com",
        web_base: str = "https://github.com",
        codeload_base: str = "https://codeload.github.com",
    ):
        self.dir = Path(data_dir) / "corpus"
        self.fetcher = fetcher or Fetcher(per_host_interval=0.0)
        self.repo = repo or upstream()
        self.branch = branch
        self.interval = interval
        self.api_base, self.web_base, self.codeload_base = api_base, web_base, codeload_base
        self.last_error: str | None = None

    # ----- small state files shared by every process ---------------------------------

    def _read(self, name: str) -> dict:
        try:
            return json.loads((self.dir / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _write(self, name: str, data: dict) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.dir / f".{name}.tmp{os.getpid()}"
        tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
        os.replace(tmp, self.dir / name)

    def state(self) -> dict:
        return self._read("state.json")

    def due(self) -> bool:
        return time.time() - float(self.state().get("checked_at", 0)) >= self.interval

    # ----- GitHub ---------------------------------------------------------------------

    def latest_sha(self) -> str:
        st = self.state()
        headers = {"Accept": "application/vnd.github.sha"}
        if st.get("etag"):
            headers["If-None-Match"] = st["etag"]
        res = self.fetcher.fetch(
            f"{self.api_base}/repos/{self.repo}/commits/{self.branch}", headers=headers, max_bytes=4096,
            total_timeout=30, use_robots=False, accept="application/vnd.github.sha",
        )
        if res.status == "not_modified" and st.get("sha"):
            return st["sha"]
        if res.ok and SHA_RE.match(res.body.decode("ascii", "replace").strip()):
            self._write("state.json", {**st, "etag": res.headers.get("etag")})
            return res.body.decode("ascii").strip()
        # the API's hourly limit is shared behind one address: ask git itself instead
        res2 = self.fetcher.fetch(
            f"{self.web_base}/{self.repo}.git/info/refs?service=git-upload-pack", max_bytes=1024 * 1024,
            total_timeout=30, use_robots=False, accept="*/*",
        )
        if res2.ok:
            m = re.search(rb"([0-9a-f]{40}) refs/heads/" + re.escape(self.branch.encode()) + rb"\b", res2.body)
            if m:
                return m.group(1).decode()
        raise UpdateError(f"could not read the newest commit ({res.status} {res.http_status}; {res2.status} {res2.http_status})")

    def download(self, sha: str) -> tuple[Path, dict]:
        if not SHA_RE.match(sha):
            raise UpdateError(f"not a commit id: {sha!r}")
        final = self.dir / sha
        info_path = final / "_build_info.json"
        if info_path.is_file():
            return final, json.loads(info_path.read_text(encoding="utf-8"))
        res = self.fetcher.fetch(
            f"{self.codeload_base}/{self.repo}/tar.gz/{sha}", max_bytes=MAX_TARBALL, total_timeout=180,
            use_robots=False, accept="application/x-gzip,application/gzip,*/*",
        )
        if not res.ok:
            raise UpdateError(f"download failed: {res.status} {res.http_status} {res.detail}")
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = Path(tempfile.mkdtemp(prefix=".incoming-", dir=self.dir))
        try:
            files, date = extract(res.body, tmp)
            if "README.md" not in files:
                raise UpdateError("the download has no README.md")
            info = {
                "commit": sha,
                "commit_date": date,
                "downloaded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "files": files,
                "source": f"{self.codeload_base}/{self.repo}/tar.gz/{sha}",
            }
            (tmp / "_build_info.json").write_text(json.dumps(info, indent=1), encoding="utf-8")
            if final.exists():
                shutil.rmtree(tmp, ignore_errors=True)
            else:
                os.replace(tmp, final)
        except BaseException:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        return final, info

    # ----- the daily step ----------------------------------------------------------------

    def newer_than(self, reader: CorpusReader) -> CorpusReader | None:
        """A downloaded copy newer than the one being served, if there is one."""
        if reader.source in ("checkout", "explicit"):
            return None
        fetched = downloaded(self.dir.parent)
        if fetched is None or fetched.commit == reader.commit:
            return None
        return fetched if fetched.date_key > reader.date_key else None

    def run(self, serving: CorpusReader, validate=None) -> CorpusReader | None:
        """Check (if due) and download (if newer). Returns a newer copy to serve, or None.

        `validate(reader)` must raise if the copy does not parse into a sane
        list; the copy is then kept off and the error remembered."""
        if serving.source in ("checkout", "explicit"):
            return None
        ready = self.newer_than(serving)
        if ready is not None:
            return ready  # another process already fetched it
        if not self.due():
            return None
        lock = CrawlLock(self.dir / "update.lock")
        if not lock.acquire():
            return None
        try:
            if not self.due():
                return self.newer_than(serving)
            st = self.state()
            try:
                sha = self.latest_sha()
            except UpdateError as exc:
                self.last_error = str(exc)
                self._write("state.json", {**st, "checked_at": time.time(), "error": self.last_error})
                return None
            self._write("state.json", {**self.state(), "checked_at": time.time(), "sha": sha, "error": None})
            if sha == serving.commit or sha == st.get("rejected"):
                return None
            path, info = self.download(sha)
            candidate = downloaded_from(path, info)
            if _utc(info.get("commit_date")) <= serving.date_key:
                return None  # the copy being served (a newer wheel) is not older
            if validate is not None:
                try:
                    validate(candidate)
                except Exception as exc:  # keep the list being served
                    self.last_error = f"commit {sha[:12]} did not parse: {exc}; upgrade the server"
                    self._write("state.json", {**self.state(), "rejected": sha, "error": self.last_error})
                    log.warning("%s", self.last_error)
                    return None
            self._write("current.json", {"sha": sha, "commit_date": info.get("commit_date")})
            self._prune(keep={sha, serving.commit or ""})
            return candidate
        except UpdateError as exc:
            self.last_error = str(exc)
            self._write("state.json", {**self.state(), "error": self.last_error})
            log.warning("list update failed: %s", exc)
            return None
        finally:
            lock.release()

    def _prune(self, keep: set[str]) -> None:
        dirs = sorted(
            (p for p in self.dir.iterdir() if p.is_dir() and SHA_RE.match(p.name)), key=lambda p: p.stat().st_mtime, reverse=True
        )
        for p in dirs[KEEP:]:
            if p.name not in keep:
                shutil.rmtree(p, ignore_errors=True)


def downloaded_from(path: Path, info: dict) -> CorpusReader:
    return CorpusReader(
        source="downloaded", root=path, files=sorted(info["files"]), commit=info.get("commit"),
        built_at=info.get("downloaded_at"), commit_date=info.get("commit_date"),
    )
