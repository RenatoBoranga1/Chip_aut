# Milestone 3.2 — fila operacional e memória humana

Continuação de `1a71bf9` em `milestone-3-wr-motos-wip`, sem merge em main.
Baseline executada antes das alterações: **220 testes aprovados**. Base real
preservada: 3.993 registros na versão vigente e 1.337 motos únicas.
Ambiente de validação: Windows, Python 3.14.7, SQLite local.

## Arquitetura e integração

O motor de matching e a memória dos milestones anteriores foram preservados.
A camada operacional projeta os matching_runs sobre anúncios persistidos e aplica
decisões humanas válidas antes de classificar a cobertura efetiva. O fluxo é:

`app.collect → app.coverage → review_items → app.review_queue → review_decisions → próxima cobertura`

A coleta continua separada do matching. Não há execução em background.
`app.coverage` sincroniza a fila na mesma operação de geração do relatório;
`app.refine` faz auditoria automática sem alterar a fila operacional.

Cada entrada do relatório guarda `automatic_result`, `human_decision` e
`effective_result`; o campo legado `matching` permanece automático. O resultado
original de cada execução continua em matching_runs e review_occurrences.
Decisões da nova fila não são copiadas implicitamente para matching_memory legada,
pois isso perderia parceiro, versão da base e escopo do anúncio. A memória legada
continua compondo a saída do motor existente com seu tipo explícito
CONFIRMADO_MANUALMENTE; não foi reinterpretada como uma decisão da fila nova.

## Migração e armazenamento

Nova migration: `database/migrations/006_review_queue.sql`. As migrations 001–005
não foram alteradas. O mecanismo existente aplica a migration numa transação e
registra a versão apenas após sucesso. Reabertura é idempotente.

| Tabela | Responsabilidade |
|---|---|
| review_items | Item por parceiro, external_id e assinatura; anúncio completo, execução, timestamps, estado, prioridade e projeção efetiva |
| review_occurrences | Observação e resultado automático por item/coleta/base/política, com run_id e conteúdo original |
| review_decisions | Eventos humanos imutáveis, com reviewer, nota, candidato, base, políticas, identidade normalizada e decisão anterior |
| review_events | Invalidações por identidade/base e sua proveniência |

Triggers recusam UPDATE/DELETE de decisões. Novas decisões acrescentam eventos e
referenciam a decisão aplicável anterior. Resultados e status derivados no item
podem mudar; fatos históricos não são apagados. Operações usam BEGIN IMMEDIATE
para serializar leitura/decisão/projeção; falhas após insert causam rollback.
Um lote de sincronização é atômico. Matching_runs anteriores ao lote podem existir
se a projeção falhar: o lote pode ser repetido sem duplicar a fila.

## Estados, ações e prioridade

Estados: `pending`, `resolved`, `ignored`, `deferred`, `invalidated`, `reused`.
`invalidated` com evento STALE exige reavaliação. Itens de identidade anterior
ficam inativos, mas permanecem consultáveis. `active` identifica a revisão atual
da identidade, não prova que o anúncio ainda esteja à venda.

| Comando | Decisão | Efeito |
|---|---|---|
| confirm | CONFIRMAR_MATCH | Resolve identidade com uma chave vigente |
| reject | REJEITAR_CANDIDATO | Retira candidato do resultado efetivo; mantém pendente, sem promover outro |
| no-match | NAO_EXISTE_NA_BASE | CONFIRMADO_AUSENTE_NA_BASE, suporte nulo |
| defer | DEIXAR_PENDENTE | Adia localmente; não afirma identidade |
| ignore | IGNORAR | Ignora localmente com justificativa |

Todas exigem reviewer e nota não vazios. Confirm/reject exigem chave da base
vigente, do mesmo fabricante e ano. O humano pode indicar uma chave que o fuzzy
não listou, mas isso não amplia automaticamente o escopo da memória.
A decisão mais recente aplicável determina o efetivo. Rejeições consecutivas
na mesma base se acumulam; confirmação/ausência/defer/ignore posteriores mudam
essa decisão efetiva. Defer/ignore não se propagam a outros anúncios.

Critérios centralizados em `config/review_queue.json`: alta para não encontrada,
SEM_SUPORTE e SUPORTE_PARCIAL; média para as outras pendências, incluindo ambíguos,
revisão, EM_ANALISE e SEM_STATUS; baixa para resolvidos, reaproveitados, ignorados
e adiados. Não há prioridade temporal inferida. Prioridade da revisão não modifica
o status de cobertura: uma confirmação pode resolver identidade e continuar
mostrando SEM_SUPORTE no relatório.

