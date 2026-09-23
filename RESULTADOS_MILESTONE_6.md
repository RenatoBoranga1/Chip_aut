# Milestone 6 — Alertas operacionais

23/09/2026. Continuação de `a90ed29` na branch `milestone-3-wr-motos-wip`.
Baseline executada: **439 testes aprovados**. Entrega: **497 testes**, sendo
**58 novos**. Sem merge em main. Milestones anteriores preservados.

## Inspeção e arquitetura

README e relatórios 3.2, 4.1 e 5 foram lidos; pipeline, scheduler, coleta,
matching, fila, memória, cobertura, repositórios, migrations, UI e testes
foram inspecionados. Já existiam diferenças de estoque, resultados efetivos,
prioridade da fila, eventos de invalidação, versões da base e execuções com
erros/avisos. A camada nova usa essas evidências sem duplicar matching.

`pipeline → entrega pendente → alert_service → alert_repository → dashboard`

A entrega pendente guarda contexto e referência à cobertura histórica na mesma
transação do estado terminal do pipeline. Depois do commit, a geração/persistência
do lote de alertas usa outra transação. Se falhar, todo o lote é revertido; a coleta
publicada permanece válida. Erro específico fica no resumo, registro local e entrega
pendente. Tentativa seguinte reprocessa primeiro os pendentes, na ordem de execução.
Também há `python -m app.alerts --db data/coverage.sqlite3`, sem nova coleta.

Falhas de coleta/publicação geram alertas a partir da execução falha, sem emitir
novidades de anúncios não publicados. A entrega é registrada junto à falha.
Problemas de banco que impeçam registrar a própria transação não são apresentados
como geração bem-sucedida. Logs preservam o diagnóstico; UI não mostra stack trace.

Não foi adicionada dependência. Scheduler continua em processo independente,
execução manual/agendada usa o mesmo pipeline, e bloqueios do Milestone 5 permanecem.

## Migração e auditoria

Migration **009_alerts.sql**, aditiva; 001–008 intactas:

- `alerts`: tipo, severidade, situação, parceiro/entidades relacionadas, título,
  mensagem, evidências, primeira/última ocorrência, contador e timestamps das ações.
- `alert_occurrences`: evidência por ocorrência, execução e chave de evento única.
- `alert_history`: criado, lido, não lido, arquivado, resolvido, reaberto e condição
  encerrada; triggers recusam alteração/exclusão do histórico.
- `alert_deliveries`: contexto persistido, tentativas, erro e data de processamento.

Ações de alerta escrevem apenas em suas tabelas. Nenhuma confirmação, rejeição ou
ausência humana é criada. O suporte e a identidade não mudam ao resolver um alerta.
Datas são UTC; a interface informa isso. Não existe descarte automático.

## Tipos e regras

| Tipo | Evidência exigida | Prioridade inicial |
|---|---|---|
| Novo anúncio | ID nunca persistido anteriormente | Informativo se suportado; Atenção nos demais |
| Possível nova moto | Novo, bem interpretado e não encontrado; ou provável ausência pelas regras existentes | Alta |
| Sem suporte | Identidade vinculada sem revisão pendente e status efetivo SEM_SUPORTE | Alta |
| Suporte parcial | Mesma exigência de identidade e SUPORTE_PARCIAL | Alta |
| Revisão de alta prioridade | Novo item da fila com prioridade alta | Alta |
| Decisão desatualizada | Evento de invalidação de decisão com motivo e versões da base | Alta |
| Falha de coleta | Execução falha na etapa de coleta | Atenção; escalável |
| Falha de atualização | Execução do pipeline falha | Atenção; escalável |
| Coleta incompleta/com avisos | Coleta parcial recusada, ou execução publicada com avisos | Atenção |
| Nova versão da base | Base da cobertura anterior diferente da atual | Informativo |

Os detalhes guardam anúncio, matching efetivo, cobertura, sistemas suportados,
sem suporte, em análise e sem situação definida quando houver identidade vinculada.
Decisão desatualizada inclui ação anterior, identificador, motivo e versões.
Falhas incluem etapa, data, resumo operacional, tentativas e previsão registrada.

