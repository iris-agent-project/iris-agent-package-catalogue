# The list's format

This page describes the format of `list.json`, the project's copy of each listing, and the rules the list's check holds. It's written for whoever moves a line, and for whoever writes a reader of the list.

A developer publishes by pushing to the repository a package is kept in. The push reaches the catalogue only when the project moves the package's line to the pushed commit.

## A line's fields

`list.json` is strict JSON in this form: `{"format": 1, "packages": [...]}`. Each entry of `packages` is a line. A line has the following four fields, each a string, and no other:

| Field | Value |
|---|---|
| `repository` | The address of the repository the package is kept in: an `https` address in lowercase, without `.git` at its end. The check also takes a repository's full path on your own computer, so that you can check a list against a copy. |
| `folder` | The package's folder in that repository, or the empty string when the package is the repository's top. |
| `commit` | The commit the line is pegged to: 40 lowercase hex digits. |
| `digest` | The package's digest at that commit: `sha256:` and 64 lowercase hex digits. The SDK's validator gives it. |

## The project's copy of each listing

Beside the list, the folder `listings/` holds the project's copy of each line's listing, so that an instance can show the catalogue without contacting any package's repository. A copy is two files, each named by the 64 hex digits of the line's digest:

| File | Content |
|---|---|
| `<digest>.json` | The package's declaration, `iris-package.json`, byte for byte as it is at the line's commit. |
| `<digest>.manifest` | The package's digest manifest: the line `iris-package-digest 1`, then one line for each file of the package, its SHA-256, two spaces and its path, sorted by path. |

An instance holds a copy to its line before it shows it: the SHA-256 of the manifest must be the line's digest, and the manifest's line for `iris-package.json` must be the SHA-256 of the declaration. A copy that isn't its line's isn't shown. The check doesn't hold the copies.

## The rules the check holds

`check.py` is the list's check. Run it on every change to the list. The check stops at the first rule a list breaks, in the order of the following table. It prints one line, which starts with the rule's code and names the line of the list, counted from 1.

| Code | What the check refuses |
|---|---|
| `bad-list` | A list that isn't strict JSON in the form this page gives. A name given twice is one way to break it. |
| `bad-line` | A line whose repository, folder, commit or digest isn't in its form. |
| `address-twice` | Two lines with one address. An address is the repository and the folder together. |
| `holds-a-package` | A file named `iris-package.json` anywhere in the list's own repository. |
| `not-found` | A line whose repository doesn't hold its commit, or whose commit doesn't hold its folder. |
| `refused` | A line whose package the SDK's validator refuses. The printed line gives the validator's code. |
| `digest-differs` | A line whose digest isn't the digest of its package at its commit. |
| `id-twice` | Two lines whose packages have one id. |
| `another-package` | A line moved to a commit where the package's id or kind isn't the one the old list has at that address. |
| `not-higher` | A line moved to a commit where the package's version isn't higher than the old list's. An equal version is refused, and so is a lower one. The check compares a version's three numbers as numbers. |

The last two rules compare the list with the list as it was, so the check holds them only when you give it the old list.

The check reads a package as its folder at the line's commit: every file the commit holds, by path and content. It checks nothing out, and it reads none of your git settings.

## Run the check

The check needs Python 3.14, git and the Iris SDK, from which it imports the validator and the digest. It reads each line's repository over HTTPS with no credential, so a line whose repository is private is refused `not-found`.

To check the list, run this command from the repository's top:

```sh
python3.14 check.py list.json --holds .
```

The output is `ok` when the list breaks no rule, and the command ends with 0. On a refusal it ends with 1.

To check a change to the list before you commit it, also give the check the committed list:

```sh
git show HEAD:list.json > /tmp/list-as-it-was.json
python3.14 check.py list.json --old /tmp/list-as-it-was.json --holds .
```
