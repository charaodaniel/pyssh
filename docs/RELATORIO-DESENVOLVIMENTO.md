# Relatório de Desenvolvimento — pyssh

> Documento de acompanhamento técnico. Atualizado em **10/10/2026**.
> Visão de produto e pendências: [ROADMAP.md](../ROADMAP.md).
> Uso e instalação: [README.md](../README.md).

> **Entrega mais recente (abaixo, seção 10):** correção da exportação CSV
> da GUI (causa raiz em `history.events(limit=0)`), novo formato JSON no
> módulo/CLI/GUI e versão **0.0.2**. 240 testes OK.

## 1. Resumo

`pyssh` é uma ferramenta leve para Linux que localiza dispositivos com SSH na
rede local (porta `8022` por padrão, cenário principal: Android com Termux) e
inicia conexões por terminal. Até o momento foram entregues:

| Entrega | Escopo | Estado |
| --- | --- | --- |
| Fase 1 | Núcleo compartilhado (`network`, `scanner`, `settings`) | ✅ |
| Fase 2 | `pyssh-cli` (`scan`, `connect`, seleção interativa, exit codes) | ✅ |
| Infra | Venv, repositório Git e publicação no GitHub | ✅ |
| Fase 4 | Interface gráfica Tkinter/ttk | ⬜ pendente |
| Fase 5 | Sessões SSH em terminais independentes | ⬜ pendente |

Nenhum módulo entregue importa Tkinter: o núcleo e a CLI rodam em servidores
sem desktop (validado com `sys.modules["tkinter"] = None` antes do import).

## 2. Ambiente de desenvolvimento

| Item | Valor |
| --- | --- |
| Sistema | CachyOS/Arch Linux |
| Python | 3.14.7 |
| Ferramentas usadas pelo programa | `iproute2` (`ip`), OpenSSH (`ssh`) |
| Gerenciador de pacotes | nenhum de terceiros — só biblioteca padrão |
| Ambiente virtual | `.venv` no próprio projeto (commit fora do versionamento) |
| Repositório | `git@github.com:charaodaniel/pyssh.git`, branch `main` |

Observação: o Tkinter deste ambiente está **quebrado** (falta `libtk8.6.so`),
o que reforçou a decisão de manter GUI desacoplada — ela será implementada e
testada depois de instalar o pacote `tk`.

## 3. O que foi construído

### 3.1 Núcleo (`pyssh/`)

| Módulo | Responsabilidade |
| --- | --- |
| `network.py` | Interfaces e faixa IPv4 via `ip -json addr` (com fallback textual), validação de IP/CIDR/host, iteração de endereços pulando rede e broadcast |
| `scanner.py` | Varredura TCP por janela de threads, timeout por tentativa, cancelamento por `threading.Event`, lock que impede buscas simultâneas, `HostResult`/`ScanReport` estruturados, callback de progresso, reverse DNS opcional |
| `settings.py` | Porta padrão `8022`, validação de porta/timeout/concorrência, preferências em `~/.pyssh-settings.json` (sem dados sensíveis) |
| `ssh_client.py` | Montagem do comando `ssh` como **lista de argumentos** (sem shell), execução interativa herdando o terminal, mapeamento de falhas |

### 3.2 `pyssh-cli` (`cli.py`)

```text
pyssh-cli scan [-n CIDR] [-p 8022] [-t s] [-w n] [--all] [--quiet]
               [--no-hostname] [--no-interactive] [-u USUÁRIO]
pyssh-cli connect HOST [-u USUÁRIO] [-p PORTA] [-- argumentos do ssh]
```

* Descobre a rede automaticamente quando `--network` não é informado.
* Lista numerada para seleção quando stdin é um terminal; **pulada** em pipe
  ou script.
* Resultados em **stdout**, progresso/avisos/erros em **stderr**.
* `Ctrl+C` cancela a busca e ainda lista o parcial (código 130).

### Códigos de saída

| Código | Significado |
| --- | --- |
| 0 | sucesso |
| 1 | erro interno inesperado |
| 2 | argumentos ou configuração inválidos |
| 3 | nenhum dispositivo com a porta aberta |
| 4 | OpenSSH ausente ou `ssh` retornou 255 |
| 130 | interrompido pelo usuário (Ctrl+C) |
| demais | propagados do `ssh` (saída do shell remoto) |

