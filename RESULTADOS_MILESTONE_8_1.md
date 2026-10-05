# Resultados — Milestone 8.1

Resultado: avaliação dos três candidatos concluída; nenhum novo collector aprovado. WR permanece integrado. Recursos comuns de acompanhamento e execução multi-parceiro ampliados. Esse resultado segue o critério explícito de não forçar integrações frágeis.

## Estado inicial e testes

- Branch: milestone-3-wr-motos-wip; árvore inicialmente limpa, fetch realizado.
- SHA inicial: b5511e3b1d3b1c0ecac188d1a0810454c3f1ee96.
- Baseline: 948 testes, 275,56 s.
- Final: 972 testes, 272,32 s; todos os 948 anteriores preservados e 24 adicionais.
- Suíte de arquitetura: 35 testes aprovados; novos testes: 24 aprovados, incluindo execução real do pipeline com adapters de fixture, locks independentes e idempotência.
- Ruff check, Ruff format --check, compileall app/services/database/ui e git diff --check aprovados.
- SQLite integrity_check: ok nas cópias de validação e replay. Última migration: 014; nenhuma migration alterada/criada.

## Avaliação e dados reais

| Parceiro | Resultado | Amostra pública | Estoque persistido neste milestone |
|---|---|---|---|
| Moto Marques | Não integrado: HTTP 403 | Bloqueio no acesso/robots; interrompido | Nenhum |
| Thomas | Não integrado: sem critério verificável de tipo | 79 itens, incluindo carro; 2 detalhes e endpoint público de marcas | Nenhum |
| Motonil | Não integrado: categoria/dados insuficientes | 19 itens, incluindo kart e serviço; 1 detalhe | Nenhum |
| WR | Integração preservada | Dados existentes, sem nova consulta de catálogo | 159 ativos existentes |

Amostragem não equivale a coleta operacional nem confirma 79 ou 19 motocicletas. Não houve coleta completa de candidato reprovado. Não se aplicam parsing/coleta em produção ou fixtures de collector aos candidatos, pois não há novos collectors. Não foram feitas decisões humanas, tarefas de desenvolvimento ou alterações manuais de prioridade no banco operacional. A base ativa continua sendo a V16 (import 3).

WR, fotografia existente de 30/09: 14 páginas, 318 ocorrências brutas, 159 IDs únicos, 14 fabricantes, 125 pares fabricante/modelo, anos 2001–2026 (com lacunas). Preço, km e imagem: 159 cada. Condição 0 km: desconhecida em todos, pelo conflito dos dois filtros. Duração histórica de coleta: 48,454 s; não é medição de nova coleta neste milestone. Última diferença: 19 novos, 0 reaparecidos, 31 desaparecidos. Desaparecimento não significa venda.

A avaliação HTTP inicial registrou Thomas listagem 0,90 s, Motonil inicial 1,56 s e Moto Marques robots 0,29 s com 403. São amostras de latência, não SLAs nem tempo de coleta completa. Detalhes técnicos e fontes em docs/AVALIACAO_NOVOS_PARCEIROS.md.

## Arquitetura e comportamento

1. PartnerRegistry mantém apenas WR como collector real. Avaliações ficam separadas em partners/assessments.py. Não há adapters fictícios habilitados.
2. Configuração inclui requests_per_minute, detail_lookup e image_fetch; limites existentes reutilizados, valores conservadores preservados. PartnerAdapter expõe supports_detail_lookup.
3. run-all reutiliza run_pipeline, transações, persistência e locks por parceiro. Testes comprovam execução concorrente, falha isolada, exclusão de desabilitados e mesmo request-key separado por parceiro.
4. Persistência continua (partner, external_id); testes existentes cobrem colisão de IDs, parcial sem falsos desaparecimentos e isolamento de falhas/alertas.
5. Matching continua único; nenhum algoritmo por parceiro nem alteração de normalizador global.
6. Review queue mantém memória e escopo humano. Detalhe mostra origem e ocorrências estritamente compatíveis. Nenhuma decisão é automaticamente copiada.
7. Possíveis novas motos tem consulta consolidada opcional, com quantidade de parceiros/anúncios e detalhes por origem. Casos inseguros ficam separados. Identidades são classes técnicas, não veículos físicos.
8. Desenvolvimento reutiliza identidade e múltiplas origens existentes; teste preservado prova que nova origem não duplica item seguro.
9. Alertas permanecem partner-aware e deduplicados por evento/origem. Não há agrupamento global que esconda desaparecimento específico de um estoque.
10. Indicadores comparam parceiros no mesmo recorte e diferenciam ocorrências de grupos estritos/casos isolados. Pesos de priorização inalterados.
11. Parceiros e CLI mostram Ativo/Desabilitado/Não integrado, motivo, última coleta, ativos, novos, reaparecidos, desaparecidos, duração, falhas e parcial.
12. Menu original preservado: 11 itens visíveis, Possíveis novas motos em terceiro, 5 páginas ocultas ainda internas.

## Performance e validação

Replay **offline** da coleta WR já salva, em cópia SQLite, 159 anúncios, sem HTTP:

| Etapa | Segundos |
|---|---:|
| Ler coleta persistida | 0,0131 |
| Persistir observações | 0,2032 |
| Matching em lote | 0,3103 |
| Sincronizar review queue | 0,3496 |
| Cobertura total (inclui matching/fila) | 0,8710 |
| Consulta de oportunidades consolidadas | 0,6922 |

19 grupos de oportunidades no replay; resultado depende da base e do estado consultado. Não somar etapas inclusivas. Parsing de novos sites: não aplicável. Consulta por parceiro, sem uma consulta adicional por anúncio para obter origens.

Dashboard validado no navegador integrado do Codex, porta local 8532, cópia da base com somente leitura: Visão geral, Parceiros, Possíveis novas motos com consolidação e Indicadores gerenciais com comparação. Comparação mostrou 159 anúncios e 149 identidades estritas/casos isolados no recorte consultado. Ordem do menu confirmada. Sem erros de console registrados. Edge via Playwright não iniciou no ambiente; navegador integrado foi utilizado como alternativa. Artefatos de avaliação, bancos e logs permanecem ignorados em reports/work.

## Limitações e entrega

Não há aumento de estoque monitorado nesta entrega. Thomas e Motonil exigem novo dado/filtro público verificável; Moto Marques exige acesso público permitido. Não inferimos condição novo/usado por quilometragem, selo Novo, fabricante ou título. A política existente de parar em 429 foi preservada. Configuração de imagens controla novas transferências, não apaga cache. Sem autenticação, bypass, scraping agressivo, novos pesos ou outro milestone.

Arquivos principais: partners/config.py, partners/assessments.py, services/multi_partner_service.py, services/partner_identity_service.py, services/partner_service.py, services/management_metrics_service.py, app/scheduler.py, app/partners.py, app/dashboard.py, ui/management_dashboard.py, tests/test_partner_expansion.py e documentação.

Commit e push devem apontar somente para milestone-3-wr-motos-wip. O SHA de entrega é o commit que contém este relatório; SHA exato, confirmação do push e estado final são registrados na resposta de entrega, após a operação. Nenhum merge em main.
