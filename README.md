# Iris's package catalogue

This repository holds the Iris project's catalogue: the list of add-on packages that every instance of Iris offers. Iris is a self-hosted platform for a personal AI agent, and an instance is one installed copy of it.

The list is [`list.json`](list.json). It holds no package. Each line names where a package is kept, a GitHub repository and a folder in it, and pegs it to one commit and the package's digest. An instance installs that folder at that commit, and only when its digest is the line's.

The Iris project writes this repository. A trust agent may later move lines too. Whoever moves a line can't change a package, because packages are kept in other repositories. The project's own packages are kept in [iris-agent-official-packages](https://github.com/iris-agent-project/iris-agent-official-packages).

## What's here

| Path | What it is |
|---|---|
| [`list.json`](list.json) | The list |
| [`listings/`](listings) | The project's copy of each line's listing, so that an instance can show the catalogue without contacting a package's repository |
| [`FORMAT.md`](FORMAT.md) | The list's format, the listings' format and the rules the check holds |
| [`check.py`](check.py) | The list's check |

To move a line, change `list.json` and its listing's copy, and run the check before you commit, as [`FORMAT.md`](FORMAT.md#run-the-check) says. A line moves only to a higher version.

## Licence

This repository is licensed under the [Apache License 2.0](LICENSE).