## 4. Decisões técnicas

| Decisão | Motivo | Alternativa descartada |
| --- | --- | --- |
| Somente biblioteca padrão | Baixo consumo, instalação trivial em servidor | `python-nmap`, `scapy`, `rich` |
| `unittest` nos testes | Sem dependência externa no ambiente | `pytest` (ausente na máquina) |
| `ip -json addr` com fallback textual | JSON evita parsing frágil; fallback cobre versões antigas | `psutil` |
| Janela de futures (`workers * 4`) em vez de submeter tudo | Um `/16` criaria 65 mil futures de uma vez | `executor.map` com todos os alvos |
| Lock **não-bloqueante** contra buscas simultâneas | GUI e CLI podem dividir o processo; erro claro é melhor que fila escondida | Espera implícita na fila |
| Cancelamento por `threading.Event` + `shutdown(cancel_futures=True)` | Testável sem sinais e funciona em thread da GUI | `executor.shutdown()` puro |
| Reverse DNS apenas em portas abertas e opt-in (`--no-hostname`) | Consulta reversa é a parte mais lenta | Lookup de todos os alvos |
| Validação em camadas (`SettingsError` → `NetworkError` → `ScanError`) | Mensagem de erro útil antes de qualquer rede ser tocada | Validação dentro do loop |
| `ssh` com lista de argumentos, nunca shell | Sem risco de injeção de comando | `os.system` / string com `shell=True` |
| Senhas nunca armazenadas nem exibidas | Autenticação é do usuário/OpenSSH | Prompt de senha próprio |
| Streams separados (stdout = dados, stderr = diagnóstico) | Uso em pipeline e scripts | Mensagens todas no stdout |

## 5. Resultados de verificação (09/10/2026)

| Verificação | Resultado |
| --- | --- |
| `python -m unittest discover -s tests -t .` | **89 testes OK** (~5 s), dentro e fora do venv |
| Import do núcleo com `tkinter` bloqueado | OK — nenhuma referência a GUI em `*.py` |
| Scan real na LAN `192.168.8.0/24` (254 hosts, 8022) | 2,5 s → `192.168.8.54:8022 Android-2.local` |
| Exit codes no shell | `--help` 0 · `--port 0` 2 · rede inválida 2 · host inválido 2 · sem alvos 3 · `connect` contra porta fechada 4 |
| Pseudo-terminal real (`script(1)`) — seleção interativa | lista → escolha → spawn do `/usr/bin/ssh` → falha mapeada para 4 |
| Pseudo-terminal real — `^C` no meio da busca | 130 + `busca cancelada após N verificação(ões)` |
| Pseudo-terminal real — Enter na seleção | 0, sem conexão aberta |
| `pip install -e .` em venv e CLI rodando de outro diretório | `pyssh-cli scan -q` achou o Termux (exit 0) |
| `git push -u origin main` + `git ls-remote` | branch `main` publicada (`08aeb1a`) |

### Correções feitas durante as verificações

Problemas reais encontrados pelos testes/smoke tests e corrigidos na origem:

1. `SyntaxError` em `settings.py` (`except SettingsError):`) — o núcleo nem
   importava; corrigido antes de qualquer entrega.
2. `resolve_targets` propagava `NetworkError` onde a API prometia `ScanError`
   — corrigido no módulo, não no teste.
3. Teste de `/30` em loopback assumia dois hosts abertos — asserção corrigida
   para refletir a semântica real (só o endereço com listener está aberto).
4. `Listener` dos testes travava ~2 s no `join()` (`accept()` bloqueado);
   corrigido com `settimeout(0.2)`, o que derrubou a suíte de 30 s para ~5 s.
5. `--all` não imprimia nada quando nenhum host estava aberto — ordem de
   impressão corrigida no `cli.py`.
6. `git config --local` executado antes do `git init` — corrigido reordenando
   os comandos.

## 6. Limitações conhecidas

