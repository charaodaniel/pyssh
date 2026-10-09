# pyssh — Roadmap do Projeto

> Ferramenta leve para Linux que localiza dispositivos com SSH na rede local e
> permite iniciar conexões por interface gráfica ou terminal.

## Status atual

| Fase | Descrição | Estado |
| --- | --- | --- |
| 1 | Núcleo compartilhado | ✅ concluída |
| 2 | `pyssh-cli` | ✅ concluída |
| 3 | Scanner de rede (amadurecimento) | 🟡 parcial |
| 4 | Interface gráfica (Tkinter/ttk) | ⬜ pendente |
| 5 | Sessões SSH independentes | ⬜ pendente |
| 6 | Configurações e descoberta complementar | 🟡 parcial |
| 7 | Testes | 🟡 parcial |
| 8 | Documentação e distribuição | 🟡 parcial |

## 1. Objetivo

O `pyssh` será desenvolvido em Python e terá duas interfaces:

* **pyssh:** interface gráfica usando Tkinter/ttk.
* **pyssh-cli:** interface de linha de comando para desktops, terminais e
  servidores sem ambiente gráfico.

Ambas compartilharão o mesmo núcleo de descoberta de rede, varredura TCP,
configurações e preparação de conexões SSH.

O primeiro cenário de uso será localizar um telefone Android com Termux e
servidor SSH ativo, normalmente na porta `8022`, mesmo após mudanças de
endereço IP.

O projeto deverá priorizar baixo consumo de recursos, simplicidade,
modularidade e ausência de dependências desnecessárias.

## 2. Tecnologias

* Python 3
* Tkinter/ttk para a interface gráfica
* `socket` para verificações TCP
* `threading` para operações de rede sem bloquear a GUI
* `subprocess` para iniciar OpenSSH e terminais
* `iproute2` para identificação da rede local
* OpenSSH para autenticação e sessões remotas
* Git para versionamento

O núcleo e a CLI deverão funcionar sem Tkinter e sem dependências de
interface gráfica.

## 3. Arquitetura e estrutura de diretórios

```text
pyssh/
├── pyssh/
│   ├── __init__.py
│   ├── network.py
│   ├── scanner.py
│   ├── ssh_client.py
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
    └── test_settings.py
```

### Responsabilidades

* `main.py`: inicialização da interface gráfica.
* `cli.py`: comandos e interação por terminal.
* `network.py`: descoberta e validação de redes e interfaces.
* `scanner.py`: varredura TCP, timeouts e concorrência.
* `ssh_client.py`: inicialização das conexões SSH e terminais independentes.
* `settings.py`: preferências compartilhadas.
* `tests/`: testes automatizados.

O núcleo não deverá importar módulos da GUI. A aplicação gráfica e a CLI
consumirão os mesmos módulos, evitando duplicação da lógica.

## 4. Fase 1 — Núcleo compartilhado ✅

* [x] Criar a estrutura inicial do projeto.
* [x] Implementar a identificação das interfaces de rede (`ip -json addr`).
* [x] Identificar a faixa IPv4/CIDR quando possível.
* [x] Permitir informar manualmente a faixa de rede.
* [x] Validar endereços, portas e timeouts.
* [x] Criar o módulo de scanner TCP.
* [x] Implementar a configuração de porta com padrão `8022`.
* [x] Definir resultados estruturados para os dispositivos encontrados.
* [x] Separar a lógica de rede de qualquer interface.
* [x] Criar testes básicos do núcleo.

**Resultado:** biblioteca interna funcional que poderá ser utilizada pela GUI e
pela CLI.

### API entregue

```python
from pyssh.network import guess_network, validate_network, iter_hosts
from pyssh.scanner import scan, HostResult
from pyssh.settings import Settings, DEFAULT_PORT  # 8022

rede = guess_network()                      # Interface | None
faixa = validate_network("192.168.8.0/24")  # "192.168.8.0/24"

report = scan(faixa, port=8022, timeout=0.5, progress=print)
abertos = report.open_hosts                 # List[HostResult]
```

## 5. Fase 2 — pyssh-cli

### Funcionalidades

* [x] Pesquisar dispositivos em uma faixa de rede.
* [x] Utilizar `8022` como porta padrão.
* [x] Permitir alterar a porta em cada busca (`--port`).
* [x] Exibir IP, hostname quando disponível e estado da porta.
* [x] Mostrar progresso e erros no terminal.
* [x] Permitir cancelar a busca com `Ctrl+C` (código 130, lista o parcial).
* [x] Oferecer seleção interativa dos resultados.
* [x] Permitir conexão direta com um IP conhecido.
* [x] Abrir uma sessão SSH interativa no terminal atual.
* [x] Retornar códigos de saída apropriados para scripts.
* [x] Funcionar sem ambiente gráfico ou Tkinter.

