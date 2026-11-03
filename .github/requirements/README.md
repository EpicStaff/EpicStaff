# CI Python requirements

Every `pip install` in `.github/workflows/` installs from one of these files with
`--require-hashes`, so a job runs exactly the packages that were reviewed here, down to
the last transitive dependency. Several of these jobs hold write tokens, the
image-signing identity or a Drive service-account key. A bare `pip install <name>`
there would run whatever release PyPI serves that day.

- `<name>.in` lists what a job needs directly.
- `<name>.txt` is the locked set, generated from it. Do not edit it by hand.

To add a package or change a version, edit the `.in` file and regenerate the `.txt`
file from this directory:

```sh
uv pip compile --universal --python-version 3.11 --generate-hashes --no-header \
  --exclude-newer <date at least 7 days ago> <name>.in -o <name>.txt
```

`--universal` keeps the hashes for every platform and Python version the runners use.
`--exclude-newer` holds back releases younger than a week, the same cooldown Dependabot
uses: a hijacked release is usually found and pulled within days.

`uv.in` pins the same uv version that the service Dockerfiles install. Change both
together.
