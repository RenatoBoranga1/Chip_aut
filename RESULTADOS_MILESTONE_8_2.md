# Resultados — Milestone 8.2

Reavaliação concluída sem aprovação de novos collectors. Somente WR Motos continua habilitada. Diagnóstico limitado, evidências e métricas foram adicionados sem alterar a coleta WR, matching, pesos, decisões humanas ou dados operacionais.

## Estado inicial e validação

- Branch: `milestone-3-wr-motos-wip`; árvore inicialmente limpa; fetch realizado.
- SHA inicial: `c66865bdaa37879d323fe54725ba0ee547025ee6`.
- Baseline executada: **972 testes aprovados em 303,09 s**.
- Suíte nova de diagnóstico: **31 testes aprovados**; suíte completa: **1003 testes aprovados em 399,09 s**, preservando os 972 anteriores.
- Ruff check e format: aprovados; 165 arquivos formatados. Compileall app/services/database/ui e diff --check aprovados.
- SQLite: integrity_check `ok` no operacional e na cópia de validação. Sem migration nova (última: 014).
- CLI status e diagnose dos três candidatos executados; Moto Marques com `--live` termina sem rede por restrição conhecida. Diagnósticos HTTP testados com respostas injetadas, sem rede nos testes.
- Registry habilita só WR. A suíte preserva scheduler, run-all, locks, isolamento, alertas, review e desenvolvimento existentes.

## Resultado por parceiro

| Parceiro | Status anterior | Resultado da investigação | Rota/filtro encontrado | Critério de moto | Integração final | Motivo e limites |
|---|---|---|---|---|---|---|
| Thomas | Não integrado, estoque misto | DADOS INSUFICIENTES PARA CLASSIFICAÇÃO SEGURA | `/Veiculos`; `/Home/ObterMarcasPorTipo/1` retorna marcas, não tipo individual | Nenhum aprovado | Não integrado | Breadcrumb Motos também no carro; sem campo seguro observado |
| Motonil | Não integrado, kart/serviço | DADOS INSUFICIENTES PARA CLASSIFICAÇÃO SEGURA | `/MOTOS`, categoria 65 e rota pública alternativa; mapa HTML | Nenhum aprovado | Não integrado | Mesma categoria para motos, kart e serviço; atributos em texto livre |
| Moto Marques | Não integrado, HTTP 403 | BLOQUEADO POR RESTRIÇÃO DE ACESSO | `/multipla` e filtros novo/usado observados no navegador | Não auditado | Não integrado | HTTP simples 403; browser abre, mas robots proíbe ChatGPT-User e agentes genéricos |
| WR Motos | Ativo | Integração preservada | XHR HTML existente | Critério existente preservado | Ativo | Nenhuma nova coleta WR disparada por esta entrega |

Não foram tentadas combinações inventadas de parâmetros, endpoints privados, login, cookies de evasão, proxy, rotação de UA ou challenge. Moto Marques foi encerrada ao observar o Disallow. Sitemaps desse domínio ficaram não avaliados, não foram declarados inexistentes. Browser acessível não equivale a permissão para automação.

## Auditoria de tipo e amostra

Seis detalhes examinados: Thomas 5058456 (carro), 5534082 (scooter), 2656970 (tipo não explícito); Motonil 1061 (serviço), 1755 (moto), 1635 (kart). A regra categoria/breadcrumb Motos produziria pelo menos três falsos positivos; foi rejeitada. Nenhuma marca, título, foto ou IA classifica itens para publicação.

Resultado do sistema: seis UNKNOWN, zero publicação. Não se calcula acurácia de classificador inexistente. Verdadeiros/falsos positivos e falsos negativos não são aplicáveis à política de abstenção. A amostra 10–20 seguida de coleta controlada só se aplicaria a parceiros aprováveis; nenhum atingiu esse estágio.

Releitura offline dos HTMLs reais salvos: Thomas **78 cards/78 IDs**, Motonil **19 cards/19 IDs**, totais consistentes. Todos os **97 são desconhecidos**, não motos confirmadas; excluídos por tipo determinístico: zero. Moto Marques: quantidade desconhecida. Nenhum novo anúncio foi persistido. Fixtures mínimas mantêm apenas o contrato HTML necessário, sem páginas completas.

## Implementação e interface

- `partners/assessments.py`: avaliações datadas, motivo, campos/rotas, status de acesso, categoria, métricas e avisos; separado do registry executável.
- `partners/diagnostics.py` e `app/partners.py`: `diagnose`, leitura salva por padrão; `--live` limitado a robots e uma página Thomas/Motonil. Sem banco, redirects, retries ou detalhes. Limites: 10 s por acesso, 3 MB, intervalo mínimo 2 s; robots pode aumentar ou impedir acesso.
- Campos UNKNOWN e evidência de categoria mista impedem publicação. Parser detecta cards ausentes, IDs inválidos/duplicados e totais inconsistentes; parcial não significa estoque vazio. Diagnóstico não é collector nem modelo canônico alternativo.
- `services/partner_service.py`, `app/dashboard.py`, `ui/partner_diagnostics.py`: integração, método, última validação manual, categoria segura e qualidade por parceiro. Valores não medidos ficam vazios/não avaliados; publicados e observados têm escopos distintos.
- `ui/management_dashboard.py`: opção de qualidade por parceiro. `ui/alert_panel.py`: avisos salvos, deduplicados por parceiro/motivo e sem novas gravações. Erros de acesso, estrutura e parcial de diagnósticos futuros ficam na saída CLI, sem persistência automática no centro de alertas.
- `tests/test_partner_diagnostics.py` e duas fixtures: parsing/IDs, categorias mistas, UNKNOWN, parcial, quebra estrutural, 403/401/429, CAPTCHA/login, timeout, redirects, robots, limites, CLI e dashboard somente leitura.

O menu permanece com 11 itens, Possíveis novas motos em terceiro, cinco telas ocultas preservadas. Não há mudança em rotas, permissões ou dados. Não foram criados DevelopmentItems ou decisões humanas. Nenhuma mudança em coletores, matching, normalizadores ou configuração de parceiros.

## Validação visual e dados

Dashboard local na porta 8533, em cópia SQLite somente leitura: Visão geral, Parceiros, Alertas e Indicadores gerenciais. Browser integrado do Codex utilizado; menu e novos campos/avisos verificados. Nenhum erro de console registrado.

A cópia operacional atual contém base ativa 3 (V16), coleta WR 7 de 05/10 e **170 anúncios ativos**. Esse é o estado observado durante a validação, não uma nova coleta realizada por este milestone. O número 159 do relatório M8.1 é histórico. Bancos, HTML bruto e logs permanecem ignorados em reports/work.

## Limitações e entrega Git

Nenhum aumento do estoque monitorado. Thomas/Motonil precisam de evidência pública confiável de tipo; Moto Marques precisa de acesso permitido. A investigação cobre rotas observadas, não prova inexistência universal de outra fonte. Avaliações salvas não são atualizadas ao abrir o dashboard nem por diagnose. Métricas de tipo da WR não foram instrumentadas para preservar seu collector.

Documentação: [auditoria detalhada](docs/VALIDACAO_MANUAL_PARCEIROS_8_2.md), [avaliação](docs/AVALIACAO_NOVOS_PARCEIROS.md), [operação](docs/PARCEIROS_INTEGRADOS.md) e README atualizados.

Mensagem do commit: `feat: validate and recover additional inventory partners`, na mesma branch, sem merge em main. O SHA definitivo e a confirmação do push constam na entrega da conversa (o commit não pode conter seu próprio hash).
