# Validação técnica — Milestone 3

Continuação de `e7d0274` em `milestone-3-wr-motos-wip`, sem recriar os Milestones
1 e 2 nem alterar o motor de matching. Ambiente: Windows, Python 3.14.7.

## Estado inicial

Leitura de README, validações anteriores, adaptadores, serviços, persistência,
migração 004, CLI e testes antes das alterações. A suíte inicial executou 122
testes: 121 passaram e um falhou. A falha existente era a recuperação do link
do anúncio após alteração de classe HTML; corrigida nesta etapa.

## Validação automatizada

```powershell
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
python -m compileall -q app scanner_base matching database services partners
python -c "import app.import_base, app.match, app.collect, app.coverage, matching.matcher, database.partner_repository, partners.wr_http, partners.wr_browser, services.coverage_service"
```

153 testes passaram. Ruff lint, Ruff format (48 arquivos), compilação e imports
passaram. Suíte principal não acessa o site. Testes existentes foram preservados;
fixtures de transporte agora encerram explicitamente o segundo filtro vazio,
o teste de migração inclui a versão 005 e o helper do parser aplica normalização
separadamente. Não há atualização de regras ou reinterpretação de suporte.

Novas regressões cobrem transporte HTTP, ambos os filtros, limite global,
sequência e repetição de conteúdo/IDs, preço promocional no título, campos de
auditoria, classe HTML alterada com múltiplos links por anúncio, falhas parciais,
HTTP 500/401/403/429/302, desafio, resposta vazia, timeout, cache persistido,
integridade SQLite, grupos de cobertura e manutenção da separação entre suporte
e identidade provável/ambígua.

## Validação operacional

Importação pela CLI existente, duas coletas HTTP controladas (a segunda após
correção do preço promocional), replay por cache e cobertura sobre a base real.
Resultados e evidências ficam exclusivamente em diretórios ignorados pelo Git:

- `reports/import-0001/`: auditoria da planilha original, inclusive SHA-256.
- `reports/collections/`: primeira coleta.
- `reports/collections-final/`: coleta posterior à correção de preço.
- `reports/coverage/`: relatório preliminar e resultados detalhados por anúncio.
- `reports/validation.json`: checks operacionais finais e métricas consolidadas.
- `data/coverage.sqlite3`: runs, observações, first/last_seen e matching.

As contagens reais não são fixtures nem constantes do código. HTML bruto,
relatórios reais, banco e cache não fazem parte do commit. A planilha já
versionada permaneceu intacta.

## Limitações

Classificação 0 km depende da coerência dos filtros publicados. Anúncios nos
dois filtros recebem estado indefinido e aviso, sem inferência por quilometragem.
Completude significa percurso dos dois conjuntos retornados pelo site; não
garante correção dos filtros nem snapshot atômico de um estoque mutável.

Títulos promocionais e versões não estruturadas são preservados para revisão.
Fuzzy não confirma cobertura automaticamente. Revisões humanas e política de
status continuam sendo responsabilidades de negócio. Não houve validação visual
do fallback Playwright, execução Docker/Python 3.12, dashboard ou scheduler.
