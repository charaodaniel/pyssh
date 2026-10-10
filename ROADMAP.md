# pyssh — Roadmap do Projeto

> Aplicação Linux em Python para descobrir dispositivos SSH na rede local,
> gerenciar conexões e chaves, iniciar sessões remotas e consultar o
> histórico de atividades.

> **Status (09/10/2026):** Fases 1–9 praticamente entregues — núcleo,
> `pyssh-cli` completo (`scan`, `connect`, `connections`, `keys`, `history`),
> GUI em abas, sessões independentes, 216 testes OK. Pendências finais:
> fechamento da Fase 10 (distribuição) e alguns itens de polish.
> Acompanhamento: [docs/RELATORIO-DESENVOLVIMENTO.md](docs/RELATORIO-DESENVOLVIMENTO.md),
> pendências: [docs/TODO.md](docs/TODO.md).

## 1. Objetivo

Aplicação Linux em Python para descobrir dispositivos SSH na rede local,
gerenciar conexões e chaves, iniciar sessões remotas e consultar o
histórico de atividades.

O projeto terá duas interfaces:

* **pyssh:** interface gráfica com Tkinter/ttk.
* **pyssh-cli:** interface de linha de comando para desktops e servidores
  sem ambiente gráfico.

Ambas utilizarão o mesmo núcleo de rede, conexão, armazenamento e histórico.

## 2. Tecnologias

* Python 3
* Tkinter/ttk para a GUI
* `socket` para varredura TCP
* `threading` para tarefas de rede
* `subprocess` para iniciar o OpenSSH e terminais
* `iproute2` para identificação de redes
* OpenSSH para autenticação
* JSON para configurações e conexões
* CSV e JSON para exportação de histórico
* `pytest` para testes automatizados

> **Nota desta entrega:** a suíte usa `unittest` da biblioteca padrão (os
> testes rodam com `pytest` sem alteração, pois são `unittest.TestCase`).
> `pytest` é uma dependência de desenvolvimento opcional; o runtime não
> requer nenhuma biblioteca de terceiros.

Não será necessário utilizar banco de dados no MVP.

## 3. Estrutura do projeto

```text
pyssh/
├── pyssh/
│   ├── __init__.py
│   ├── network.py
│   ├── scanner.py
│   ├── ssh_client.py
│   ├── terminal.py        # terminais do sistema e sessões desanexadas
│   ├── connections.py     # CRUD de conexões salvas
│   ├── keys.py            # referências a chaves SSH
│   ├── history.py         # histórico JSONL + exportação CSV/JSON
│   ├── storage.py         # dirs XDG, JSON atômico, permissões
│   ├── gui.py             # janela Tkinter/ttk
│   └── settings.py
├── main.py
├── cli.py
├── pyproject.toml
├── README.md
├── ROADMAP.md
├── .gitignore
└── tests/
    ├── test_network.py
    ├── test_scanner.py
    ├── test_ssh_client.py
    ├── test_terminal.py
    ├── test_connections.py
    ├── test_keys.py
    ├── test_history.py
    ├── test_storage.py
    ├── test_settings.py
    ├── test_cli.py
    └── test_gui.py
```

### Responsabilidades dos módulos

* `network.py`: identificação e validação de redes.
* `scanner.py`: descoberta de dispositivos e portas abertas.
* `ssh_client.py`: preparação e inicialização das sessões SSH.
* `terminal.py`: detecção do terminal do sistema e sessões fora do processo.
* `connections.py`: CRUD de conexões salvas.
* `keys.py`: cadastro, listagem e gerenciamento de referências a chaves SSH.
* `history.py`: registro e consulta de atividades.
* `storage.py`: leitura, gravação e validação dos arquivos JSON/CSV.
* `settings.py`: preferências gerais.
* `main.py`: interface gráfica.
* `cli.py`: comandos de terminal.

## 4. Fase 1 — Núcleo compartilhado ✅

