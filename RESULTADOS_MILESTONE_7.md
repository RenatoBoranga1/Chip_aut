# Milestone 7 — Gestão de motos para desenvolvimento

24/09/2026. Repositório `RenatoBoranga1/Chip_aut`, branch
`milestone-3-wr-motos-wip`. Início sincronizado em
`d945ff7556431d6b4196726b77ecb85633af69ec`, árvore limpa, fetch e pull fast-forward
sem alterações remotas. Nenhum merge em `main`.

## Inspeção e arquitetura

Baseline executada antes de editar: **598 testes aprovados em 91,83 s**.
README, relatórios 3.2, 6 e 6.1.1, dashboard, fila, memória humana, matching,
alertas, miniaturas, migrations, scheduler e testes foram inspecionados.
`RESULTADOS_MILESTONE_6_1.md` continua ausente no repositório de origem.

Dados reutilizados: anúncios e primeiras/últimas aparições, resultados efetivos da
revisão, prioridades, chaves e sistemas da base, decisões humanas e alertas. A
decisão existente `NAO_EXISTE_NA_BASE` confirma ausência por versão da base, sem
declarar falta de suporte. Nenhuma dessas regras foi reimplementada na interface.

Nova camada: `dashboard/CLI → DevelopmentService → DevelopmentRepository → SQLite`.
A interface apenas apresenta dados e envia comandos. Leituras do desenvolvimento
são feitas em conexão somente leitura. Comandos usam a unidade transacional
existente, autor/justificativa, idempotência e revisão otimista. Falha no histórico,
origem ou alerta reverte a operação inteira. Não há dependência nova.

## Migration e campos

Migration aditiva **011_development.sql**; 001–010 intactas:

| Tabela | Conteúdo |
| --- | --- |
| development_items | Identidade, fabricante/modelo/versão/ano, scanner, base de origem, motivo, situação, prioridade, responsável, criador, datas, revisão, dados técnicos e checklist |
| development_origins | Parceiro, anúncio, revisão/alerta associados, primeiras/últimas aparições, contagem e snapshot da origem |
| development_occurrences | Observações imutáveis, autor e chave de idempotência |
| development_events | Criação, situação, prioridade, atribuição, notas, informações técnicas e checklist; antes/depois, autor, data e justificativa |
| development_commands | Solicitações já aplicadas e hash do conteúdo |
| development_alerts / development_alert_history | Avisos de desenvolvimento e histórico das ações na central |
| development_maintenance | Última verificação de prazos |

Preço, quilometragem, URL, foto e evidência de matching/cobertura ficam nos snapshots
das origens. Notas são eventos append-only. Triggers impedem modificar/apagar
histórico e ocorrências. Índice único parcial impede duas tarefas ativas da mesma
identidade. Migrations continuam transacionais, inclusive em falha da 011.

## Criação e deduplicação

Inclusão somente por pessoa, exigindo confirmação explícita, nome e justificativa.
Não foi implementada regra de criação automática. A origem atual é relida durante
o comando; o cliente não fornece uma suposta classificação de suporte.

Motivos: ausência confirmada, sem suporte, suporte parcial, revisão de alta
prioridade, novo modelo e inclusão manual. Motivos que afirmam ausência ou suporte
só são aceitos com evidência vigente. Inclusão não fabrica uma decisão humana de
matching nem promove candidatos aproximados.

Deduplicação por identidade estrita de fabricante/modelo/versão/ano, usando a entrada
do scanner quando já vinculada com segurança. Imagens, preço e quilometragem não
participam. Mesma identidade explícita pode reunir vários parceiros; ambiguidades,
matching pendente e avisos de interpretação restringem a tarefa ao anúncio. Não
há fusão aproximada. Identidade incompleta é recusada.

Inclusão repetida abre/reutiliza o existente. Uma observação realmente nova registra
origem/ocorrência e atualiza datas e foto de forma auditável, preservando prioridade
e responsável. Repetição da mesma observação não infla contadores. Uma tarefa
encerrada permite outra necessidade futura; reabertura conflitante é recusada.

## Situações e ações

