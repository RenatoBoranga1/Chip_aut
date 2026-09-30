# Resultados — Milestone 13: Indicadores e visão gerencial

## Referência e escopo

- Repositório: RenatoBoranga1/Chip_aut.
- Branch: milestone-3-wr-motos-wip.
- SHA inicial: 8e92b34db0a0bba46bb610427ddfe4a9f22b4e9f.
- Baseline: 846 testes aprovados, 174,48 s.
- Entrega: camada analítica somente leitura, sem migração e sem publicação operacional.

## Arquitetura e funcionalidades

`database/management_metrics_repository.py` lê observações, avaliações, fila, decisões, eventos, versões, desenvolvimento e alertas em transação consistente. Reaproveita a regra oficial de validade da decisão humana, limitando evidências ao corte. `services/management_metrics_service.py` agrega, calcula duração, taxas e comparações, aplica filtros e cache limitado com invalidação por SQLite/WAL. `ui/management_dashboard.py` apresenta os resultados sem SQL nem comandos operacionais.

Nova página com oito cards executivos e 16 métricas selecionáveis: anúncios novos, possíveis identidades, ausências válidas no período/acumuladas, fila aberta/concluída/pendente, alterações e invalidações, desenvolvimento ativo/entradas/conclusões/descartes, alertas novos/relevantes e cobertura conhecida. Cada métrica usa a mesma lista do drill-down, paginada em 30 registros. Navegação reaproveita revisão e desenvolvimento existentes.

Períodos hoje, 7/30/90 dias, ano atual e personalizado; parceiro pelo registro existente; filtros de fabricante, modelo, ano, situação na base, estado humano, etapa, prioridade e responsável. Base publicada selecionável. Comparação com período anterior de mesma duração, incluindo tempo de revisão, com setas neutras e denominadores explícitos.

Revisão: distribuição/percentuais, eventos, tempo até primeira conclusão com média/mediana/amostra, alterações e invalidações. Desenvolvimento: oito etapas, passagens encerradas, idade da etapa aberta, top 10, prazos existentes e responsável sem avaliação individual. Cobertura/matching: séries por dia/base e anúncio, deduplicadas, sem interpretar V10–V16/MC. Demanda: identidades estritas e anúncios distintos, sem contar recoleta como moto nova.

Prioridades: última avaliação/override válido temporalmente, separação manual/automática e não avaliada. Alertas: estado histórico, severidade e tipo, contagem única por origem e ID. Base: totais, diferenças, distribuição de cobertura e revalidações identificadas. CSV agregado UTF-8 BOM, filtros/corte/definições/tempos/taxas/comparações e proteção contra fórmulas; sem raw_text, fotos ou justificativas.

## Validação real reproduzível

Foi aberta uma conexão somente leitura ao banco real e criada uma cópia consistente para conferência. O banco operacional recebeu novas coletas ao longo do trabalho, por outros fluxos; não se compara seu estado final com um hash antigo como se fosse estático. A camada entregue não grava nele. Nenhuma versão nova foi publicada durante esta entrega.

Corte UTC da evidência: `2026-09-30T14:48:45.192753+00:00`. Banco de conferência: `reports/milestone-13/validation.sqlite3` (ignorado pelo Git).

| Verificação | Resultado |
|---|---|
| stock | 159 |
| base | 1337 |
| new_ads | 193 |
| review_opened | 173 |
| integrity | ok |
| foreign_keys | [] |

Os totais de estoque, base, novos anúncios e revisões abertas foram comparados a SQL direto e coincidiram. O dump lógico da cópia permaneceu idêntico antes/depois das consultas.

| Métrica | Valor no corte |
|---|---|
| Novos anúncios | 193 |
| Possíveis novas identidades | 55 |
| Ausências confirmadas no período | 0 |
| Ausências confirmadas acumuladas | 0 |
| Revisões abertas no período | 173 |
| Revisões concluídas no período | 0 |
| Revisões pendentes | 144 |
| Decisões alteradas | 0 |
| Revisões reabertas | 2 |
| Desenvolvimentos ativos | 0 |
| Entradas em desenvolvimento | 0 |
| Desenvolvimentos concluídos | 0 |
| Desenvolvimentos descartados | 0 |
| Novos alertas | 64 |
| Alertas relevantes | 41 |
| Cobertura conhecida | 20 |

Cálculo sem cache: **0.3362 s**. Com cache: **0.0155 s**. Carregamento completo no navegador Edge local: **3.357 s** (inclui navegação inicial do dashboard). São medições locais na população acima, não promessa para históricos arbitrariamente grandes.

A ausência de decisões conclusivas e de desenvolvimento no recorte real produz amostra vazia, não duração zero. Esses caminhos foram exercitados com fixtures isoladas. Os dois arquivos RESUMO_MDL.xlsx mantêm SHA-256 `32aac84eedec3e8b34e48920bc4bf03c17ccc773886cd84490d2e6f64f57cfdc`.

## Interface e testes

Navegador Edge/Playwright: carregamento, abas, gráficos, botão de drill-down, CSV e captura desktop/mobile; sem pageerror. A CLI agent-browser não estava disponível, então foi usado o navegador instalado com Playwright. O filtro BMW e seu CSV foram conferidos em uma execução; o fluxo completo de filtros, datas personalizadas e preservação do banco também tem teste Streamlit AppTest. Nenhum teste publica/edita a base operacional.

Novos testes cobrem período/fuso, limites inválidos, identidade incompleta, anúncio fora do estoque, deduplicação, filtros, estatística vazia, etapa/reentrada/SLA, alerta, taxas, ausência sem comprovação, prioridade histórica, validade por base, decisão futura, somente leitura, cache, CSV e interface. O teste existente de todas as páginas em português detectou rótulos técnicos na primeira passagem; a apresentação foi corrigida. Uma execução com ambiente de servidor somente leitura herdado falhou em um comando CLI de escrita da fixture; a regressão final foi executada em processo independente desse ambiente.

**Regressão final: 883 testes aprovados em 202,39 s (37 novos sobre a baseline de 846).**

Checagens: ruff check, ruff format --check, compileall app/services/database/ui e git diff --check. Evidências locais em reports/milestone-13 (ignoradas): validation.json, browser.json, CSV e screenshots.

## Documentação, limites e preservação

O dicionário `docs/DICIONARIO_INDICADORES.md` define populações, datas, unidades, denominadores, cache, filtros, revalidações e limitações. README inclui acesso e links. Não foi criada tabela de snapshots: observações/eventos existentes bastam para os indicadores entregues, com limites explícitos.

Limites: dias sem avaliação não são preenchidos; série humana representa eventos, não estoque diário reconstruído; severidade histórica não tem trilha completa; vínculos de origem de desenvolvimento usam a relação existente; filtros operacionais em séries usam contexto no encerramento; base global recebe apenas filtros de identidade. Tempo é corrido, não esforço humano. Bases antigas sem tabelas opcionais são lidas sem migração. Detalhes constam no dicionário.

Arquivos principais: repository, service, UI, integração app/dashboard.py, tests/test_management_metrics.py, dicionário, README e este relatório. Nenhuma funcionalidade operacional anterior foi removida; não há novo parceiro, IA, autenticação, implantação nem Milestone 14. Commit e push devem permanecer na branch solicitada; o SHA da entrega é o commit que adiciona este relatório (consultável via git log), evitando hash autorreferente no próprio arquivo.