Ausência provável não é ausência confirmada, e não encontrado não é SEM_SUPORTE.
Fuzzy/ambiguidade não gera alerta de suporte a partir do status de um candidato.
Anúncios com campos ausentes ou avisos de interpretação não geram possível nova moto;
o conflito já conhecido de filtros 0 km não invalida a identidade por si só.

`PARTIAL_SUCCESS` continua permitindo apenas publicação completa com avisos ou
recuperação de erro transitório. O alerta distingue publicação com avisos de coleta
incompleta recusada. Não transforma erro em desaparecimento.

## Severidade, configuração e deduplicação

`config/alerts.json`, substituível por `MOTO_ALERTS_CONFIG`, concentra habilitação
geral e de cada regra, além de `failure_high_after=3` e
`failure_critical_after=5`. Tipos/valores são validados. Configuração efetiva fica
salva no resumo da entrega. Configuração inválida deixa entregas pendentes.

Severidades: Informativo, Atenção, Alta prioridade e Crítico. Falhas consecutivas
de execuções concluídas começam em Atenção, atingem Alta na terceira e Crítico na
quinta. Novas tentativas internas não contam como novas execuções. Sequências de
coleta e pipeline são independentes; sucesso interrompe a sequência correspondente.
Solicitações ignoradas/canceladas não contam como falhas concluídas.

Chave estável: tipo + parceiro + entidade. Suporte e possível ausência incluem
versão da base; novidade usa anúncio, revisão usa item, invalidação usa decisão e
nova base. A ocorrência tem outra chave única: repetir a entrega/observação não
incrementa contadores. Observação realmente nova atualiza last_seen e contador.
Falhas/avisos contam uma vez por execução. Há constraint e transação para impedir
duplicação mesmo no reprocessamento concorrente.

Uma condição contínua não reabre alerta arquivado ou resolvido. Uma execução válida
que deixe de observar a condição marca seu encerramento, preservando a situação
escolhida pelo usuário. Retorno em nova observação reabre como Novo, com histórico.
Também há reabertura explícita. Mudança de versão pode justificar nova chave.
Novidades de anúncio/revisão/base/invalidação são eventos únicos.

Desabilitar alertas consome a entrega com indicação de desabilitado; não gera
novidades retroativas ao reativar. Alertas existentes não são apagados.

## Interface e operação

Página **Alertas**, indicador lateral e métricas: novos, alta prioridade, críticos,
não lidos e arquivados. Filtros de situação, severidade, tipo, fabricante, parceiro,
período e leitura. Ordenação padrão por severidade, não lidos e recentes; alternativas
por data/título. Paginação de 30 registros.

Detalhe inclui evidências, ocorrências, histórico e links para anúncio, item de
revisão e execução relacionada, inclusive fora da página recente de execuções.
Ações: marcar como lido/não lido, arquivar, resolver e reabrir. Somente leitura é
validado na apresentação e no serviço. Enumerações novas ficam em `ui/textos.py`;
chave de deduplicação e nomes técnicos não são exibidos.

O painel de atualização mostra alertas criados/atualizados e erro específico de
geração. A consulta periódica considera a conclusão da entrega de alertas, além
do estado do pipeline, para refletir a publicação posterior.

## Testes e verificações

**439 → 497 aprovados**, com 58 novos testes. Testes anteriores mantidos; apenas
expectativas de migration foram atualizadas para 9. Casos novos cobrem:

- 12 anúncios novos em fixture, ausência de repetição e anúncios legados;
- possível ausência, identidade insuficiente, suporte real e candidato ambíguo;
- alta prioridade, memória stale, versões e preservação das decisões humanas;
- ocorrências, idempotência, repetição de chave e reprocessamento concorrente;
- leitura, arquivamento, resolução, reabertura, parceiro e modo somente leitura;
- falhas de coleta/publicação, parcial, avisos, retries e escalada configurável;
- rollback de lote de alertas com pipeline preservado e recuperação posterior;
- configuração inválida/desabilitada, filtros, ordenação, CLI e migração;
- central Streamlit, seis ações, traduções e navegação para revisão/execução.

Ruff, formatação, compileall, imports principais, integridade e chaves estrangeiras
SQLite aprovados. Smoke independente do scheduler observou atividade, próxima
execução e encerramento limpo sem acessar o catálogo.

