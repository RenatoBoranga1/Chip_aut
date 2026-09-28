# Milestone 8 — arquitetura multi-parceiro

Data: 28/09/2026. Branch: `milestone-3-wr-motos-wip`.
Referência inicial: `796543b6f15cfa162bc2ee095e30dee17b47b522`.

**Nenhum novo parceiro foi integrado neste milestone.**
Somente WR Motos continua registrada e habilitada na configuração de produção.

## Baseline e testes

- Baseline anterior às alterações: **706 testes aprovados**, 186,34 s.
- Regressão intermediária dos 706 testes anteriores: 706 aprovados, 196,62 s.
- Testes novos de arquitetura: **35 aprovados**, 9,00 s.
- Suíte final completa: **741 testes aprovados**, 140,90 s.
- Ruff check, Ruff format --check, compileall, imports principais e diff --check aprovados.

Os testes existentes foram preservados. Expectativas da versão do schema passaram
para 12; a fixture de upgrade concorrente prepara também a migration 012. A fixture
compartilhada de coleta agora atribui à coleção a origem dos anúncios (antes fixava
WR até quando os próprios testes criavam anúncios de outra origem).

## Contrato, registry e WR Motos

`PartnerAdapter` estende o contrato legado `PartnerCollector`, oferecendo `collect`,
`normalize_ad`, identidade, habilitação e capacidades opcionais. `PartnerMotorcycle`
permanece o modelo canônico: não foi criada outra representação paralela. A camada
de persistência continua mantendo primeira/última aparição e dados originais.

`PartnerRegistry` valida chaves, duplicações, fábricas explícitas, habilitação e
capacidade de concorrência. Lê `config/partners.json` (ou `MOTO_PARTNERS_CONFIG`).
Não importa código arbitrário indicado em JSON. Consultar/instanciar não coleta.
A lista de habilitados prepara extensão futura, sem orquestrador de múltiplos sites.

WR implementa o contrato e sua fábrica de transporte. Normalização delega à mesma
função anterior. Paginação, filtros 0/1, IDs, evidências, imagens, cache do catálogo,
matching e tratamento de zero km indefinido permanecem preservados.

## Pipeline, scheduler, locks e limites

`run_pipeline(..., partner_key=...)` concentra a execução comum. Estoque anterior,
IDs conhecidos, fingerprint (inclusive catálogo vazio), cobertura anterior,
reutilização, recuperação e histórico são filtrados por parceiro. Publicação de
coleta/matching/revisão permanece atômica; falha não prova desaparecimento.

`app.scheduler start/run-now/status/history --partner wr_motos` seleciona o parceiro.
A solicitação do dashboard também encaminha essa chave. Locks de execução e do
scheduler incluem a chave; apenas migrations mantêm coordenação global de schema.
A recuperação de um parceiro não cancela execução pendente de outro.

Configuração WR preservada: intervalo 2 s, timeout 30 s, 2 retries transitórios,
concorrência 1 e limite 100 páginas. Calendário/backoff permanecem no scheduler;
limites de transporte e retry da execução normal vêm do parceiro. O coletor WR
continua sequencial. Concorrência acima da capacidade declarada é recusada.

Histórico registra parceiro, início, fim, situação, duração, quantidade, novos,
reencontrados, retornos após ausência, desaparecidos e erros. `collector_factory`
continua sendo a injeção legada de testes com limites explícitos do SchedulerConfig.

## Persistência e compatibilidade

Migration **012_partner_architecture.sql** é aditiva. Migrations 001–011 intactas.
Adiciona parceiro às execuções antigas com padrão WR, chave idempotente por parceiro
e tabela `scheduler_partners`. Mantém `request_key` e `scheduler_state` antigos para
preservar dados; consultas reconhecem bancos anteriores sem migrá-los.

Anúncios e observações já utilizavam `(partner, external_id)`. Agora a publicação
valida também origem de todos os anúncios, IDs presentes e duplicados no lote.
Dois parceiros podem ter o mesmo ID e a mesma chave de solicitação sem colisão.

## Alertas, revisão e desenvolvimento

Deduplicação de alertas inclui parceiro. Sequência de falhas, alertas de decisões
vencidas, encerramento de condições e pendências são isolados. Uma entrega com
falha mantém a ordem do próprio parceiro, mas permite processar outro.

A regra humana do M7.1 não foi alterada: novo anúncio não significa nova moto;
ausência automática não significa ausência confirmada. Uma confirmação em WR não
é aplicada à revisão de outro parceiro. Matching e suporte continuam separados.

Desenvolvimento preserva origens múltiplas e suas regras de identidade. Listagem,
contadores e opções respeitam o filtro do parceiro. A origem da foto é recuperada
pelas observações, independentemente do filtro usado para um item compartilhado.