### Exemplos de utilização

```bash
pyssh-cli scan --network 192.168.8.0/24
pyssh-cli scan --network 192.168.8.0/24 --port 22
pyssh-cli connect 192.168.8.52 --user dev --port 8022
pyssh-cli --help
```

### Modo interativo

```text
Dispositivos encontrados:

[1] 192.168.8.52:8022
[2] 192.168.8.71:8022

Selecione um dispositivo:
```

### Compatibilidade com servidores

* [x] Executar sem Tkinter.
* [x] Funcionar em servidores sem desktop.
* [x] Suportar execução por SSH em outra máquina.
* [x] Evitar dependências gráficas.
* [x] Exibir mensagens de erro claras.
* [x] Não armazenar senhas.
* [x] Permitir integração com scripts de administração (stdout/stderr separados
      e códigos de saída).

### Códigos de saída

| Código | Significado |
| --- | --- |
| 0 | sucesso |
| 1 | erro interno inesperado |
| 2 | argumentos ou configuração inválidos |
| 3 | nenhum dispositivo com a porta aberta |
| 4 | OpenSSH ausente ou `ssh` retornou 255 |
| 130 | interrompido pelo usuário (Ctrl+C) |
| demais | propagados do `ssh` |

**Resultado:** busca e conexão disponíveis diretamente no terminal.

## 6. Fase 3 — Scanner de rede

* [x] Percorrer os endereços da faixa selecionada.
* [x] Verificar a disponibilidade da porta TCP configurada.
* [x] Limitar a concorrência para evitar consumo excessivo de recursos.
* [x] Utilizar timeouts configuráveis.
* [ ] Atualizar os resultados progressivamente (callback `progress` pronto;
      falta exibição na GUI).
* [x] Permitir cancelar a busca (`threading.Event`).
* [x] Tratar hosts sem resposta e erros de socket.
* [x] Impedir buscas simultâneas acidentais.
* [x] Identificar os dispositivos que apresentam a porta aberta.

### Configuração da porta

* Porta padrão: `8022`.
* Campo editável na GUI e argumento editável na CLI.
* Intervalo válido: `1` a `65535`.
* A porta utilizada deverá aparecer nos resultados.
* O valor escolhido deverá ser utilizado na conexão SSH.
* Uma porta inválida deverá impedir a busca e produzir uma mensagem clara.

O scanner verificará a acessibilidade TCP da porta. Uma porta aberta é um
indício de serviço acessível, mas não garante que o serviço seja SSH nem que a
autenticação seja aceita.

**Resultado:** descoberta de dispositivos sem depender de endereços IP fixos.

## 7. Fase 4 — Interface gráfica

* [ ] Criar a janela principal com Tkinter/ttk.
* [ ] Adicionar campo para a faixa de rede.
* [ ] Adicionar campo editável para a porta.
* [ ] Preencher a porta com `8022` por padrão.
* [ ] Criar o botão **Escanear rede**.
* [ ] Criar o botão **Cancelar busca**.
* [ ] Exibir os resultados em `ttk.Treeview`.
* [ ] Mostrar IP, hostname quando disponível, porta e estado.
* [ ] Permitir selecionar e copiar um endereço IP.
* [ ] Adicionar campo para o usuário SSH.
* [ ] Criar o botão **Conectar via SSH**.
* [ ] Mostrar progresso sem congelar a interface.
* [ ] Exibir mensagens quando nenhum dispositivo for encontrado.

### Painel de saída

* [ ] Registrar o início e o término das buscas.
* [ ] Informar a rede e a porta utilizadas.
* [ ] Mostrar dispositivos encontrados.
* [ ] Exibir erros de rede, timeouts e configurações inválidas.
* [ ] Informar falhas ao abrir o terminal ou iniciar o SSH.
* [ ] Exibir horário das mensagens.
* [ ] Diferenciar informações, avisos e erros.
* [ ] Permitir limpar e copiar os logs.
* [ ] Nunca registrar senhas ou dados sensíveis de autenticação.

## 8. Fase 5 — Sessões SSH independentes

### Comportamento obrigatório

* [ ] Cada conexão iniciada pela GUI abrirá em um terminal independente.
* [ ] O terminal e o cliente SSH serão iniciados em processos independentes do
      `pyssh`.
* [ ] Fechar a GUI não deverá encerrar as sessões já abertas.
* [ ] O usuário poderá manter várias sessões simultâneas.
* [ ] Cada sessão poderá ser encerrada individualmente.
* [ ] O terminal deverá continuar interativo para comandos e autenticação.
* [ ] O encerramento da GUI deverá finalizar as buscas e tarefas auxiliares.
* [ ] A aplicação não deverá manter processos desnecessários após iniciar a
      conexão.