Verificação visual com Playwright/Edge: home, central, detalhe, botão somente leitura
e execução relacionada. Sem erros de página ou console no fluxo final. Capturas
inspecionadas; textos padrão dos filtros corrigidos para português. `agent-browser`
indisponível. A primeira tentativa teve timeout de abertura; o roteiro genérico de
todas as páginas e o seletor de opções exigiram ajuste. A verificação final focou
o fluxo novo; as páginas anteriores passaram na regressão automatizada.

## Execução real controlada

Backup anterior à migration: `reports/milestone-6/before.sqlite3`.
Uma única coleta real: execução **2**, coleta **5**, manual, de
**16:09:20 a 16:10:11 UTC**, 23/09/2026. Duração registrada do pipeline:
**51,059 segundos**, antes da entrega posterior dos alertas. Uma tentativa, zero
erros; resultado Concluída com avisos pelo conflito dos filtros de 0 km.

| Indicador | Resultado |
|---|---:|
| Anúncios antes / depois | 170 / 171 |
| Novos | 2 |
| Reencontrados | 169 |
| Retornados após ausência | 0 |
| Desaparecidos | 1 |
| Alertas criados / atualizados | 27 / 0 |
| Entregas pendentes | 0 |
| Informativos / Atenção / Alta / Críticos | 0 / 3 / 24 / 0 |
| Decisões humanas criadas | 0 |

| Tipo | Alertas |
|---|---:|
| Possível nova moto | 18 |
| Sem suporte | 3 |
| Suporte parcial | 1 |
| Novo anúncio | 2 |
| Novo item de revisão de alta prioridade | 2 |
| Coleta incompleta/com avisos | 1 |
| Falha, decisão stale ou nova base | 0 |

Os 12 anúncios novos da execução anterior não foram reutilizados como novidade.
As 18 possíveis novas motos incluem condições atuais de provável ausência e os
novos anúncios, não são 18 anúncios novos nem confirmações de falta de suporte.
O alerta de coleta é **publicação completa com 171 avisos de filtros**, não falha
de completude. Como era a primeira entrega de alertas, todos os 27 foram criados.

Matching: 57 exatos, 46 revisão, 9 ambíguos, 59 não encontrados.
Cobertura: 18 suportados, 3 sem suporte, 1 parcial, 35 sem situação definida,
59 não encontrados e 55 com identidade em revisão. Nenhuma ausência humana criada.
Fila da coleta: 153 pendências. Painel/fila persistente: 154, pois conserva também
o histórico pendente do anúncio que desapareceu; 63 altas e 91 médias.

Repetir a mesma chave retornou a execução 2 sem nova coleta e sem alteração em
qualquer tabela. Prefixos históricos de 16 tabelas anteriores preservados, SQLite
íntegro, zero violações de FK e nenhuma decisão humana criada. Excel inalterado:
`32aac84eedec3e8b34e48920bc4bf03c17ccc773886cd84490d2e6f64f57cfdc`.
Evidências em `reports/milestone-6/`, ignoradas pelo Git.

## Arquivos e limites

Criados: migration 009, `database/alert_repository.py`, `services/alert_service.py`,
`services/alert_config.py`, `config/alerts.json`, `ui/alert_panel.py`,
`app/alerts.py`, `tests/test_alerts.py` e este relatório.
Integrações: pipeline, dashboard, painel de atualização, traduções e README.

Somente canal interno. Não há e-mail, WhatsApp, Teams, Slack, notificações móveis,
novo parceiro, autenticação, deploy ou atualização automática do scanner.
Alertas são detectados no pipeline; comandos legados isolados de coleta/cobertura
não publicam notificações imediatamente. Nova versão da base é percebida na próxima
comparação de cobertura pelo pipeline. Pendentes exigem uma próxima execução ou CLI;
não existe outro daemon de entrega. O agendador não ficou permanentemente ativo.

Detalhes preservam evidência histórica; não são recalculados ao navegar. Ações são
auditadas por data e transição, sem identidade autenticada do operador neste ambiente
local. Leituras carregam os alertas do parceiro antes da paginação; escala de milhões
de alertas não foi validada. Não há expurgo ou notificações externas. Banco local
Windows validado; uso distribuído/múltiplas máquinas não foi testado.