## Memória conservadora e escopo

A assinatura é JSON canônico de parceiro, fabricante normalizado, modelo
normalizado, versão normalizada separadamente e ano válido. Remove somente as
diferenças cosméticas já aceitas pelo projeto (caixa/acentos/espaços/hífens de
modelo). Mantém números, ordem de palavras, versões e tokens de publicidade;
novos aliases não expandem uma decisão antiga. External_id não faz parte dessa
assinatura, mas faz parte da identidade persistente do item.

A decisão registra `memory_scope`:

- `advertisement`: confirmações/rejeições de resultado AMBIGUOUS ou cujo anúncio
  difere em tokens do alvo, além de defer/ignore. Reutiliza apenas o mesmo item,
  com external_id e assinatura idênticos, em coletas futuras.
- `identity`: confirmação/rejeição sem ambiguidade e com os mesmos tokens de
  identidade canônica do alvo; permite reaproveitar entre anúncios de assinatura
  estritamente igual. As regras explícitas de identidade do matching são usadas
  somente para verificar compatibilidade com o alvo, sem alterar a assinatura.
  Uma ambiguidade na nova execução impede o compartilhamento.
- Ausência declarada é por identidade e versão da base. Não se transforma em
  suporte negativo. Identidades incompletas não podem ser confirmadas como ausentes.

Exemplo: uma confirmação de F 900 R explícita pode ser aplicada a outro anúncio
de F-900-R do mesmo parceiro/ano. Uma escolha de F 900 R GT a partir do título
ambíguo F 900 R vale apenas para aquele anúncio. GS/Adventure, R/RR, Standard/Touring,
Limited/Special, ABS, 114/117 e 650/700 não compartilham assinatura.

Não é possível inferir que external_ids diferentes representam a mesma moto
física. O compartilhamento é de identidade do modelo, quando suficientemente
explícita, não de VIN/chassi. A CLI mostra escopo, decisão, item, run e base de origem.

## Mudanças de base e anúncios

Ausências e rejeições valem apenas no import_id original; qualquer nova importação
as torna STALE, mesmo se a planilha tiver conteúdo igual. Confirmações podem
continuar válidas se a chave e o fingerprint de fabricante/modelo/ano do alvo
permanecerem iguais. O suporte é sempre obtido do snapshot atual. Alvo ausente ou
identidade alterada gera STALE_TARGET_REMOVED_OR_CHANGED e resultado de revisão.

A validação ocorre em list/show/decide/sincronização, sem scheduler. Após importar
uma base, a próxima leitura da fila reflete a invalidação; a geração de cobertura
refaz o matching. Sem decisão humana, um automático histórico também exige novo
matching antes de ser tratado como atual. Nenhuma decisão antiga é apagada.

Existe no máximo um item ativo por parceiro/external_id. Nova coleta da mesma
assinatura atualiza last_seen e acrescenta ocorrência. Mudança relevante invalida
o item anterior; mudança apenas de preço preserva o item e registra novos dados.
Reprocessar a mesma coleta/base/política não acrescenta ocorrência duplicada.
Anúncio que desaparece não apaga pendência/histórico; a diferença entre coletas
é registrada separadamente. Coleta parcial/cache não prova desaparecimento.

Para evitar retroceder a fila, projeção operacional de coleta mais antiga que a
observação atual é recusada. Use o relatório histórico salvo ou `--automatic-only`
para recalcular uma auditoria automática sem projeção humana operacional.

## CLI

```powershell
python -m app.collect --fresh
python -m app.coverage 3
python -m app.review_queue list
python -m app.review_queue list --status pending
python -m app.review_queue list --priority high
python -m app.review_queue list --include-inactive
python -m app.review_queue show 123
python -m app.review_queue history 123
python -m app.review_queue confirm 123 --candidate "BMW|R18|2022" --reviewer "Renato" --note "Identidade conferida"
python -m app.review_queue reject 123 --candidate "BMW|R18|2022" --reviewer "Renato" --note "Versão diferente"
python -m app.review_queue no-match 123 --reviewer "Renato" --note "Identidade ausente na versão atual"
python -m app.review_queue defer 123 --reviewer "Renato" --note "Consultar parceiro"
python -m app.review_queue ignore 123 --reviewer "Renato" --note "Fora do escopo"
python -m app.review_queue --db data/coverage.sqlite3 --json list
python -m app.coverage 1 --automatic-only
```

