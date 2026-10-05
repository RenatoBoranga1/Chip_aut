# Parceiros e operação

Estado verificado em 05/10/2026. Apenas collectors reais entram no PartnerRegistry. Candidatos avaliados ficam em `partners/assessments.py`, sem possibilidade de execução, e aparecem como **Não integrado** na CLI e na página Parceiros.

| Parceiro | URL | Status | Método | Campos disponíveis | Limitações |
|---|---|---|---|---|---|
| WR Motos | https://www.wrmotos.com.br/ | Ativo | HTTP + HTML XHR público, adapter existente | ID, link, marca, modelo, versão quando fornecida, ano, preço, km, imagem | Conflito entre filtros 0 km permanece desconhecido; ausência de anúncio não comprova venda |
| Moto Marques | https://motomarquesmultimarcas.com.br/ | Não integrado | Nenhum collector | Não verificados | HTTP 403 |
| Thomas Motos | https://thomasmotos.com.br/Veiculos | Não integrado | Amostragem HTML pública | ID, título, versão, ano, preço, km, imagem | Estoque misto, sem tipo verificável |
| Motonil | https://www.motonil.com.br/MOTOS | Não integrado | Amostragem HTML pública | ID, título, preço, imagem; marca no detalhe examinado; ano/km em texto | Categoria contém kart e serviço, estrutura insuficiente |

Veja [avaliação técnica](AVALIACAO_NOVOS_PARCEIROS.md). Nenhum novo parceiro foi aprovado nesta avaliação. Para habilitar um candidato no futuro, primeiro validar classificação e dados, implementar/testar PartnerAdapter e registrá-lo explicitamente; alterar apenas o status de avaliação não habilita coleta.

## Comandos

```console
python -m app.partners list
python -m app.partners status
python -m app.partners show thomas_motos
python -m app.scheduler run-now --partner wr_motos
python -m app.scheduler run-all --json
```

`run-all` executa somente parceiros habilitados, com um worker por parceiro, limites e lock próprios. Cada resultado é devolvido por chave; uma falha não impede outra execução. `--request-key` mantém idempotência no escopo de cada parceiro. Código de saída 1 se qualquer execução falhar/cancelar. Sem parceiros habilitados, retorna objeto vazio. As transações de escrita SQLite continuam naturalmente serializadas; a espera de rede de um parceiro não ocupa o worker de outro. Banco inexistente não é criado pelo comando.

## Configuração

`config/partners.json`: `enabled`, `limits.timeout_seconds`, `limits.retries`, `limits.concurrency`, `limits.max_pages`, `limits.delay_seconds`, `limits.requests_per_minute`, `detail_lookup`, `image_fetch` e `image_hosts`.

Valores atuais preservam a WR: concorrência 1, até 30 solicitações/minuto (intervalo mínimo 2 s), timeout 30 s, até 2 retries transitórios, 100 páginas. Intervalo efetivo = máximo do delay configurado e 60/requests_per_minute; robots pode elevar o intervalo. `detail_lookup=false` impede fallback de imagem nos detalhes. `image_fetch=false` impede esse fallback e novas transferências de fotos, mantendo metadados e cache já existentes. O limite de catálogo não é um limitador global de todas as imagens: miniaturas mantêm o orçamento/cache próprio existente.

A política conservadora existente interrompe 401/403/429 e challenges. Não adicionamos retry em 429: não insistir no rate limit é mais conservador que reexecutar. Timeout/conexão/5xx seguem a política transitória existente. Nenhum bypass.

## Origens e decisões

Possíveis novas motos permite consultar a consolidação de todos os parceiros e abrir ocorrências, com situação no parceiro, base e decisão por origem. Fabricante/modelo/versão/ano são comparados estritamente pelo normalizador existente. Identidades incompletas, ambíguas, prováveis, em dúvida ou com avisos de parsing ficam isoladas; não há fuzzy de consolidação. Uma identidade não é uma moto física. Consolidação não cria decisão nem altera suporte.

O detalhe da revisão mostra parceiro e ocorrências compatíveis. As decisões continuam limitadas às regras atuais; não são propagadas entre parceiros. DevelopmentItem já admite várias origens e mantém deduplicação existente. Prioridade não muda de peso. Alertas permanecem específicos por parceiro/ocorrência, com deduplicação existente: consolidar alertas globalmente ocultaria eventos de estoque distintos, portanto essa mudança foi descartada.

Indicadores gerenciais oferece comparação por parceiro sob os mesmos filtros/período/base. Diferencia quantidade de anúncios de grupos de identidade; ambiguidades são contadas como casos isolados. Não soma identidades entre parceiros. Candidatos não integrados não entram nos indicadores de estoque.

Na página Parceiros, novos significa primeira observação; reaparecidos significa previamente observado mas ausente no último censo completo. Coleta parcial não calcula desaparecimentos. Histórico mantém seus rótulos/semântica preexistentes de reencontro; a nova coluna Reaparecidos tem a definição acima. Nenhuma migration nova; última existente: 014_scanner_versions.sql.
