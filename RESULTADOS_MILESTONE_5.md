# Milestone 5 — Agendamento e atualização automática

23/09/2026. Continuação de `56c04af`, branch `milestone-3-wr-motos-wip`.
Baseline: **390 testes aprovados**. Entrega: **439 aprovados**, com 49 novos casos.
Sem merge em main.

## Arquitetura e fluxo

Biblioteca padrão Python: laço interrompível, `threading.Event`, `datetime`,
`zoneinfo` e bloqueio do sistema operacional. Dependência explícita
`tzdata==2026.4` garante os fusos no Windows. Não depende de Streamlit, cron ou
systemd para agendar.

`app.scheduler` → `scheduler_service` → `pipeline_service.run_pipeline` → coletor
WR existente → persistência → `build_coverage` existente → matching, fila e memória
válida → cobertura. A CLI manual e o botão do painel usam o mesmo pipeline.
O agendador apenas dispara. Nenhuma regra de parsing, matching ou decisão humana
foi duplicada na coordenação ou no frontend.

Uma execução adquire bloqueio, registra início, coleta, valida completude, publica
o resultado, registra fim e libera o bloqueio. Sinal de atividade corre durante
o trabalho. A base vigente do scanner é usada sem importação automática.

`atomic_database` é uma unidade de trabalho opcional: os repositórios existentes
compartilham uma conexão/transação dentro desse contexto. Seu uso independente
mantém o comportamento anterior. Coleta, anúncios, matching, fila, ocorrências e
cobertura são revertidos se uma etapa falhar. O histórico da execução registra
a falha separadamente. A rede é consultada antes da transação.

Coletas parciais/incompletas não são publicadas. Erros ficam no histórico e
evidências de rede na pasta da tentativa. Erro não equivale a catálogo vazio.
Catálogo completo explicitamente vazio mantém a semântica de desaparecimento.

## Bloqueio, recuperação e concorrência

Bloqueio exclusivo por caminho resolvido do SQLite: `msvcrt.locking` no Windows,
`flock` nos demais sistemas. O arquivo não é removido. A posse pertence ao processo,
não à idade do arquivo. A morte do processo libera o bloqueio pelo sistema
operacional. Só após obtê-lo a próxima execução marca antigos RUNNING como
CANCELLED, com data e duração. Sinal antigo nunca permite tomar um bloqueio vivo.

Há bloqueios separados para um único agendador e para serializar migrations.
A CLI antiga de coleta participa do bloqueio operacional. Uma segunda atualização
registra SKIPPED_ALREADY_RUNNING. Solicitações concorrentes com a mesma chave
retornam um único registro. Processo vivo travado exige intervenção do operador.

## Configuração e operação

`config/scheduler.json` define habilitação, fuso, frequência diária ou intervalo,
horário, tentativas, espera, sinal de atividade, limites de coleta e caminhos.
Padrão: diariamente às 07:00, America/Sao_Paulo. O arquivo habilitado não inicia
um serviço sozinho: o processo precisa estar em execução.

```powershell
python -m app.scheduler validate-config
python -m app.scheduler start
python -m app.scheduler run-now
python -m app.run_pipeline
python -m app.scheduler status
python -m app.scheduler history
```

`--db` / `MOTO_DB` e `--config` / `MOTO_SCHEDULER_CONFIG` configuram caminhos.
`--json` fornece saída técnica. `enabled=false` desliga recorrência sem impedir
execução manual. Ctrl+C encerra. Configuração é recarregada entre execuções.

Banco e novos logs usam UTC. Próximo horário é exibido no fuso configurado.
Intervalos medem tempo UTC. Horário diário ambíguo usa a primeira ocorrência;
horário inexistente avança pela transição. Ocorrências vencidas são condensadas
em uma atualização, sem rajada de compensação. O próximo horário é salvo antes
do disparo: uma queda nesse pequeno intervalo pode perder uma ocorrência, mas
não dispara duplicações de recuperação.

## Tentativas, idempotência, histórico e logs

Novas tentativas limitadas a timeout, conexão e 5xx reconhecidos. Padrão: duas além
da inicial, espera exponencial com teto de 300 segundos. 401/403/429, desafios,
erro de parsing e mudança de contrato interrompem sem contorno.

Migração 008 cria `pipeline_runs` e `scheduler_state`: início/fim, duração, sinal
de atividade, origem manual/agendada, coleta, anúncios antes/depois, diferenças,
matching, fila, cobertura, avisos, erros e hash de configuração. Migrations 001–007
permanecem intactas. RUNNING, SUCCESS, PARTIAL_SUCCESS, FAILED,
SKIPPED_ALREADY_RUNNING e CANCELLED são traduzidos na interface.
PARTIAL_SUCCESS significa publicação com avisos ou recuperação de falha transitória;
nunca autorização para publicar coleta incompleta.

Chave única evita repetir clique/horário. A impressão dos dados relevantes,
versão da base, regras e decisões permite reutilizar cobertura sem novos registros
de matching ou pendências. Mudança de base, memória ou anúncio exige reavaliação.
Timestamp e HTML de transporte não alteram essa impressão.