* [x] Criar a estrutura modular.
* [x] Implementar a identificação da rede local (`ip -json addr`, com fallback).
* [x] Implementar a varredura TCP (threads, timeout, cancelamento).
* [x] Utilizar `8022` como porta padrão.
* [x] Permitir alterar a porta na GUI e na CLI.
* [x] Validar faixas de rede, portas e timeouts.
* [x] Criar resultados estruturados para os dispositivos encontrados.

## 5. Fase 2 — pyssh-cli ✅

* [x] Implementar `pyssh-cli scan`.
* [x] Implementar `pyssh-cli connect`.
* [x] Permitir informar rede, usuário e porta.
* [x] Listar dispositivos encontrados.
* [x] Oferecer seleção interativa de resultados.
* [x] Exibir mensagens de erro e progresso (stdout/stderr separados).
* [x] Funcionar sem Tkinter ou ambiente gráfico.
* [x] Integrar os comandos de conexões, chaves e histórico.

```bash
pyssh-cli scan --network 192.168.8.0/24
pyssh-cli scan --network 192.168.8.0/24 --port 22
pyssh-cli connect 192.168.8.52 --user dev --port 8022
pyssh-cli connect Termux            # abre uma conexão salva pelo nome
pyssh-cli connections list
pyssh-cli keys list
pyssh-cli history list
```

## 6. Fase 3 — CRUD de conexões SSH ✅

### Dados de cada conexão

* [x] Nome amigável da conexão.
* [x] Endereço IP ou hostname.
* [x] Porta SSH, com padrão `8022`.
* [x] Nome de usuário.
* [x] Referência opcional a uma chave SSH.
* [x] Observações opcionais.
* [x] Data de criação e última atualização.

### Operações

* [x] Criar uma conexão salva.
* [x] Listar e pesquisar conexões.
* [x] Editar os dados de uma conexão.
* [x] Excluir uma conexão com confirmação.
* [x] Abrir uma sessão a partir de uma conexão salva.
* [x] Duplicar uma configuração para criar outra conexão.
* [x] Validar os campos antes de salvar.

### Interface gráfica

* [x] Seção **Conexões salvas** com tabela, pesquisa e ações
      (adicionar, editar, excluir, duplicar, conectar).

### CLI

```bash
pyssh-cli connections list [--search TEXTO]
pyssh-cli connections add -n NOME -H HOST [-p PORTA] [-u USUÁRIO] [-k CHAVE]
pyssh-cli connections edit ID|NOME [campos]
pyssh-cli connections delete ID|NOME [--yes]
pyssh-cli connections duplicate ID|NOME [--name NOVO]
pyssh-cli connect NOME
```

## 7. Fase 4 — CRUD de chaves SSH ✅

### Funcionalidades

* [x] Cadastrar uma referência para uma chave privada existente.
* [x] Listar chaves cadastradas.
* [x] Mostrar nome, caminho, tipo quando identificável e chave pública correspondente.
* [x] Editar nome e caminho de uma referência.
* [x] Remover uma referência do `pyssh` sem apagar automaticamente o arquivo original.
* [x] Associar uma chave a uma ou mais conexões (via `--key` em conexões).
* [x] Permitir usar a chave padrão do OpenSSH (caminho `~/.ssh/...`).
* [x] Verificar se o arquivo referenciado existe e possui permissões adequadas.
* [x] Permitir gerar novas chaves usando o `ssh-keygen` do sistema.
* [x] Permitir consultar a impressão digital da chave pública (`ssh-keygen -lf`).
* [x] Registrar no histórico as operações administrativas relevantes.

### Segurança

* [x] As chaves privadas não são copiadas para o diretório do `pyssh`.
* [x] As senhas de proteção das chaves não são armazenadas.
* [x] A autenticação é delegada ao OpenSSH (e ao `ssh-agent`).
* [x] A exclusão de uma referência não apaga a chave privada original.
* [x] A interface alerta antes de operações destrutivas (`--delete-file`).
* [x] O histórico não registra material de chave privada, senhas ou passphrases.

