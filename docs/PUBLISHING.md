# Publishing

The PyPI distribution name is `plague-browser`. The import package and CLI stay
`plague`.

Use the Weaion Labs PyPI account, not a personal account.

## Trusted publishing

1. Sign in to PyPI as the Weaion Labs account.
2. Open the account's publishing settings and add a pending publisher:
   - PyPI project: `plague-browser`
   - Owner: `weaion-labs`
   - Repository: `plague`
   - Workflow: `publish.yml`
   - Environment: `pypi`
3. In the GitHub repository, create an environment named `pypi`.
4. Create a GitHub release. The `publish.yml` workflow builds and publishes with
   OIDC, so no API token is stored in the repository.

TestPyPI is optional but recommended for the first run. Add a second pending
publisher for TestPyPI and a workflow input or a separate manual run.

## Manual build

```bash
python -m pip install --upgrade build
python -m build
python -m pip install dist/plague_browser-0.1.0-py3-none-any.whl
plague --version
```

Upload with `twine` only if you are not using trusted publishing:

```bash
python -m pip install --upgrade twine
twine check dist/*
twine upload dist/*
```

Do not commit tokens. Do not use a personal PyPI account for the project.

## After publishing

- Add the PyPI badge to the README.
- Add `pip install plague-browser` to the quickstart.
- Verify `uvx --from plague-browser plague doctor`.
- Add the project to the MCP directories with the PyPI install line.