### Compatibilidade

* [ ] Detectar terminais instalados no sistema.
* [ ] Suportar terminais como Kitty, Konsole e Xfce Terminal quando
      disponíveis.
* [ ] Informar quando nenhum terminal compatível estiver instalado.
* [ ] Permitir configurar um terminal alternativo.

**Critério principal:** depois de iniciar uma conexão, o usuário poderá
encerrar o `pyssh` e continuar trabalhando no terminal independente.

## 9. Fase 6 — Configurações e descoberta complementar

* [x] Salvar preferências básicas (`settings.py`, JSON no `$HOME`).
* [x] Manter `8022` como porta padrão inicial.
* [x] Permitir lembrar a última faixa de rede utilizada (`last_network`).
* [ ] Avaliar lembrar a última porta selecionada.
* [ ] Adicionar descoberta complementar por mDNS/Avahi.
* [ ] Permitir selecionar interfaces de rede diferentes.
* [ ] Adicionar suporte futuro a perfis do `~/.ssh/config`.

## 10. Fase 7 — Testes

* [x] Testar o núcleo sem Tkinter (89 testes, `unittest` da stdlib).
* [x] Testar a CLI em ambiente sem desktop (testes sem Tkinter e sem tty).
* [ ] Testar a GUI no CachyOS.
* [x] Testar a porta padrão `8022`.
* [ ] Testar outras portas e valores inválidos.
* [ ] Testar redes sem dispositivos acessíveis.
* [x] Testar timeout e cancelamento da busca.
* [ ] Testar a atualização de resultados em tempo real.
* [ ] Testar o painel de logs.
* [ ] Testar a conexão com o Termux.
* [ ] Reiniciar o telefone e verificar a descoberta do novo IP.
* [ ] Testar várias sessões SSH simultâneas.
* [ ] Fechar a GUI durante uma sessão ativa.
* [ ] Confirmar que as sessões abertas continuam funcionando.
* [ ] Verificar o encerramento das tarefas de scanner.
* [x] Testar códigos de saída da CLI.

## 11. Fase 8 — Documentação e distribuição

* [x] Criar o README com instalação, arquitetura e exemplos (inicial).
* [ ] Documentar os requisitos do sistema.
* [ ] Incluir instruções para CachyOS/Arch Linux.
* [ ] Documentar a instalação do OpenSSH e de um terminal compatível.
* [ ] Explicar o uso da GUI e da CLI.
* [ ] Documentar o funcionamento em servidores sem desktop.
* [ ] Incluir instruções para diagnóstico.
* [ ] Criar pontos de entrada instaláveis para `pyssh` e `pyssh-cli`.
* [ ] Avaliar um arquivo `.desktop`.
* [ ] Considerar empacotamento para outras distribuições Linux.

## 12. Critérios de conclusão do MVP

1. O núcleo funcionar independentemente das interfaces.
2. A CLI localizar dispositivos com portas abertas sem exigir desktop.
3. A GUI oferecer busca, resultados e painel de logs.
4. A porta `8022` for padrão e editável.
5. Ambas as interfaces apresentarem erros úteis.
6. O usuário puder iniciar uma conexão SSH manualmente autenticada.
7. Fechar a GUI não encerrar sessões abertas nos terminais independentes.
8. A CLI funcionar em ambientes sem Tkinter.
9. O projeto encontrar o telefone após uma mudança de IP.
10. A aplicação não deixar scanners ou tarefas auxiliares executando após o
    encerramento.

## 13. Melhorias futuras

* Histórico de dispositivos encontrados.
* Favoritos para dispositivos conhecidos.
* Exportação de logs.
* Configuração avançada de timeout e concorrência.
* Descoberta por mDNS/Avahi.
* Integração com perfis SSH.
* Empacotamento para outras distribuições.

## 14. Ordem recomendada de implementação

1. ✅ Estrutura do projeto e núcleo compartilhado.
2. ✅ Identificação de rede e scanner TCP.
3. ✅ `pyssh-cli` funcional.
4. ✅ Testes do núcleo e da CLI.
5. Interface gráfica.
6. Painel de logs.
7. Sessões SSH independentes.
8. Testes de encerramento e uso de recursos.
9. Documentação e distribuição.

**Princípio central:** o `pyssh` será uma ferramenta temporária para
descobrir dispositivos e iniciar conexões. Depois de aberta a sessão, o
usuário poderá encerrar a interface gráfica para economizar recursos sem
interromper o trabalho no terminal remoto.
