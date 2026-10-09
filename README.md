# pyssh

Ferramenta leve para Linux que localiza dispositivos com SSH na rede local
(porta `8022` por padrão — Termux) e prepara conexões por interface gráfica ou
terminal.

> **Status:** Fases 1 e 2 concluídas — núcleo compartilhado e `pyssh-cli`.
> A GUI (`pyssh`) ainda não foi implementada. Veja [ROADMAP.md](ROADMAP.md)
> e o [relatório de desenvolvimento](docs/RELATORIO-DESENVOLVIMENTO.md).

## Requisitos

* Python 3.9+
* `iproute2` (comando `ip`) para descobrir a rede local
* OpenSSH (`ssh`) para as sessões
* Tkinter — **apenas** para a interface gráfica (ainda não implementada)

O núcleo e a futura CLI funcionam **sem Tkinter** e sem bibliotecas de
terceiros.

## Instalação (desenvolvimento)

```bash
git clone git@github.com:charaodaniel/pyssh.git
cd pyssh
python3 -m venv .venv && source .venv/bin/activate
pip install -e .

pyssh-cli --help                          # comando instalado no venv
python -m unittest discover -s tests -t . # 89 testes
```

O `.venv/` já é ignorado pelo Git. Para desativar: `deactivate`.

## Arquitetura

```text
pyssh/
├── pyssh/
│   ├── __init__.py      # versão do pacote
│   ├── network.py       # interfaces, CIDR, validação de host (iproute2)
│   ├── scanner.py       # varredura TCP, timeout, concorrência, cancelamento
│   ├── ssh_client.py    # monta e executa a sessão OpenSSH
│   ├── terminal.py      # detecta terminais e abre sessões independentes
│   ├── gui.py           # janela Tkinter/ttk (só aqui há GUI)
│   └── settings.py      # preferências compartilhadas, porta padrão 8022
├── cli.py               # pyssh-cli (linha de comando)
├── main.py              # pyssh (interface gráfica)
├── pyproject.toml
├── docs/
│   ├── RELATORIO-DESENVOLVIMENTO.md
│   └── TODO.md
├── ROADMAP.md
└── tests/
```

O núcleo **não importa** módulos da GUI. A aplicação gráfica e a CLI
consumirão os mesmos módulos, evitando duplicação de lógica.

## Interface gráfica (Fase 4)

Requer Tkinter do sistema (Arch/CachyOS: `sudo pacman -S tk`). Sem ele,
`pyssh` explica o problema e sugere a CLI (código de saída 4).

```bash
pyssh              # ou: python main.py
pyssh --selftest   # abre e fecha a janela sozinho (verificação)
```

A janela oferece campo da rede (auto-detectada), porta `8022` editável,
usuário SSH, botões **Escanear rede** / **Cancelar busca** / **Conectar via
SSH** / **Copiar IP**, resultados em tabela (IP, hostname, porta, estado) e
um painel de logs com horário e níveis (INFO/AVISO/ERRO), limpar e copiar.

A varredura roda em thread própria e a interface nunca trava; fechar a
janela cancela a busca. A conexão abre um terminal do sistema (kitty,
konsole, xfce4-terminal, alacritty, gnome-terminal, urxvt ou xterm) em
processo separado, então a sessão continua depois de fechar o `pyssh`.

## Uso do núcleo

```python
from pyssh.network import guess_network, validate_network
from pyssh.scanner import scan
from pyssh.settings import DEFAULT_PORT  # 8022

iface = guess_network()                  # Interface | None
faixa = validate_network("192.168.8.0/24")

report = scan(faixa, port=DEFAULT_PORT, timeout=0.5, progress=print)
for host in report.open_hosts:
    print(host.address)                  # ex.: 192.168.8.52:8022
```

Uma porta aberta é apenas um indício de serviço acessível: ela **não**
garante que o serviço seja SSH nem que a autenticação seja aceita.

## pyssh-cli

Depois de `pip install -e .`, o comando `pyssh-cli` fica disponível (também
funciona sem instalar: `python3 cli.py ...`). Não depende de Tkinter nem de
ambiente gráfico.

```bash
# Buscar na rede detectada automaticamente (porta 8022)
pyssh-cli scan

# Buscar numa faixa específica
pyssh-cli scan --network 192.168.8.0/24

# Outra porta, com seleção interativa desativada (uso em scripts)
pyssh-cli scan --network 192.168.8.0/24 --port 22 --no-interactive

# Conectar direto num IP conhecido
pyssh-cli connect 192.168.8.52 --user dev --port 8022

# Passar opções extras ao ssh após o separador --
pyssh-cli connect 192.168.8.52 -- -4 -v

pyssh-cli --help
```

### Modo interativo

Após a busca (em terminal real), a CLI apresenta uma lista numerada:

```text
Dispositivos encontrados:

[1] 192.168.8.52:8022 (Android-2.local)
[2] 192.168.8.71:8022

Selecione um dispositivo (Enter para sair):
```

Enter cancela; a sessão é aberta com o `ssh` do sistema em **seu próprio
terminal**, com autenticação feita pelo usuário. Nenhuma senha é armazenada.
Quando o stdin/stdout não é um terminal (pipe/script), a seleção é pulada.

### Saídas

* Resultados (tabela) → **stdout**; progresso, avisos e erros → **stderr**.
  Assim dá para encadear: `pyssh-cli scan -n 192.168.8.0/24 -q | awk '$1=="IP"{next} $3=="aberta"{print $1}'`.
* `Ctrl+C` cancela a busca e ainda lista o que já foi encontrado.

### Códigos de saída

| Código | Significado |
| --- | --- |
| 0 | sucesso |
| 1 | erro interno inesperado |
| 2 | argumentos ou configuração inválidos |
| 3 | nenhum dispositivo com a porta aberta |
| 4 | OpenSSH ausente ou o `ssh` retornou 255 (falha de conexão/autenticação) |
| 130 | interrompido pelo usuário (Ctrl+C) |
| demais | propagados do próprio `ssh` (saída do shell remoto) |

## Testes

```bash
python3 -m unittest discover -s tests -t .   # 89 testes, ~5 s
```

Os testes usam apenas a biblioteca padrão (`unittest`) e não dependem de
Tkinter, rede externa nem de privilégios: as portas abertas são simuladas
com um servidor TCP local.

## Termux

No telefone, inicie o servidor SSH e mantenha a porta `8022`:

```bash
sshd
```

Depois execute o `pyssh` na máquina desktop para localizar o dispositivo.

## Documentação

* [ROADMAP.md](ROADMAP.md) — fases, pendências e critérios de conclusão.
* [docs/TODO.md](docs/TODO.md) — lista priorizada do que falta fazer.
* [docs/RELATORIO-DESENVOLVIMENTO.md](docs/RELATORIO-DESENVOLVIMENTO.md) —
  relatório técnico: decisões de projeto, verificações executadas, bugs
  corrigidos e próximos passos.

## Licença

MIT