| Situação | Transições |
| --- | --- |
| Nova | Em análise, Descartada |
| Em análise | Aguardando informações, Dados coletados, Descartada |
| Aguardando informações | Em análise, Dados coletados, Descartada |
| Dados coletados | Em análise, Em desenvolvimento, Descartada |
| Em desenvolvimento | Aguardando informações, Em validação, Descartada |
| Em validação | Em desenvolvimento, Concluída, Descartada |
| Concluída / Descartada | Em análise, com justificativa de reabertura |

Conclusão exige responsável atribuído e registra data, autor, justificativa e versão
informada opcional. Atribuição e prioridade alta/média/baixa são editáveis e auditadas.
Formulário mantém a revisão que foi aberta: não sobrescreve uma alteração concorrente
apenas porque o Streamlit executou novamente. A atualização explícita do formulário
permite avaliar os dados novos antes de salvar.

Checklist padrão com oito itens, configurável: identidade, disponibilidade,
informações, comunicação, início, teste, validação e base/scanner atualizado.
Campos técnicos opcionais: protocolo, ECU, sistema eletrônico, conector, cabo,
observações técnicas, fornecedor/parceiro e data de coleta. Edições conservam antes
e depois; notas anteriores não são apagadas. Nomes de responsáveis podem ser livres
ou restritos pela configuração.

Concluir, descartar, reabrir ou marcar checklist não escreve no scanner, não altera
cobertura e não resolve a revisão de identidade. Uma nova base com entrada candidata
gera indicação de possível atendimento para conferência; não vincula nem encerra
automaticamente. Uma ausência declarada numa versão antiga não é mostrada como atual.

## Integrações e painel

- Inclusão no detalhe da revisão e de alertas de motos; seleção nas páginas de
  possíveis novas motos, sem suporte, suporte parcial, inspeção do scanner e busca.
- Item existente mostra acesso direto; registrar outra origem não cria duplicata.
- Página **Motos para desenvolvimento**, com lista de oito por página e métricas
  por situação, total ativo e alta prioridade.
- Filtros: situação, prioridade, responsável, fabricante, ano, motivo, parceiro,
  com/sem foto e texto. Ordenações: prioridade, atualização, antiguidade, modelo e
  situação. Datas compactas e parceiros traduzidos na lista.
- Detalhe: resumo, origens, scanner/cobertura, fluxo, checklist, dados técnicos,
  observações, histórico e alertas relacionados. Eventos/origens paginados em 30.
- Miniaturas reutilizam cache, segurança, limites, fallback e ampliação do 6.1.1.
  Não há segundo sistema de imagens e fotos não influenciam qualquer decisão.
- Listagens não leem todo o histórico, notas ou snapshots de todos os itens.
- Toda a interface nova usa português; códigos internos ficam na persistência/JSON.

Os avisos aparecem na central do Milestone 6: inclusão de alta prioridade, entrada
em validação, conclusão e tempo parado. O adaptador usa identificadores internos
separados para evitar colisão e mostra “Desenvolvimento” na interface. Não fabrica
pipeline/collection IDs. Ações de leitura/arquivamento/resolução e histórico seguem
a central existente; resolver aviso não altera a tarefa.

SLA padrão: aguardando informações >7 dias completos; desenvolvimento >30;
validação >14. A idade usa a entrada no estado, sem ser reiniciada por nota ou
atribuição. Aviso de Atenção único por permanência no estado, sem falha automática.
Scheduler verifica no máximo uma vez por hora quando ativo; CLI `scan` permite
verificação explícita. Navegação não gera avisos nem faz escrita oculta.

## CLI e configuração

`app.development`: `init`, `list`, `show`, `create`, `status`, `priority`, `assign`,
`note`, `technical`, `checklist`, `scan`. Escritas exigem autor e justificativa;
criação exige `--confirm`; alterações exigem `--revision`. `--request-key` permite
repetir de forma idempotente. `--json`, `--db` e `--read-only` são opções globais.
`MOTO_READ_ONLY` é respeitado também pela CLI.

`config/development.json` / `MOTO_DEVELOPMENT_CONFIG`: habilitação, avisos, prazos,
responsáveis e checklist. Configuração inválida não é silenciosamente habilitada.
Exemplos de comandos e transições estão no README.

## Testes e validação

