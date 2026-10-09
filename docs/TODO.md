# TODO — pyssh

> Pendências priorizadas. Estado em **09/10/2026**: Fases 1–9 praticamente
> entregues (núcleo + `pyssh-cli` completo + GUI em abas + conexões/chaves/
> histórico, **216 testes OK**). Detalhes em [ROADMAP.md](../ROADMAP.md) e
> [RELATORIO-DESENVOLVIMENTO.md](RELATORIO-DESENVOLVIMENTO.md).

## Ações imediatas

* [x] Fazer o `git push` dos commits locais (pendente de novo push desta entrega).
* [x] Instalar o pacote `tk` — contornado: validado em prefixo local
      `~/.local/opt/tk`; instalação definitiva continua pendente
      com `sudo pacman -S --needed tk`.
* [ ] Criar o `LICENSE` (MIT) — o README já declara MIT.
* [ ] Fazer `git push` desta entrega (conexões/chaves/histórico/GUI).

## Entregue nesta rodada (novo roadmap)

* [x] `pyssh/storage.py` — diretórios XDG, JSON atômico, permissões 0700/0600,
      JSONL e CSV.
* [x] `pyssh/connections.py` — CRUD de conexões salvas (validação, busca,
      duplicação, persistência atômica).
* [x] `pyssh/keys.py` — referências a chaves SSH, geração via `ssh-keygen`,
      impressão digital, alerta de permissões; remover referência preserva o
      arquivo.
* [x] `pyssh/history.py` — histórico JSONL com filtros (evento, endereço,
      estado, data, conexão), exportação CSV/JSONL, rotação (1 MiB, 3
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
