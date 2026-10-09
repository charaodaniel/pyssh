# Relatório de Desenvolvimento — pyssh

> Documento de acompanhamento técnico. Atualizado em **09/10/2026**.
> Visão de produto e pendências: [ROADMAP.md](../ROADMAP.md).
> Uso e instalação: [README.md](../README.md).

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
