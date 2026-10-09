# TODO — pyssh

> Pendências priorizadas. Estado em **09/10/2026**: Fases 1 e 2 concluídas
> (núcleo + `pyssh-cli`, 89 testes OK). Detalhes em
> [ROADMAP.md](../ROADMAP.md) e [RELATORIO-DESENVOLVIMENTO.md](RELATORIO-DESENVOLVIMENTO.md).

## Ações imediatas

* [ ] Fazer o `git push` dos commits locais ainda não publicados
      (`08aeb1a` núcleo+CLI, `3f1f03e` documentação).
* [ ] Instalar o pacote `tk` (Arch: `sudo pacman -S tk`) — sem ele o Tkinter
      não carrega e a GUI fica inviável de testar (`libtk8.6.so` ausente).
* [ ] Criar o `LICENSE` (MIT) — o README já declara MIT.

## Fase 4 — Interface gráfica (próxima entrega)

* [ ] `main.py` com a janela principal Tkinter/ttk.
* [ ] Campo da faixa de rede (auto-preenchido com `guess_network()`).
* [ ] Campo da porta, preenchido com `8022`, validado antes da busca.
* [ ] Botões **Escanear rede** e **Cancelar busca** (via `threading.Event`).
* [ ] Resultados em `ttk.Treeview` (IP, hostname, porta, estado).
* [ ] Selecionar e copiar um endereço IP.
* [ ] Campo do usuário SSH + botão **Conectar via SSH**.
* [ ] Painel de logs: horário, níveis (info/aviso/erro), limpar e copiar,
      sem bloquear a interface (fila entre threads e `after()`).
* [ ] Mensagem clara quando nenhum dispositivo for encontrado.
* [ ] Fechar a janela finaliza buscas e tarefas auxiliares.

## Fase 5 — Sessões SSH independentes

* [ ] Detectar terminais instalados (kitty, konsole, xfce4-terminal, xterm).
* [ ] Iniciar terminal + `ssh` em processo separado do `pyssh` (sobrevive ao
      fechamento da GUI).
* [ ] Várias sessões simultâneas, encerradas individualmente pelo usuário.
* [ ] Terminal alternativo configurável (`settings.terminal`).
* [ ] Testar fechamento normal **e** forçado da interface.

## Núcleo restante (Fases 3 e 6)

* [ ] Usar `last_network` e a última porta nas buscas (`settings.py` já
      persiste os campos).
* [ ] Seleção de interface de rede na CLI e na GUI.
* [ ] Descoberta complementar por mDNS/Avahi (não substitui a varredura TCP).
* [ ] Suporte a perfis do `~/.ssh/config` (aliases `Host`, `ProxyJump`).

## Fase 7 — Testes restantes

* [ ] Testar a GUI no CachyOS (manual + lógica isolada).
* [ ] Conexão real com o Termux e descoberta após reiniciar o telefone.
* [ ] Várias sessões SSH simultâneas; fechar a GUI durante sessão ativa.
* [ ] Verificar que nenhuma thread de scanner sobrevive ao encerramento.
* [ ] Códigos de saída da CLI em pipelines reais (já cobertos por teste,
      repetir após a Fase 4).

## Fase 8 — Documentação e distribuição

* [ ] Requisitos do sistema e instruções para CachyOS/Arch (`openssh`,
      `tk`, terminal compatível, `iproute2`).
* [ ] Seção de diagnóstico (firewall, ARP, porta errada, Termux adormecido).
* [ ] Arquivo `.desktop` para lançar a GUI.
* [ ] Empacotamento: PKGBUILD/AUR e `pipx install pyssh`.
