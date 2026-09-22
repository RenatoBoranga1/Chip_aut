# Fechamento verificado do Milestone 3.1 — 22/09/2026

## Origem e escopo desta verificação

A branch remota já continha `b00ffe5`, implementação do refinamento sobre
`f87816e`. Foi preservada por fast-forward; nenhum milestone foi reimplementado.
Este fechamento acrescenta resultados verificáveis ao Git, pois os relatórios
operacionais citados na validação anterior não estavam versionados.

O banco local tinha uma coleta antiga de 160 anúncios. Uma nova coleta HTTP em
22/09/2026, às 11:05 UTC, trouxe 158 anúncios únicos, 14 páginas (7 por filtro),
sem erros de coleta. Os dois filtros retornaram os mesmos 158 IDs: `zero_km=null`
e alerta de conflito em todos. Isso não comprova que o conteúdo seja idêntico à
coleta histórica mencionada no pedido, embora as contagens iniciais coincidam.

O baseline foi recalculado com `config/matching.json` extraído de `f87816e`
(sem política de identidade), usando o motor atual. Baseline e refinamento usam
exatamente as mesmas observações da coleta 2 e a mesma base importada 2.
Não houve nova importação ou revisão manual. Esta é uma comparação de políticas
sobre uma nova observação, não recuperação do banco histórico de outro ambiente.

## Resultado comparativo

Coleta 2; base 2.

| Tipo | Antes | Depois |
|---|---:|---:|
| AMBIGUOUS | 8 | 8 |
| CORRESPONDENCIA_PROVAVEL | 5 | 0 |
| EXATO_NORMALIZADO | 41 | 54 |
| NAO_ENCONTRADA_NA_BASE | 56 | 53 |
| REVISAR | 48 | 43 |

Resolvidos por equivalências explícitas: 13.
Ablação individual: regras indispensáveis ao resultado. Regras conjuntas podem contar o mesmo anúncio; não somar para obter total.

## Casos resolvidos

