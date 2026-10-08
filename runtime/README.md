# Bundled Python for Windows

`python\` is the official **Python 3.13.16 embeddable package for 64-bit Windows** from python.org
(`python-3.13.16-embed-amd64.zip`, SHA-256 `97dae5274cc54867065e8d5a3226e48c35017ed332a0fdb0e27d5b5821961297`),
with Gate Tasks' requirements installed in `python\Lib\site-packages` (exact versions in `requirements-windows.txt`).

`Start_Gate_Tasks.bat` uses it automatically, so the PC needs neither Python nor internet access.
`python313._pth` puts `Lib\site-packages` and the Gate Tasks folder (`..\..`) on the import path.

## Rebuilding (after changing `requirements.txt` or to update Python)

On any machine with Python and internet, from the repository root:

```bash
rm -rf runtime/python
curl -LO https://www.python.org/ftp/python/3.13.16/python-3.13.16-embed-amd64.zip
unzip python-3.13.16-embed-amd64.zip -d runtime/python
python -m pip install uv
uv pip install --target runtime/python/Lib/site-packages --python-platform x86_64-pc-windows-msvc \
  --python-version 3.13 --only-binary :all: --no-compile -r runtime/requirements-windows.txt
rm -rf runtime/python/Lib/site-packages/bin
printf 'python313.zip\r\n.\r\nLib\\site-packages\r\n..\\..\r\nimport site\r\n' > runtime/python/python313._pth
```

To move to newer packages, install from `requirements.txt` instead and refresh `requirements-windows.txt`.