* GUI não implementada (Fase 4) e não testável enquanto `libtk8.6.so` estiver
  ausente — instalar o pacote `tk` do sistema.
* Sessões em terminais independentes (Fase 5) ainda não existem: hoje
  `connect` abre o `ssh` no terminal atual.
* Login SSH real num aparelho não foi automatizado nos testes (exigiria
  credenciais/chave); o caminho foi coberto com servidor TCP falso, porta
  fechada e testes unitários do comando e do mapeamento de códigos.
* Chave SSH do repositório criada sem passphrase (push sem `ssh-add`);
  proteger com `ssh-keygen -p -f ~/.ssh/id_ed25519` se desejado.
* Sem `LICENSE` (o GitHub vai sugerir) e sem empacotamento para
  distribuições.

## 7. Próximos passos

1. **Fase 4** — GUI Tkinter/ttk: campos de rede/porta, `ttk.Treeview`,
   botões Escanear/Cancelar, painel de logs com horário e níveis.
2. **Fase 5** — `ssh_client` com detecção de terminais (kitty, konsole,
   xfce4-terminal) e sessões que sobrevivem ao fechamento da GUI.
3. **Fase 6** — lembrar última rede/porta, seleção de interface e
   descoberta por mDNS/Avahi (complementar à varredura TCP).
4. **Fase 8** — instalação de dependências de sistema, `.desktop` e
   empacotamento.

## 8. Como reproduzir as verificações

> Esta seção descreve as verificações das fases iniciais. As da entrega
> recente estão na seção 9.

```bash
git clone git@github.com:charaodaniel/pyssh.git
cd pyssh
python3 -m venv .venv && source .venv/bin/activate
pip install -e .

python -m unittest discover -s tests -t .   # 89 testes
pyssh-cli scan                              # detecta a rede e procura a 8022
pyssh-cli scan -n 192.168.8.0/24 --all      # inclui portas fechadas
pyssh-cli connect 192.168.8.52 -u dev       # abre o ssh no terminal atual
```

Para simular um terminal interativo sem sair do shell:

```bash
printf '1\n' | script -qec "pyssh-cli scan -n 127.0.0.1/32 -p 8022" /dev/null
```

---

## 9. Entrega — conexões, chaves, histórico e terminal padrão (09/10/2026)

Esta fase implementa o novo roadmap (Fases 3–9) sem remover nada do que já
existia: os módulos antigos (`network`, `scanner`, `ssh_client`, `terminal`,
`settings`) e a CLI/GUI atuais continuam intactos e com todos os testes
originais passando.

### 9.1 Módulos novos

| Módulo | Responsabilidade |
| --- | --- |
| `storage.py` | Diretórios XDG (`$XDG_CONFIG_HOME/pyssh`, `$XDG_DATA_HOME/pyssh`), gravação de JSON **atômica** (`os.replace` + `fsync`), permissões restritas (0700/0600), leitura tolerante de JSONL, escrita de CSV. |
| `connections.py` | CRUD de conexões salvas: nome, host, porta (padrão 8022), usuário, referência a chave, observações, ID curto e carimbos de data. Validação de campos, nome único (sem diferenciar caixa), busca, duplicação. |
| `keys.py` | Referências a chaves SSH: nome + caminho (expandido). Geração real via `ssh-keygen` (ed25519/rsa/ecdsa), impressão digital (`ssh-keygen -lf`), tipo pelo `.pub`, alerta de permissões amplas. **Remover referência nunca apaga o arquivo** (a menos que `--delete-file`). |
| `history.py` | Histórico em JSON Lines com 7 campos (timestamp, event, connection_id, address, port, status, message), filtros combináveis (evento, estado, endereço por substring, data, conexão, limite), exportação CSV/JSONL, rotação por tamanho (1 MiB, 3 rotações) e limpeza. |

Cada entrega do roadmap está refletida no `ROADMAP.md` (checkboxes) e no
`README.md` (exemplos de uso).

### 9.2 Integração na CLI

Novos subcomandos, com a mesma filosofia de exit codes da CLI original:

```text
pyssh-cli connections list|add|edit|delete|duplicate|fields
pyssh-cli keys list|add|edit|delete|generate|fields
pyssh-cli history list|export|clear|fields
pyssh-cli connect HOST|NOME        # resolve conexão salva e injeta -i da chave
```

* `connect NOME` procura primeiro nas conexões salvas (por ID ou nome); não
  achando, trata o argumento como host (compatível com o uso anterior).
  Quando a conexão tem chave associada, o `-i <caminho>` é injetado antes do
  host.
* Exclusões (`delete`/`clear`) exigem confirmação: `--yes` pula; sem tty e
  sem `--yes`, é **erro de uso (exit 2)** — decisão explícita, documentada.

### 9.3 Integração na GUI

A janela passou a usar `ttk.Notebook` com quatro abas — **Descoberta**,
**Conexões**, **Chaves** e **Histórico** — mantendo os atributos testados
(`network_var`, `port_var`, `tree`, `worker`, `log_panel`, `status_var`).

* **Conexões:** tabela + adicionar/editar/duplicar/excluir/conectar (duplo
  clique conecta) + campo de busca.
* **Chaves:** tabela com tipo e impressão digital + cadastrar/editar/
  remover/gerar nova.
* **Histórico:** tabela (mais recente primeiro) + filtros por evento e
  endereço + exportar CSV (via diálogo) + limpar (com confirmação).
* Diálogos simples (`_ask_form`) sem dependências externas.

### 9.4 Terminal padrão do sistema (correção importante)

O `find_terminal(configured)` anterior retornava só o caminho, **sem o
argumento de execução** — e o Alacritty (terminal padrão deste sistema,
`Mod+Return` no niri) **falha sem `-e`** (comprovado: exit 2). Correções:

1. `exec_args_for()` devolve o argumento certo por terminal (`-e`, `--` para
   gnome-terminal, `-x` para xfce4-terminal) e convenção `-e` para
   desconhecidos.
2. `detect_system_terminal()` detecta o padrão do sistema: `settings.terminal`
   → spec XDG (`xdg-terminal-exec`) → `$TERMINAL` → `x-terminal-emulator` →
   lista fixa.
3. `settings.terminal = "alacritty"` gravado nas preferências.

Também foi corrigido um bug real em `settings.py`: a chave `extra` aninhava
`{"extra": {"extra": ...}}` a cada gravação (o arquivo do usuário acumulava
níveis). O `from_dict` agora ignora a própria chave e **repara** arquivos já
corrompidos no load.

### 9.5 Segurança (invariantes verificados)

* Chaves privadas **nunca** copiadas para o diretório do `pyssh` — só o
  caminho é guardado.
* Nenhuma senha, passphrase ou material de chave é gravado nos arquivos de
  dados nem no histórico.
* A autenticação permanece 100% do OpenSSH; o registro final do histórico
  usa o código de saída do `ssh` (não declara "autenticado" sem confirmação).
* Arquivos de dados gravados com 0600 e diretórios 0700; gravação atômica
  para não corromper JSON em caso de queda.

### 9.6 Decisões técnicas

| Decisão | Motivo | Alternativa descartada |
| --- | --- | --- |
| JSON atômico (tmp + `os.replace` + `fsync`) | Nunca deixar arquivo pela metade | Sobrescrita direta |
| Histórico em JSON Lines | Acrescentar evento sem reescrever o arquivo; rotação simples | JSON único (reescrita total) ou SQLite (peso) |
| Chaves como **referências** (não cópias) | Sem duplicar segredo; usuário mantém controle | Copiar chave para o diretório do app |
| `_confirm` tri-valente (True/False/None) | Distinguir "recusou" de "não posso confirmar" (exit 2) | `bool` só (perdia o caso de erro de uso) |
| IDs curtos de 12 hex + busca por nome | Legíveis na CLI e estáveis | Só nome (ambíguo) ou UUID longo |
| Loja por arquivo com escrita atômica inteira | Poucos registros; sem dependência | Bloco de registro/lock |

### 9.7 Verificações executadas (09/10/2026)

