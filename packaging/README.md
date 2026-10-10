# Empacotamento — pyssh

Todos os comandos rodam na raiz do repositório. Versão lida de `pyproject.toml`.

| Artefato | Comando | Onde roda |
| --- | --- | --- |
| Portátil (GUI+CLI, vários arquivos) | `packaging/build-portable.sh` | Linux/Windows com `pyinstaller` |
| Instalar portátil no PATH | `packaging/portable-install.sh` | Linux (`~/.local/bin`) |
| AppImage | `packaging/build-appimage.sh` | Linux (`squashfs-tools`) |
| .deb (Debian/Ubuntu) | `packaging/build-deb.sh` | qualquer (fallback `ar` sem dpkg) |
| .pkg.tar.zst (Arch) | `cd packaging/arch && makepkg -s` | Arch/CachyOS |
| .rpm (Fedora/RHEL) | `rpmbuild -ba packaging/fedora/pyssh.spec` | Fedora (Source0 = tarball) |
| .exe Windows (portátil) | `packaging/build-portable.sh` | Windows (ou CI) |
| Tarball de fonte | `packaging/make-source-tarball.sh` | qualquer |

## Layout instalado nos pacotes (.deb/.rpm/PKGBUILD)

```
/usr/lib/pyssh/            código-fonte (main.py, cli.py, pyssh/)
/usr/bin/pyssh             wrapper sh → python3 /usr/lib/pyssh/main.py
/usr/bin/pyssh-cli         wrapper sh → python3 /usr/lib/pyssh/cli.py
/usr/share/applications/pyssh.desktop
/usr/share/icons/hicolor/{48,128,256}x256/apps/pyssh.png
/usr/share/{doc,licenses}/...
```

Wrappers em `packaging/wrappers/` resolvem o `PYTHONPATH` para `/usr/lib/pyssh`,
o que funciona igual em Debian (`python3-tk`), Fedora (`python3-tkinter`) e
Arch (`python-tk`) — só muda o nome do pacote de Tk declarado em cada
`depends`.

## Portátil (vários arquivos + PATH)

`build-portable.sh` gera `dist/pyssh-portable/` com duas pastas onedir —
`pyssh/pyssh` + `_internal/` (GUI) e `pyssh-cli/pyssh-cli` + `_internal/`
(CLI) — via `packaging/pyssh-gui.spec` e `packaging/pyssh-cli.spec` (um spec
por EXE: um COLLECT com duas Análises colide o `PYZ-00.pyz` — PYI-41745).
A mesma spec builda os `.exe` no Windows via CI. `portable-install.sh` cria
symlinks em `~/.local/bin` (já em PATH na maioria das distros) ou, com
`PREFIX=/usr/local sudo ...`, no PATH do sistema; `--remove` desfaz.

## CI (.github/workflows/build.yml)

Roda em tags `v*` (e manualmente): portátil+AppImage (ubuntu), .deb (ubuntu),
pacote Arch (container `archlinux`), .rpm (container `fedora`) e `.exe`
(`windows-latest`, com smoke test `--help`/`--selftest`). Tudo vai para a
release da tag.

## Ícones

`packaging/icons/` é gerado do PNG da raiz:

```bash
magick "Logo pyssh_ terminal, segurança e Python.png" -strip -resize 256x256 packaging/icons/pyssh-256.png
# idem 128/48/32; .ico:
magick "Logo pyssh_ terminal, segurança e Python.png" -resize 256x256 \
  -define icon:auto-resize=256,128,64,48,32,16 packaging/icons/pyssh.ico
```
