# TODO — pyssh

> Pendências priorizadas. Estado em **10/10/2026**: **v0.0.2** — correção
> da exportação CSV da GUI, formato JSON, empacotamento e push ao GitHub
> (**240 testes OK**). Antes: Fases 1–9 (núcleo + `pyssh-cli` + GUI em abas
> + conexões/chaves/histórico). Detalhes em [ROADMAP.md](../ROADMAP.md) e
> [RELATORIO-DESENVOLVIMENTO.md](RELATORIO-DESENVOLVIMENTO.md).

## Ações imediatas

* [x] Fazer o `git push` dos commits locais (pendente de novo push desta entrega).
* [x] Instalar o pacote `tk` — contornado: validado em prefixo local
      `~/.local/opt/tk`; instalação definitiva continua pendente
      com `sudo pacman -S --needed tk`.
* [x] Criar o `LICENSE` (MIT) — criado em 10/10/2026 (empacotamento).
* [x] Fazer `git push` desta entrega — feito em 10/10/2026 (`fe950c2`).

## Entrega 10/10/2026 — v0.0.2

* [x] Bug: `history.events(limit=0)` devolvia vazio — a exportação CSV da GUI
      logava "Nenhum evento para exportar" mesmo com eventos; corrigido
      (`0` = sem limite, como a CLI já documentava) com teste de regressão.
* [x] Exportação em **JSON** (array indentado) no módulo, na CLI
      (`--format json`) e na GUI (CSV/JSON/JSON Lines; a extensão escolhida
      decide o formato; botão renomeado para "Exportar…").
* [x] Versão **0.0.2** em `pyproject.toml`, `pyssh/__init__.py`, PKGBUILD e
      spec do RPM.
* [x] Empacotamento (portátil/AppImage/.deb/Arch/RPM/CI) publicado no GitHub.

## Entregue nesta rodada (novo roadmap)

* [x] `pyssh/storage.py` — diretórios XDG, JSON atômico, permissões 0700/0600,
      JSONL e CSV.
* [x] `pyssh/connections.py` — CRUD de conexões salvas (validação, busca,
      duplicação, persistência atômica).
* [x] `pyssh/keys.py` — referências a chaves SSH, geração via `ssh-keygen`,
      impressão digital, alerta de permissões; remover referência preserva o
      arquivo.
* [x] `pyssh/history.py` — histórico JSONL com filtros (evento, endereço,
      estado, data, conexão), exportação CSV/JSON/JSONL, rotação (1 MiB, 3
      rotações) e limpeza.
* [x] CLI: `connections`, `keys`, `history` + `connect NOME` (resolve conexão
      salva e injeta `-i` da chave associada).
* [x] CLI: registro automático de eventos (busca, conexão, sessão, CRUD,
      chaves, exportação).
* [x] GUI: abas **Descoberta**, **Conexões**, **Chaves**, **Histórico** com
      CRUD, filtros e exportação; sessões abertas em terminal desanexado.
* [x] Testes dos novos módulos + novos subcomandos da CLI (216 no total).

## Pendências restantes

### Fase 5/9 — Sessões e encerramento

* [ ] Testar fechamento normal **e** forçado da GUI durante sessão ativa
      (a mecânica de desanexação já é coberta por teste unitário).
* [ ] Conexão real com o Termux e descoberta após reiniciar o telefone.

### Fase 6 — Armazenamento

* [ ] Migrar `~/.pyssh-settings.json` para `~/.config/pyssh/settings.json`
      (hoje os novos módulos já usam XDG; só o settings fica na raiz do home).
* [ ] Seleção de interface de rede na CLI e na GUI.
* [ ] Descoberta complementar por mDNS/Avahi (não substitui a varredura TCP).
* [ ] Suporte a perfis do `~/.ssh/config` (aliases `Host`, `ProxyJump`).

### Fase 10 — Documentação e distribuição

* [ ] Avaliar distribuição: PKGBUILD/AUR e `pipx install pyssh`.
* [ ] Arquivo `.desktop` para lançar a GUI.
* [ ] Instruções de diagnóstico (firewall, ARP, porta errada, Termux
      adormecido).

### Melhorias de UX

* [ ] Na GUI, usar a porta/usuário padrão da conexão salva ao conectar pela
      tabela da Descoberta.
* [ ] Histórico: filtro por faixa de datas na GUI (a CLI já tem
      `--since`/`--until`).