| Verificação | Resultado |
| --- | --- |
| `python3 -m unittest discover -s tests -t .` | **216 testes OK** (125 anteriores + 91 novos) |
| Testes novos (`storage`, `connections`, `keys`, `history`) | 70 OK — CRUD, validação, persistência, rotação, filtros, exportação |
| Testes novos de CLI (`NewCommandsTests`) | 21 OK — subcomandos, exit codes, confirmação sem tty |
| Geração real de chave `ed25519` via `ssh-keygen` | OK — cria `.pub`, devolve `SHA256:...`; destino ocupado é recusado |
| `pyssh-cli connect NOME` (mock do `run_interactive`) | OK — resolve a conexão salva e monta `ssh -p … -i <chave> <host>` |
| `pyssh --selftest` (GUI) | OK — janela em abas abre e fecha (exit 0) |
| E2E terminal padrão: `settings → alacritty -e ssh → Termux` | OK — comando remoto executou no dispositivo |

### 9.8 Bugs encontrados e corrigidos nesta entrega

1. `ConnectionStore._load` deixava `StorageError` vazar em vez de converter
   em `ConnectionsError` (mesmo caso no `KeyStore`/`KeyError_`) — corrigido
   na origem, não no teste.
2. `_confirm` retornava falso positivo de "cancelado" (exit 0) quando não
   havia tty e faltava `--yes` — deveria ser erro de uso (exit 2); corrigido
   com retorno tri-valente.
3. `find_terminal(configured)` sem argumento de execução quebrava o
   Alacritty — corrigido (seção 9.4).
4. `settings.py` aninhava `extra` a cada gravação — corrigido e com teste de
   regressão.

### 9.9 Limitações conhecidas desta entrega

* O `settings.json` ainda fica em `~/.pyssh-settings.json` (compatibilidade);
  os novos módulos já usam XDG. A migração está no TODO.
* A geração de chave na GUI usa diálogo simples (sem escolher bits de RSA;
  a CLI aceita `--bits`).
* Falta o teste automatizado de fechamento **forçado** da GUI durante sessão
  ativa (a desanexação em si é coberta por teste unitário de
  `spawn_session`).
* A suíte usa `unittest` (stdlib); `pytest` roda os mesmos testes, mas é
  dependência opcional de desenvolvimento (não instalada por padrão, para
  manter o runtime sem terceiros).

---

## 10. Entrega — correção da exportação CSV, formato JSON e v0.0.2 (10/10/2026)

### 10.1 Bug: a exportação CSV da GUI não funcionava

Causa raiz em `history.events(limit=0)`: o corte antigo
(`filtered[-limit:] if limit else []`) devolvia **vazio** para `limit=0`,
porem `0 = todos` é o comportamento documentado na própria CLI. A CLI
mascarava o problema com `args.limit or None`; a GUI chamava `events(limit=0)`
direto e logava "Nenhum evento para exportar" mesmo com histórico cheio.

Correção no módulo (não no chamador): `limit > 0` aplica o corte; `0`/`None`
são sem limite. Teste de regressão: `test_limit_zero_significa_todos`.

### 10.2 Formato JSON

* `history.export(rows, destino, "json")` grava um **array JSON indentado**
  com os 7 campos de cada evento.
* CLI: `pyssh-cli history export --format json` (choices `csv|json|jsonl`).
* GUI: diálogo oferece CSV, JSON e JSON Lines — a extensão escolhida decide
  o formato; o botão passou a se chamar "Exportar…".
* CSV continua com cabeçalho e o mesmo layout (testado por leitura com
  `csv.DictReader`).

### 10.3 Versão e verificações (10/10/2026)

Versão **0.0.2** em `pyproject.toml`, `pyssh/__init__.py`, PKGBUILD e spec do
RPM (os scripts de build leem a versão do `pyproject.toml`).

| Verificação | Resultado |
| --- | --- |
| `python3 -m unittest discover -s tests -t .` | **240 testes OK** (236 + 4 novos) |
| Novos testes | JSON (módulo), regressão `limit=0`, CLI `--format json`, e2e da GUI (diálogo → CSV e JSON gravados) |
| Exportação CSV real (CLI) | 13 eventos, cabeçalho + linhas corretas |
| Documentação | README, ROADMAP, TODO e este relatório atualizados |