| ID / anúncio | Ano | Antes | Chave da base | Regra indispensável |
|---|---|---|---|---|
| [399290](https://www.wrmotos.com.br/v1/veiculo?veiculo=399290) TRIUMPH SCRAMBLER 400 X *PROMOÇÃO* | 2025 | REVISAR | TRIUMPH / SCRAMBLER400X / 2025 | promotion-star-suffix |
| [402920](https://www.wrmotos.com.br/v1/veiculo?veiculo=402920) HARLEY-DAVIDSON SPORTSTER S ** PROMOÇÃO** | 2023 | REVISAR | HARLEY DAVIDSON / SPORTSTERS / 2023 | promotion-star-suffix |
| [414709](https://www.wrmotos.com.br/v1/veiculo?veiculo=414709) TRIUMPH STREET TRIPLE 765 RS *PROMOÇÃO* | 2023 | REVISAR | TRIUMPH / STREETTRIPLE765RS / 2023 | promotion-star-suffix |
| [421926](https://www.wrmotos.com.br/v1/veiculo?veiculo=421926) BMW R 1250 GS ADVENTURE TRIPLE BLACK *PROMOÇÃO* | 2024 | REVISAR | BMW / R1250GSADVENTURETRIPLEBLACK / 2024 | promotion-star-suffix |
| [425668](https://www.wrmotos.com.br/v1/veiculo?veiculo=425668) HONDA CRF 1100L AFRICA TWIN DCT *VERSÃO DCT* | 2023 | REVISAR | HONDA / CRF1100LAFRICATWINDCT / 2023 | repeated-dct-description |
| [428542](https://www.wrmotos.com.br/v1/veiculo?veiculo=428542) BMW K 1600 GTL *PROMOÇÃO* | 2018 | REVISAR | BMW / K1600GTL / 2018 | promotion-star-suffix |
| [431023](https://www.wrmotos.com.br/v1/veiculo?veiculo=431023) DUCATI STREETFIGHTER V4 S *PROMOÇÃO* | 2022 | REVISAR | DUCATI / STREETFIGHTERV4S / 2022 | promotion-star-suffix |
| [434855](https://www.wrmotos.com.br/v1/veiculo?veiculo=434855) BMW R 1250 GS ADVENTURE PREMIUM RALLYE | 2024 | REVISAR | BMW / R1250GSADVENTUREPREMIUMRALLY / 2024 | bmw-adventure-rally-spelling |
| [442749](https://www.wrmotos.com.br/v1/veiculo?veiculo=442749) YAMAHA FZ25 FAZER ABS | 2019 | CORRESPONDENCIA_PROVAVEL | YAMAHA / FAZERFZ25ABS / 2019 | yamaha-fazer-token-order |
| [445743](https://www.wrmotos.com.br/v1/veiculo?veiculo=445743) BMW BMW R 18 | 2023 | CORRESPONDENCIA_PROVAVEL | BMW / R18 / 2023 | repeated-manufacturer-prefix |
| [402308](https://www.wrmotos.com.br/v1/veiculo?veiculo=402308) DUCATI SCRAMBLER FULL THROTTLE ** PROMOÇÃO** | 2018 | REVISAR | DUCATI / SCAMBLERFULLTHROTTLE / 2018 | ducati-scrambler-spelling, promotion-star-suffix |
| [422106](https://www.wrmotos.com.br/v1/veiculo?veiculo=422106) BMW S 1000 R PROMOÇÃO R$4.000 ABAIXO DA FIPE | 2021 | NAO_ENCONTRADA_NA_BASE | BMW / S1000R / 2021 | promotion-fipe-suffix |
| [440808](https://www.wrmotos.com.br/v1/veiculo?veiculo=440808) BMW R 1250 GS ADVENTURE PREMIUM 40 ANOS | 2022 | REVISAR | BMW / R1250GSADVENTUREPREMIUM40YEARS / 2022 | bmw-40-years-translation |

## PROVAVELMENTE_NAO_SUPORTADA_NA_BASE (14)

Hipótese sobre identidades registradas nesta versão da planilha, não diagnóstico de SEM_SUPORTE. Anos não são interpolados. Demais não encontrados permanecem inconclusivos.

| ID / anúncio | Ano | Evidência |
|---|---|---|
| [420076](https://www.wrmotos.com.br/v1/veiculo?veiculo=420076) BMW S 1000 RR *PROMOÇÃO* | 2017 | Identidade canônica conhecida em outros anos; ano anunciado ausente e sem candidato plausível no mesmo ano. Outros anos: [2022, 2024, 2021, 2023, 2025, 2026, 2015] |
| [425656](https://www.wrmotos.com.br/v1/veiculo?veiculo=425656) HONDA NC 750X ABS | 2018 | Identidade canônica conhecida em outros anos; ano anunciado ausente e sem candidato plausível no mesmo ano. Outros anos: [2019] |
| [431380](https://www.wrmotos.com.br/v1/veiculo?veiculo=431380) HONDA CBR 500R | 2014 | Identidade canônica conhecida em outros anos; ano anunciado ausente e sem candidato plausível no mesmo ano. Outros anos: [2018] |
| [436759](https://www.wrmotos.com.br/v1/veiculo?veiculo=436759) DUCATI MULTISTRADA 1200S TOURING | 2016 | Identidade canônica conhecida em outros anos; ano anunciado ausente e sem candidato plausível no mesmo ano. Outros anos: [2017] |
| [437940](https://www.wrmotos.com.br/v1/veiculo?veiculo=437940) INDIAN SCOUT | 2016 | Montadora extraída do catálogo não possui registros na versão consultada, após aliases conhecidos. Outros anos: [] |
| [439242](https://www.wrmotos.com.br/v1/veiculo?veiculo=439242) KAWASAKI NINJA 300 | 2014 | Identidade canônica conhecida em outros anos; ano anunciado ausente e sem candidato plausível no mesmo ano. Outros anos: [2023, 2013, 2018] |
| [439246](https://www.wrmotos.com.br/v1/veiculo?veiculo=439246) KAWASAKI Z800 | 2016 | Identidade canônica conhecida em outros anos; ano anunciado ausente e sem candidato plausível no mesmo ano. Outros anos: [2017, 2014] |
| [439816](https://www.wrmotos.com.br/v1/veiculo?veiculo=439816) TRIUMPH ROCKET III R | 2024 | Identidade canônica conhecida em outros anos; ano anunciado ausente e sem candidato plausível no mesmo ano. Outros anos: [2020, 2023, 2021, 2022] |
| [440005](https://www.wrmotos.com.br/v1/veiculo?veiculo=440005) BMW G 650 GS | 2010 | Identidade canônica conhecida em outros anos; ano anunciado ausente e sem candidato plausível no mesmo ano. Outros anos: [2014, 2015] |
| [440480](https://www.wrmotos.com.br/v1/veiculo?veiculo=440480) HONDA CBR 650F | 2015 | Identidade canônica conhecida em outros anos; ano anunciado ausente e sem candidato plausível no mesmo ano. Outros anos: [2018, 2019] |
| [441730](https://www.wrmotos.com.br/v1/veiculo?veiculo=441730) HONDA SHADOW 750 | 2007 | Identidade canônica conhecida em outros anos; ano anunciado ausente e sem candidato plausível no mesmo ano. Outros anos: [2014] |
| [442703](https://www.wrmotos.com.br/v1/veiculo?veiculo=442703) BMW G 310 GS | 2020 | Identidade canônica conhecida em outros anos; ano anunciado ausente e sem candidato plausível no mesmo ano. Outros anos: [2022, 2024, 2021, 2023, 2025, 2026] |
| [445190](https://www.wrmotos.com.br/v1/veiculo?veiculo=445190) HARLEY-DAVIDSON ROAD KING CLASSIC | 2014 | Identidade canônica conhecida em outros anos; ano anunciado ausente e sem candidato plausível no mesmo ano. Outros anos: [2012, 2011] |
| [445448](https://www.wrmotos.com.br/v1/veiculo?veiculo=445448) HONDA CB 250F TWISTER | 2017 | Identidade canônica conhecida em outros anos; ano anunciado ausente e sem candidato plausível no mesmo ano. Outros anos: [2022, 2020, 2021] |

## Ambiguidades preservadas

- 428733: BMW R 1200 GS, 2018; R 1200 GS; R 1200 GS PREMIUM; R 1200 GS TRIPLE BLACK (LIQUID COOLED)
- 439893: BMW S 1000 RR, 2022; S1000RR; S 1000RR CARBON
- 443074: BMW S 1000 RR, 2024; S1000 RR; S 1000 RR-M CARBON; S 1000 RR-M PACKAGE
- 443471: BMW R 1250 GS PREMIUM, 2020; R 1250 GS PREMIUM; R 1250 GS PREMIUM 40 YEARS; R 1250 GS PREMIUM RALLYE
- 444162: ROYAL ENFIELD CLASSIC 350, 2023; CLASSIC 350; CLASSIC 350 DARK
- 444946: BMW S 1000 RR, 2025; S 1000 RR; S 1000RR M
- 445207: BMW R 1250 GS PREMIUM, 2020; R 1250 GS PREMIUM; R 1250 GS PREMIUM 40 YEARS; R 1250 GS PREMIUM RALLYE
- 445647: BMW S 1000 RR, 2024; S1000 RR; S 1000 RR-M CARBON; S 1000 RR-M PACKAGE

## Pesos e limites

Pesos mantidos. Sem rótulos humanos, variação de contagem não mede precisão nem autoriza calibrar scores.
Os filtros 0 km continuam inconsistentes: estado indefinido e alerta preservados. O inventário JSON contém todos os anúncios, tokens, scores, diferenças, rejeições e causas. Cobertura completa e candidatos estão em coverage/COBERTURA.md.

## Regras e efeito medido

As nove regras configuradas em `config/identity.json` foram preservadas.
As categorias são fabricante, modelo, token, equivalência e ruído; não há novo
alias de fabricante habilitado. Todas possuem evidência e testes positivos/negativos.

| Regra indispensável | Anúncios resolvidos |
|---|---:|
| promotion-star-suffix | 7 |
| repeated-dct-description | 1 |
| bmw-adventure-rally-spelling | 1 |
| yamaha-fazer-token-order | 1 |
| repeated-manufacturer-prefix | 1 |
| ducati-scrambler-spelling | 1 |
| promotion-fipe-suffix | 1 |
| bmw-40-years-translation | 1 |

A regra `ducati-streetfighter-spacing` existe, mas não é indispensável isoladamente
nesta coleta: a normalização compacta já elimina a diferença de espaçamento.
O anúncio 402308 precisa simultaneamente de grafia e remoção da promoção; portanto
as 14 incidências da tabela correspondem a 13 anúncios, não 14 casos resolvidos.

Dos cinco prováveis anteriores, dois viraram exatos por equivalências explícitas
e três foram encaminhados à revisão. Houve 26 mudanças de classificação: as
outras transições e os candidatos estão no inventário JSON. Não são 26 resoluções.
Os pesos 0,65/0,25/0,10 foram mantidos. As alternativas testadas mantiveram 54
exatos e 8 ambíguos, mas alteraram a divisão entre revisão e não encontrados;
essa variação não mede precisão sem rótulos humanos.

## Falsos positivos e limites

Nenhum vínculo automático incorreto foi identificado na inspeção dos 13 casos
resolvidos ou nos testes. Isso não é uma estimativa de precisão: não há conjunto
independentemente rotulado nem confirmação humana dos anúncios. Os 41 exatos
anteriores conservaram suas chaves. Nenhum resultado com revisão pendente recebeu
chave automática. Ano, ABS, Adventure, Touring e demais variantes continuam
protegidos. A lista de 14 ausências prováveis não significa status SEM_SUPORTE;
os outros 39 não encontrados continuam inconclusivos.

## Validação e preservação

- `python -m pytest -q`: 220 testes aprovados (inclui as regressões anteriores).
- `python -m ruff check .`: aprovado.
- `python -m ruff format --check .`: 54 arquivos aprovados.
- `python -m compileall -q app database matching partners scanner_base services`: aprovado.
- Imports de todos os módulos desses seis pacotes: aprovados.
- SQLite `integrity_check`: `ok`; `foreign_key_check`: nenhuma violação.
- As tabelas imports, motorcycles, motorcycle_snapshots, system_records,
  import_issues, matching_reviews e matching_memory ficaram integralmente iguais
  ao backup anterior à coleta. Todos os registros históricos anteriores foram
  preservados; novos matching_runs, coverage_runs e observações foram acrescentados.
- A tabela de última observação partner_advertisements foi atualizada normalmente
  pela nova coleta, preservando os IDs anteriores. O histórico está em
  partner_observations (160 anteriores + 158 novos).
- Planilha idêntica byte a byte à versão de `f87816e`; SHA-256:
  `32aac84eedec3e8b34e48920bc4bf03c17ccc773886cd84490d2e6f64f57cfdc`.

## Artefatos e reprodução

Os artefatos completos ficam em `reports/revalidation-2026-09-22/`:
`collections/` (HTML e resumo), `baseline/`, `refinement/inventory.json`
(inventário de todos os 158 com tokens, scores, diferenças, rejeições e causas),
`refinement/probable_absence.json`, `refinement/coverage/` e
`refinement/validation.json` (comparação do banco com backup).
Banco e artefatos operacionais permanecem ignorados pelo Git conforme a política
existente. Este documento registra as contagens, todos os casos resolvidos,
ausências prováveis e ambiguidades, e é versionado.

Com o banco local desta execução, o relatório pode ser reproduzido offline com:

```powershell
python -m app.refine 2 --baseline-coverage 1 --reports reports/revalidation-repeat
```

Este fechamento altera somente `RESULTADOS_MILESTONE_3_1.md`. O código já estava
publicado em `b00ffe5`: config/identity.json, config/matching.json,
matching/identity.py, matching/matcher.py, matching/models.py,
matching/fuzzy_matcher.py, matching/rules.py, services/refinement_service.py,
app/refine.py e tests/test_refinement.py, além da documentação daquele commit.
Trabalho mantido na branch `milestone-3-wr-motos-wip`, sem merge em main.
