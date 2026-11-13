"""The check of a catalogue's list.

    check.py NEW [--old OLD] [--holds FOLDER]

NEW is the list. OLD is the list as it was before the change, and FOLDER
is the list's own repository. The list's repository runs this on every
change to the list.

It prints ok and ends with 0 when nothing is refused. At the first rule
the list breaks it prints one line, which starts with a code of CODES and
names the line of the list, and ends with 1. It ends with 2 when it is
used wrongly. README.md says each rule in plain words.

It needs git as a command, and the Iris SDK to import: the validator's
verdict on a package is the SDK's, and so is its digest.
"""
import argparse
import contextlib
import gzip
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile

from iris_sdk_dev import definition
from iris_sdk_dev import folder as package_folder
from iris_sdk_dev import strictjson

# Every code the check gives, in the order it looks. The list is closed.
CODES = (
    "bad-list",
    "bad-line",
    "address-twice",
    "holds-a-package",
    "not-found",
    "refused",
    "digest-differs",
    "id-twice",
    "another-package",
    "not-higher",
)

FORMAT = 1
NAMES = ("repository", "folder", "commit", "digest")

_MAX_BYTES = 4 * 1024 * 1024
# The list, its lines and one line: nothing nests deeper.
_MAX_DEPTH = 3

_COMMIT = re.compile(r"[0-9a-f]{40}")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_FOLDER_PART = re.compile(r"[A-Za-z0-9._-]{1,100}")
# One spelling for one repository, so that equal addresses are equal text.
_ELSEWHERE = re.compile(r"https://[a-z0-9.-]+(/[a-z0-9._-]+)+")


class Refusal(Exception):
    """One rule the list breaks: the code, the place and a sentence."""

    def __init__(self, code, where, words):
        assert code in CODES
        Exception.__init__(self, code, where, words)
        self.code, self.where, self.words = code, where, words

    def line(self):
        place = " at " + self.where if self.where else ""
        return "%s%s: %s" % (self.code, place, self.words)


class NotFound(Exception):
    """A repository, a commit or a folder that can't be taken."""


def _where(index=None, old=False):
    """The place a refusal names: a line, counted from 1."""
    if index is None:
        return "the old list" if old else ""
    return ("the old list's line %d" if old else "line %d") % (index + 1)


# The list.


def _is_repository(text):
    """Whether text is a repository's address in the one form the list
    takes: a path on this machine from its top, or an https address in
    lowercase without .git at its end."""
    if text.startswith("/"):
        return not text.startswith("//") and text != "/" and os.path.normpath(text) == text
    if _ELSEWHERE.fullmatch(text) is None or text.endswith(".git"):
        return False
    return not any(part in (".", "..") for part in text.split("/"))


def _is_folder(text):
    """Whether text is a folder in a repository: nothing for the top, or
    parts with / between them."""
    if text == "":
        return True
    parts = text.split("/")
    return all(_FOLDER_PART.fullmatch(part) and part not in (".", "..") for part in parts)


_FORMS = (
    ("repository", _is_repository, "A repository is a path from this machine's top, or an https address in lowercase."),
    ("folder", _is_folder, "A folder is a path inside the repository, or nothing for the repository's top."),
    ("commit", lambda text: _COMMIT.fullmatch(text) is not None, "A commit is 40 lowercase hex digits."),
    ("digest", lambda text: _DIGEST.fullmatch(text) is not None, "A digest is sha256: and 64 lowercase hex digits."),
)


def read(path, old=False):
    """The lines of the list in a file, each a dict of NAMES.

    Refuses a list that isn't in the format, a line that isn't in its
    form, and two lines with one address.
    """
    with open(path, "rb") as held:
        data = held.read(_MAX_BYTES + 1)
    doc, refused = strictjson.parse(data, _MAX_BYTES, _MAX_DEPTH)
    if refused:
        place = " at " + refused[1] if refused[1] else ""
        raise Refusal("bad-list", _where(old=old), "The list isn't strict JSON: %s%s." % (refused[0], place))
    if type(doc) is not dict or set(doc) != {"format", "packages"}:
        raise Refusal("bad-list", _where(old=old), "A list holds format and packages, and no other name.")
    if type(doc["format"]) is not int or doc["format"] != FORMAT:
        raise Refusal("bad-list", _where(old=old), "This check reads format %d alone." % FORMAT)
    if type(doc["packages"]) is not list:
        raise Refusal("bad-list", _where(old=old), "packages is a list of lines.")
    lines = doc["packages"]
    for index, line in enumerate(lines):
        if type(line) is not dict or set(line) != set(NAMES) or any(type(line[name]) is not str for name in NAMES):
            words = "A line holds %s, each a string, and no other name." % ", ".join(NAMES)
            raise Refusal("bad-list", _where(index, old), words)
    for index, line in enumerate(lines):
        for name, fits, words in _FORMS:
            if not fits(line[name]):
                raise Refusal("bad-line", _where(index, old), words)
    seen = {}
    for index, line in enumerate(lines):
        address = (line["repository"], line["folder"])
        if address in seen:
            words = "Line %d names the same repository and folder." % (seen[address] + 1)
            raise Refusal("address-twice", _where(index, old), words)
        seen[address] = index
    return lines