Repetir a mesma observação não incrementa verificações. Observação mais recente
com dados iguais atualiza last_seen e uma verificação, sem novo matching ou
decisão. A coleta anterior permanece como origem dos dados; a nova verificação
fica no histórico do pipeline. “Reaparecidos” conserva o sentido anterior de IDs
reencontrados; `returned` distingue retorno após ausência.

Logs: 2 MB e três cópias anteriores. SQLite e relatórios/HTML não têm descarte
automático. Se o banco não aceitar registro de falha, o comando retorna erro e
o diagnóstico fica na CLI/log, sem inventar histórico ou indicar sucesso.

## Dashboard

Nova página “Atualização automática”: estado real do processo, próxima execução,
histórico paginado, duração, anúncios, diferenças, falhas, avisos e detalhes.
Sinal ausente não é apresentado como processo ativo. O botão inicia outro
processo Python; a atualização não depende da sessão Streamlit. Reexecuções da
mesma solicitação reutilizam a chave. Somente leitura desabilita o disparo também
no serviço. A tela consulta mudanças a cada 15 segundos.

Textos novos seguem `ui/textos.py`. As nove páginas anteriores foram preservadas.
O painel não mantém o agendador vivo.

## Validação

49 novos testes sem site real: execução completa, falha/parcial, rollback,
idempotência, observação nova sem novo matching, concorrência, morte de processo,
recuperação de bloqueio órfão, bloqueio vivo antigo, atividade, tentativas e
recuperação, memória vigente/obsoleta, diferenças de anúncios, banco indisponível,
configuração, fusos, transição de horário, origem agendada, compensação limitada,
migration concorrente, CLI, histórico e botão do painel.

**439 testes aprovados**. Ruff, formatação, compilação, imports, migration 008,
integridade SQLite e chaves estrangeiras aprovados. Testes antigos mantidos;
expectativas de versão de migration e do rótulo “Falhou” foram atualizadas.

Smoke do agendador em processo Python separado: estado ativo observado, próximo
horário calculado e encerramento limpo, sem site. AppTest verificou disparo, chave
estável e somente leitura. Playwright/Edge abriu dez páginas na base real, exibiu
a execução concluída e verificou o botão desabilitado, sem erro de página.
agent-browser indisponível; usado navegador instalado. Captura inspecionada.

## Execução real controlada

Backup: `reports/milestone-5/before.sqlite3`. Execução 1, manual, coleta 4,
23/09/2026, 10:53:51–10:54:42 UTC. **50,572 segundos**, uma tentativa, zero erros.
Resultado: **Concluída com avisos** pelo conflito dos filtros de 0 km.

| Indicador | Antes | Depois |
|---|---:|---:|
| Anúncios | 158 | 170 |
| Pendências | 142 | 152 |
| Prioridade alta / média | 57 / 85 | 61 / 91 |
| Exatos | 54 | 57 |
| Revisão | 43 | 47 |
| Ambíguos | 8 | 9 |
| Não encontrados | 53 | 57 |
| Suportados | 16 | 18 |
| Sem suporte | 3 | 3 |
| Suporte parcial | 1 | 1 |
| Situação não definida | 34 | 35 |
| Decisões humanas | 0 | 0 |

**12 novos, 158 reencontrados, zero retornados após ausência e zero desaparecidos.**
170 avisos de conflito entre 0 km e usados. Os 56 casos de identidade pendente
(47 revisão + 9 ambíguos) não foram tratados como sem suporte. Nenhuma decisão
humana criada. Repetir a chave real retornou a execução 1 sem outra coleta.

Hashes comprovaram preservação da base importada, memórias, decisões e registros
históricos anteriores. SQLite íntegro e sem erros de FK. Excel preservado:
`32aac84eedec3e8b34e48920bc4bf03c17ccc773886cd84490d2e6f64f57cfdc`.
Evidências locais em `reports/milestone-5/`, ignoradas pelo Git.

## Arquivos e limites

Novos: `app/scheduler.py`, `app/run_pipeline.py`, serviços `pipeline_service`,
`scheduler_service`, `scheduler_config`, `pipeline_lock`, repositório
`pipeline_repository`, `database/transaction.py`, migration 008,
`config/scheduler.json`, `ui/pipeline_panel.py` e `tests/test_pipeline.py`.
Integrações: repository base, coleta, dashboard, traduções, dependências e README.

Bloqueios são locais ao mesmo caminho resolvido. Compartilhamento de rede,
múltiplas máquinas, Linux e Docker não foram validados. Processo vivo travado
não é encerrado automaticamente. Arquivos de relatório não participam da
transação SQLite: pastas de execuções FAILED não representam publicação válida.
SQLite é a fonte oficial.

O agendador não foi deixado permanentemente ativo; inicie `app.scheduler start`
para ativar recorrência. O teste real foi único. Não há serviço Windows definitivo,
inicialização no boot, notificações, novos parceiros, atualização automática da
planilha, autenticação corporativa ou deploy.

Referências: [bloqueio Windows](https://docs.python.org/3/library/msvcrt.html) e
[fusos IANA](https://docs.python.org/3/library/zoneinfo.html).