**598 anteriores preservados + 66 novos = 664 testes aprovados**.
As únicas adaptações nos testes anteriores são expectativas de versão de migration
de 10 para 11. A execução completa registrou 76,83 s antes do ajuste final de
apresentação de datas/parceiros; a rodada de liberação é registrada nas evidências locais.

Casos novos: inclusão explícita, evidência dos motivos, ausência expirada,
reconciliação conservadora, origem de revisão/alerta/scanner, vários parceiros,
ambiguidades isoladas, deduplicação concorrente, repetição idempotente, datas/fotos,
transições válidas/inválidas, conclusão com responsável, descarte/reabertura,
prioridade, atribuição, notas, checklist, dados técnicos, configuração, filtros,
métricas, paginação, consultas limitadas, SLA e limitação de frequência, histórico
imutável, rollback de criação/alteração/migration, integridade e somente leitura,
CLI, AppTest de confirmação explícita e formulário concorrente, central e imagens.

Checks: Ruff, formatação, compileall, imports principais, integridade e chaves
estrangeiras SQLite, migrations e `git diff --check`. Nenhuma migration anterior
foi modificada.

### Banco real: somente leitura

Não houve coleta WR Motos, reimportação ou criação de tarefa real. Consulta controlada:
171 anúncios, 154 revisões, zero decisões humanas e zero itens de desenvolvimento.
O banco real permanece na versão 10; a 011 foi exercitada em bancos temporários e
será aplicada na primeira escrita autorizada ou por `app.development init`.

SHA-256 do dump lógico real antes/depois:
`244a95098afa5e9cef8d84246b5ac922e9f5b5af0416b938978fda7d81530f3c`.
Planilha original antes/depois:
`32aac84eedec3e8b34e48920bc4bf03c17ccc773886cd84490d2e6f64f57cfdc`.
SQLite real: integridade `ok`. Nenhuma decisão foi inventada no banco operacional.

### Navegador e desempenho

Banco separado com dez itens sintéticos, identificado como fixture. Smoke com
Playwright/Edge (agent-browser indisponível), servidor novo na porta 8507:
listagem, métricas, filtros com/sem foto, duas páginas, detalhe, transição gravada
e auditada, central de alertas e navegação de volta ao item. Zero erros de página
ou console. Capturas de lista, resumo e detalhe inspecionadas.

Abertura observada da página: **0,971 s** no banco sintético. Não é benchmark de
produção. Ausência e falha de imagem foram verificadas com placeholders, sem
buscar fotos externas para fixtures. Teste unitário confirma uso do carregador
existente e apenas oito imagens do bloco visível.

Evidências locais ignoradas pelo Git: `reports/milestone-7/real-readonly.json`,
`fixture.sqlite3`, `browser.json` e capturas. Nenhum desses dados é versionado.

## Limitações

- Nome do operador declarado localmente, sem autenticação corporativa; o modo
  somente leitura bloqueia comandos de escrita no serviço e na UI.
- Novas origens entram por inclusão explícita; não há ingestão automática de tarefas
  nem fusão posterior assistida de identidades antes ambíguas.
- Reconciliação é indicação conservadora na consulta do detalhe, sem decisão ou
  encerramento automático. Mudança da base requer avaliação humana.
- Indicadores e listas pertencem à fila de desenvolvimento, não à cobertura.
  A fila reúne parceiros; o filtro próprio permite restringir as origens.
- Avisos de prazo precisam do scheduler ativo ou do comando `scan`; abrir o painel
  sozinho mostra idade/atenção, mas não persiste notificações.
- Checklist é declaração operacional e não valida comunicação física, desenvolvimento
  de ECU ou atualização real do scanner.
- Sem Jira, Azure DevOps, autenticação corporativa, aprovação formal, IA, planejamento
  de sprint, estimativa ou escrita automática na planilha.

## Arquivos principais

`database/migrations/011_development.sql`, `database/development_repository.py`,
`database/development_alert_repository.py`, `services/development_service.py`,
`services/development_policy.py`, `services/development_alerts.py`,
`config/development.json`, `ui/development_panel.py`, `app/development.py`,
`tests/test_development.py`; integrações em dashboard, central, scheduler,
configuração de imagens e textos. README atualizado.