# A package's folder at one commit.


def _environment(ceiling=None):
    """What git runs with. No setting of the machine or of the person is
    read, and git never asks for anything; nothing but https is spoken."""
    env = dict((name, value) for name, value in os.environ.items() if not name.startswith("GIT_"))
    env.update(
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_CONFIG_NOSYSTEM="1",
        GIT_TERMINAL_PROMPT="0",
        GIT_ALLOW_PROTOCOL="https",
    )
    if ceiling:
        # git looks no higher for a repository than the path it was given.
        env["GIT_CEILING_DIRECTORIES"] = ceiling
    return env


def _git(repository, env, *args):
    return subprocess.run(["git", "-C", repository] + list(args), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def _fetched(address, commit, into):
    """Fetches one commit of a repository elsewhere, and nothing before
    it, into a new bare repository."""
    env = _environment(os.path.dirname(into))
    os.mkdir(into)
    made = _git(into, env, "init", "--quiet", "--bare")
    if made.returncode == 0:
        made = _git(into, env, "fetch", "--quiet", "--depth=1", "--no-tags", "--no-recurse-submodules", "--", address, commit)
    if made.returncode != 0:
        raise NotFound("The repository doesn't answer with the commit.")


def _listed(repository, env, folder, commit):
    """Every entry of a folder at a commit, as (mode, object, path): the
    folders too, so that the validator sees what a folder on disk holds."""
    if not os.path.isdir(repository):
        raise NotFound("No repository is at this path.")
    kind = _git(repository, env, "cat-file", "-t", commit)
    if kind.returncode != 0 or kind.stdout.strip() != b"commit":
        raise NotFound("The repository doesn't hold the commit.")
    tree = _git(repository, env, "ls-tree", "-r", "-t", "-z", "%s:%s" % (commit, folder))
    if tree.returncode != 0:
        raise NotFound("The commit doesn't hold the folder.")
    entries = []
    for record in tree.stdout.split(b"\0"):
        if record:
            about, path = record.split(b"\t", 1)
            mode, _, name = about.split(b" ")
            entries.append((mode, name, path))
    return entries


def _packed(repository, env, entries, out):
    """Writes the entries as one packed file, which the validator reads as
    it reads a folder (READING.md section 4).

    Each file's content is the bytes the commit holds. An archive made by
    git isn't used, because it leaves out and rewrites files as the
    repository's own attributes say (export-ignore, eol), and a package is
    every file of its folder as committed.
    """
    reading = subprocess.Popen(
        ["git", "-C", repository, "cat-file", "--batch"], env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE
    )
    with reading as contents, open(out, "wb") as held:
        with gzip.GzipFile(filename="", mode="wb", compresslevel=1, fileobj=held, mtime=0) as zipped:
            # The GNU form writes a path's bytes as they are.
            with tarfile.open(
                fileobj=zipped, mode="w", format=tarfile.GNU_FORMAT, encoding="utf-8", errors="surrogateescape"
            ) as archive:
                for mode, name, path in entries:
                    member = tarfile.TarInfo(path.decode("utf-8", "surrogateescape"))
                    member.mtime = 0
                    member.uid = member.gid = 0
                    member.uname = member.gname = ""
                    if mode.startswith(b"100"):
                        contents.stdin.write(name + b"\n")
                        contents.stdin.flush()
                        answer = contents.stdout.readline().split()
                        if len(answer) != 3 or answer[1] != b"blob":
                            raise NotFound("The repository doesn't hold a file of the folder.")
                        member.size = int(answer[2])
                        member.mode = 0o644
                        archive.addfile(member, contents.stdout)
                        contents.stdout.read(1)
                    elif mode == b"120000":
                        # A link, which the validator refuses whatever it names.
                        member.type = tarfile.SYMTYPE
                        member.linkname = "link"
                        archive.addfile(member)
                    else:
                        # A folder. Another repository pinned inside this one
                        # is a folder too, and an empty one: its files aren't
                        # in this commit.
                        member.type = tarfile.DIRTYPE
                        member.mode = 0o755
                        archive.addfile(member)


@contextlib.contextmanager
def taken(repository, folder, commit):
    """A package as its folder at one commit: the path of a packed file,
    for the validator's take, which is gone when the block ends.

    Nothing is checked out. A repository on this machine is read where it
    is, and any other is fetched first, that one commit alone. The package
    is never unpacked onto this machine's disk, so the validator also sees
    what a disk can't hold apart, such as two paths that differ in capital
    letters alone. NotFound says what can't be taken.
    """
    scratch = tempfile.mkdtemp(prefix="iris-list-check-")
    try:
        if repository.startswith("/"):
            source = repository
        else:
            source = os.path.join(scratch, "fetched")
            _fetched(repository, commit, source)
        env = _environment(os.path.dirname(source))
        out = os.path.join(scratch, "package")
        _packed(source, env, _listed(source, env, folder, commit), out)
        yield out
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


# The rules.


def _package(line, where):
    """The validator's verdict on a line's package, which it accepts."""
    try:
        with taken(line["repository"], line["folder"], line["commit"]) as packed:
            verdict = package_folder.take(packed)
    except NotFound as wrong:
        raise Refusal("not-found", where, str(wrong))
    if not verdict["ok"]:
        place = " at " + verdict["at"] if verdict["at"] else ""
        raise Refusal("refused", where, "The validator refuses the package: %s%s." % (verdict["code"], place))
    return verdict


def _holds_no_package(top):
    declaration = definition.load().lowest()["declaration"]["file"]
    for at, folders, files in os.walk(top):
        if at == top and ".git" in folders:
            folders.remove(".git")
        folders.sort()
        if declaration in files:
            found = os.path.relpath(os.path.join(at, declaration), top)
            raise Refusal("holds-a-package", found, "The list's repository holds no package.")


def _numbers(version):
    return tuple(int(number) for number in version.split("."))


def check(new, old=None, holds=None):
    """Checks the list in the file new, and raises the first Refusal.

    old is the list as it was, and holds is the list's own repository.
    """
    lines = read(new)
    if holds is not None:
        _holds_no_package(holds)

    packages = []
    for index, line in enumerate(lines):
        verdict = _package(line, _where(index))
        if verdict["digest"] != line["digest"]:
            words = "The package at the commit has the digest %s." % verdict["digest"]
            raise Refusal("digest-differs", _where(index), words)
        packages.append(verdict)

    ids = {}
    for index, verdict in enumerate(packages):
        if verdict["id"] in ids:
            words = "Line %d's package has the same id, %s." % (ids[verdict["id"]] + 1, verdict["id"])
            raise Refusal("id-twice", _where(index), words)
        ids[verdict["id"]] = index

    if old is None:
        return
    before = dict(((line["repository"], line["folder"]), (index, line)) for index, line in enumerate(read(old, old=True)))
    for index, line in enumerate(lines):
        was_at, was = before.get((line["repository"], line["folder"]), (None, None))
        if was is None or was["commit"] == line["commit"]:
            continue
        earlier, verdict = _package(was, _where(was_at, old=True)), packages[index]
        if (earlier["id"], earlier["kind"]) != (verdict["id"], verdict["kind"]):
            words = "The old list has %s, of the kind %s, at this address, and this is %s, of the kind %s." % (
                earlier["id"],
                earlier["kind"],
                verdict["id"],
                verdict["kind"],
            )
            raise Refusal("another-package", _where(index), words)
        if _numbers(verdict["version"]) <= _numbers(earlier["version"]):
            words = "The version %s isn't higher than the old list's %s." % (verdict["version"], earlier["version"])
            raise Refusal("not-higher", _where(index), words)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="check.py", description="Check a catalogue's list.")
    parser.add_argument("new", metavar="NEW", help="the list")
    parser.add_argument("--old", metavar="OLD", help="the list as it was before the change")
    parser.add_argument("--holds", metavar="FOLDER", help="the list's own repository, which holds no package")
    args = parser.parse_args(argv)
    for path in (args.new, args.old):
        if path is not None and not os.path.isfile(path):
            parser.error("not a file: " + path)
    if args.holds is not None and not os.path.isdir(args.holds):
        parser.error("not a folder: " + args.holds)
    if shutil.which("git") is None:
        parser.error("git isn't installed")

    try:
        check(args.new, args.old, args.holds)
    except Refusal as refused:
        sys.stderr.write(refused.line() + "\n")
        return 1
    sys.stdout.write("ok\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