### CLI

```bash
pyssh-cli keys list [--search TEXTO]
pyssh-cli keys add -n NOME --path CAMINHO
pyssh-cli keys edit ID|NOME [campos]
pyssh-cli keys delete ID|NOME [--yes] [--delete-file]
pyssh-cli keys generate --type ed25519 --path CAMINHO [--name NOME]
```

A geração permite selecionar o tipo (`ed25519`, `rsa`, `ecdsa`) e o caminho
de destino, usando o `ssh-keygen` instalado.

## 8. Fase 5 — Histórico de atividades ✅

### Eventos registrados

* [x] Busca de dispositivos iniciada e concluída (`scan_started`/`scan_finished`).
* [x] Dispositivos encontrados (`device_found`).
* [x] Tentativas de abertura de conexão SSH (`connection_attempt`).
* [x] Inicialização de sessões SSH (`session_started`).
* [x] Erros de conexão conhecidos (`session_error`).
* [x] Criação, edição e exclusão de conexões salvas.
* [x] Cadastro, alteração e remoção de referências a chaves.
* [x] Exportação do histórico (`history_exported`).

O aplicativo distingue **tentativa iniciada**, **processo SSH iniciado** e
**sessão encerrada**; não declara sucesso de autenticação sem confirmação
confiável (o registro final usa o código de saída do próprio `ssh`).

### Campos do histórico

* [x] Data e hora (`timestamp`).
* [x] Tipo de evento (`event`).
* [x] Identificador da conexão (`connection_id`).
* [x] Endereço do dispositivo (`address`).
* [x] Porta utilizada (`port`).
* [x] Resultado ou estado (`status`).
* [x] Mensagem de diagnóstico sem credenciais (`message`).

### Armazenamento

* [x] Salvar o histórico em JSON Lines (`history.jsonl`), um evento por linha.
* [x] Consultar o histórico na GUI e na CLI.
* [x] Filtrar por data, dispositivo, tipo de evento e resultado.
* [x] Exportar o histórico para CSV.
* [x] Exportar uma seleção ou o histórico completo.
* [x] Limite de tamanho e rotação dos arquivos (1 MiB, 3 rotações).
* [x] Tratar arquivos ausentes, corrompidos ou sem permissão de escrita.
* [x] Limpar o histórico mediante confirmação.

### CLI

```bash
pyssh-cli history list [--limit 50] [--event T] [--address H] [--status E]
pyssh-cli history export --format csv|json|jsonl [--output ARQUIVO]
pyssh-cli history clear [--yes]
```

## 9. Fase 6 — Armazenamento e diretórios ✅

```text
~/.config/pyssh/
├── settings.json
├── connections.json
└── keys.json

~/.local/share/pyssh/
└── history.jsonl
```

> **Nota desta entrega:** o `settings.json` ainda vive em
> `~/.pyssh-settings.json` (compatibilidade); os novos módulos já usam os
> diretórios XDG. A migração do settings está no TODO.

* [x] Criar os diretórios automaticamente (0700).
* [x] Validar os dados ao carregar os arquivos.
* [x] Evitar corromper configurações durante gravações (escrita atômica).
* [x] Utilizar gravação atômica para arquivos JSON (`os.replace`).
* [x] Definir permissões restritas para os arquivos de configuração (0600).
* [x] Implementar tratamento para dados inválidos.
* [x] Documentar os caminhos e os procedimentos de backup.

## 10. Fase 7 — Interface gráfica completa ✅

* [x] Criar a tela de descoberta de rede.
* [x] Criar a tabela de dispositivos encontrados.
* [x] Criar o painel de saída e erros em tempo real.
* [x] Criar a seção de conexões salvas.
* [x] Criar a seção de gerenciamento de chaves.
* [x] Criar a seção de histórico.
* [x] Adicionar filtros e pesquisa.
* [x] Permitir exportar o histórico.
* [x] Abrir cada conexão SSH em terminal independente.
* [x] Garantir que fechar a GUI não encerre sessões já abertas.