123 e a chave BMW são exemplos, não decisões reais. Opções globais --db/--json
precedem o subcomando da fila. JSON usa escapes Unicode para permanecer legível
por parsers UTF-8 mesmo com pipes Windows em outra codepage. Saída humana mantém
acentos e seções de anúncio, automático, candidatos, efetivo, memória e histórico.
Relatórios materializados não mudam retroativamente: execute cobertura novamente
após decisões para gerar uma nova versão no banco.

## Coleta real e fila

Coleta 3 realizada em 22/09/2026, 11:22 UTC, HTTP público, 14 páginas e zero erros.
Comparação com a coleta 2 imediatamente anterior:

| Indicador | Resultado |
|---|---:|
| Anúncios únicos | 158 |
| Reaparecidos | 158 |
| Novos | 0 |
| Identidade alterada | 0 |
| Dados relevantes alterados | 0 |
| Desaparecidos | 0 |
| Itens na fila | 142 |
| Novos itens após segunda coleta | 0 |
| Ocorrências nas duas coletas | 284 |
| Prioridade alta / média / baixa | 57 / 85 / 0 |
| Decisões humanas reais / reaproveitadas | 0 / 0 |

142 = 53 não encontrados + 43 revisão + 8 ambíguos + 3 SEM_SUPORTE +
1 SUPORTE_PARCIAL + 34 SEM_STATUS. Os 16 exatos SUPORTADO não exigiram fila.
Distribuição de identidade preservada: 54 exatos, 0 prováveis, 43 revisão,
8 ambíguos e 53 não encontrados. Os 14 indícios de ausência do Milestone 3.1
continuam dentro dos 53 não encontrados; não viraram confirmações humanas.
Os filtros 0 KM continuam retornando os mesmos IDs: indefinido e alerta nos 158.
Data_changed compara identidade, texto, preço, km, condição e URL; ignora timestamp
de coleta e metadados transitórios da resposta HTML.

O banco real não recebeu decisões fictícias. Os testes temporários demonstram
reaproveitamento válido e bloqueios. Não há número real de decisões humanas
reaproveitáveis enquanto o usuário não iniciar a revisão.

## Validação

Baseline: 220 testes. Suíte final: **295 testes**, com **75 novos casos**.
Os 220 anteriores continuam presentes; o teste que enumera migrations passou a
incluir a versão 6. Casos adicionais cobrem criação, dedup, ações, obrigatoriedade,
histórico e encadeamento, invalidação, alvo removido, troca de base/status,
mesmo/outro external_id, escopos, fuzzy versus humano, variantes e cilindradas,
CLI, cache, rollback de lote/decisão/migration e reabertura idempotente.

Checks executados: pytest, Ruff, ruff format --check, compileall, imports de todos
os módulos principais, migration 006, integrity_check e foreign_key_check.
SQLite íntegro e sem violações de FK. Banco com versões 1–6, aplicadas uma vez.
As tabelas de importação, motos, snapshots, sistemas, problemas, revisões legadas
e memória legada permaneceram integralmente iguais ao backup inicial. Todas as
observações e execuções históricas anteriores foram preservadas.
Planilha byte a byte igual a `1a71bf9`, SHA-256:
`32aac84eedec3e8b34e48920bc4bf03c17ccc773886cd84490d2e6f64f57cfdc`.

Evidências locais ignoradas pelo Git: `reports/milestone-3-2/validation.json`,
`before/`, `collections/` e `after/collection-0003/coverage.json` e `COBERTURA.md`.

## Arquivos principais e limites

Novos: app/review_queue.py, database/review_repository.py,
database/migrations/006_review_queue.sql, matching/review_policy.py,
config/review_queue.json, services/review_service.py e tests/test_review_queue.py.
Integração: app/coverage.py, services/coverage_service.py,
services/refinement_service.py, tests/test_matching.py, README.md e este relatório.

Não foi implementada correção manual de dados do anúncio: dados incompletos
exigem correção na origem/nova coleta, ou defer/ignore. Não há autenticação de
reviewer na CLI local; nome e justificativa são declarações auditadas de quem tem
acesso ao banco. Não há sincronização entre máquinas, dashboard, scheduler,
notificações, parceiros adicionais ou nuvem. Docker/Python 3.12 não executados.
Não há conjunto real de decisões humanas para medir precisão operacional.