## Dashboard, imagens, métricas e CLI

O seletor vem do registry e mostra apenas WR Motos na operação atual. Nova página
**Parceiros**: nome, chave, habilitação, última coleta, situação, anúncios ativos,
erros recentes (30 execuções; sem execução, última coleta). Estoque, revisão,
oportunidades, alertas, histórico e desenvolvimento usam o parceiro selecionado.
`partner_status()` permite métricas agrupadas sem escrita no banco.

Cache de imagens em memória/disco usa parceiro, URL e tamanho. WR conserva os
nomes antigos para não perder cache. Download usa hosts permitidos por parceiro;
continuam limites de formato/tamanho/tempo e validações de URL, DNS e redirects.
Quota de disco é global, sem crescimento ilimitado por parceiro.

CLI adicionada: `python -m app.partners list`, `status`, `show wr_motos`.
A conferência em servidor real detectou colisão entre `app/partners.py` e o pacote
`partners` na ordem de imports do Streamlit. Corrigida e coberta por teste em
processo novo, além da verificação no navegador.

## FakePartnerAdapter e validação local

O adapter fictício existe somente em `tests/test_partner_architecture.py` e não
foi inserido no registry de produção. Testes cobrem configuração inválida/desabilitada,
do registry com duas origens aos efeitos reais em SQLite: ID igual, idempotência,
locks, recuperação, falha independente, histórico, alertas, revisão humana,
desenvolvimento, imagens, limites, migration e UI/CLI. Não usam outro site.

Browser: Edge headless com Playwright, servidor Streamlit em modo somente leitura.
Oito telas aprovadas: Parceiros, Estoque WR Motos, Fila de revisão, Possíveis novas
motos, Alertas, Histórico, Motos para desenvolvimento e Atualização automática.
Sem erros de JavaScript/console; botão de execução manual desabilitado. Evidências
locais ignoradas em `reports/milestone-8-architecture` (JSON e screenshots).

## Validação dos dados reais

Não foi feita nova coleta, pesquisa de parceiro ou integração externa.
Banco observado na auditoria: schema 11, 171 anúncios ativos WR, 154 itens de revisão.
A migration para 12 foi aplicada apenas em cópia de validação. Todos os valores das
colunas históricas foram comparados e preservados. `integrity_check=ok` e
`foreign_key_check` vazio na cópia; integridade do original também aprovada.

Hash lógico do banco original antes/depois das consultas de validação:
`3ce061697c03113686625f496b37144ca2103caa4cbb8da854a764e133bff250`.
Hash da planilha original:
`32aac84eedec3e8b34e48920bc4bf03c17ccc773886cd84490d2e6f64f57cfdc`.
Nenhuma fixture ou decisão humana foi gravada no banco real.

## Documentação e arquivos

README atualizado; guia `docs/COMO_ADICIONAR_PARCEIRO.md` explica contrato, registro,
configuração, segurança, persistência, imagens, scheduler e testes para extensão futura.

Arquivos novos: `partners/config.py`, `config/partners.json`, `app/partners.py`,
`services/partner_service.py`, `database/migrations/012_partner_architecture.sql`,
`tests/test_partner_architecture.py`, guia e este relatório.

Alterações nos contratos/WR/registry; serviços de pipeline, collection, scheduler,
alertas, locks e imagens; repositórios de pipeline, parceiros, alertas e desenvolvimento;
dashboard e seus painéis; traduções; expectativas de schema nos testes anteriores;
README e padrões de lock no `.gitignore`.

## Limites operacionais e Git

- Só WR está integrada; segundo adapter é exclusivamente fixture.
- Não há execução automática de todos os parceiros em um único processo; cada
  scheduler recebe uma chave. Configuração de parceiros é lida na inicialização:
  reinicie o processo após alterar esse arquivo.
- SQLite continua serializando escritores; locks distintos não tornam escrita
  SQLite paralela. Pare processos da versão antiga antes de atualizar os locks.
- A primeira escrita autorizada aplica migrations ao banco operacional; a validação
  deste milestone usou cópia. Faça backup operacional antes de atualizar.
- `app.collect` mantém opções legadas específicas dos transportes WR; novos adapters
  devem usar o pipeline comum e implementar a própria fábrica de transporte.
- Nenhum login, CAPTCHA, integração de outro site, consolidação real cross-partner,
  ranking ou alteração do Excel foi implementado.
- Commit previsto: `feat: prepare multi-partner collection architecture`.
  Push somente para `milestone-3-wr-motos-wip`; nenhum merge em main.
  SHA e confirmação remota são informados na entrega final.