## 11. Fase 8 — Sessões independentes ✅

* [x] Detectar terminais disponíveis no Linux (kitty, konsole, xfce4-terminal,
      alacritty, gnome-terminal, urxvt, xterm + terminal padrão do sistema).
* [x] Abrir cada conexão da GUI em uma janela independente.
* [x] Desacoplar as sessões do ciclo de vida da interface (`start_new_session`).
* [x] Permitir várias sessões simultâneas.
* [x] Garantir que o scanner seja encerrado ao fechar a GUI.
* [x] Na CLI, utilizar o terminal atual por padrão.
* [x] Tratar falhas na inicialização de terminais.
* [ ] Testar o encerramento normal e forçado da GUI (parcial — mecânica coberta).

## 12. Fase 9 — Testes ✅

* [x] Testar descoberta de rede e portas.
* [x] Testar alterações da porta padrão.
* [x] Testar o CRUD completo de conexões.
* [x] Testar o CRUD de referências a chaves.
* [x] Testar a geração de chaves pelo OpenSSH.
* [x] Testar o histórico e os filtros.
* [x] Testar exportações CSV e JSONL.
* [x] Testar arquivos inválidos e permissões insuficientes.
* [x] Testar a CLI em servidores sem ambiente gráfico.
* [x] Testar a GUI no CachyOS.
* [ ] Testar sessões SSH independentes (mecânica coberta; falta o teste de
      fechamento forçado da GUI).
* [x] Confirmar que o histórico não contém segredos.

> **216 testes** (`unittest` da stdlib; rodam também com `pytest`).

## 13. Fase 10 — Documentação e distribuição

* [x] Documentar instalação e dependências.
* [x] Documentar GUI e CLI.
* [x] Explicar o armazenamento local e os formatos.
* [x] Documentar o gerenciamento de chaves.
* [x] Explicar como exportar e limpar o histórico.
* [x] Criar exemplos de comandos.
* [x] Configurar pontos de entrada no `pyproject.toml` (`pyssh`, `pyssh-cli`).
* [ ] Avaliar distribuição para outras distribuições Linux (PKGBUILD/AUR, pipx).
* [ ] Criar o arquivo `LICENSE` (MIT, já declarado no README).

## 14. Critérios de conclusão do MVP

1. [x] O scanner localiza dispositivos com a porta selecionada aberta.
2. [x] `8022` é a porta padrão, mas pode ser alterada.
3. [x] GUI e CLI compartilham o mesmo núcleo.
4. [x] O usuário pode salvar, editar e excluir conexões.
5. [x] O usuário pode cadastrar referências a chaves SSH e associá-las a conexões.
6. [x] A autenticação é executada pelo OpenSSH.
7. [x] O histórico é salvo localmente e pode ser exportado.
8. [x] A GUI exibe erros e eventos em tempo real.
9. [x] As sessões SSH abertas sobrevivem ao encerramento da GUI.
10. [x] A CLI funciona sem ambiente gráfico.
11. [x] Nenhum segredo de autenticação é gravado nos arquivos de dados ou no histórico.

## 15. Ordem de desenvolvimento

1. [x] Núcleo de rede e scanner.
2. [x] CLI básica.
3. [x] Armazenamento JSON e CRUD de conexões.
4. [x] Gerenciamento de referências a chaves SSH.
5. [x] Histórico JSONL e exportação CSV.
6. [x] Interface gráfica e painel de logs.
7. [x] Sessões SSH independentes.
8. [x] Testes, documentação e distribuição.

**Princípio do projeto:** manter o `pyssh` leve e modular, usando os recursos
nativos do OpenSSH sempre que possível e arquivos locais simples para
persistência.
