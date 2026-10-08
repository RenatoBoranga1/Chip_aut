# Fontes alternativas legítimas — Milestone 8.3

Avaliação de 08/10/2026. **Nenhuma fonte aprovada; apenas WR Motos habilitada.** A pesquisa foi limitada aos caminhos públicos observados. Não demonstra que jamais exista uma exportação autorizável junto aos fornecedores.

## Resultado por parceiro

| Parceiro | Descoberta e estrutura (A/B) | Semântica e identidade (C) | Decisão |
|---|---|---|---|
| Thomas Motos | HTML AutoCerto, IDs nativos; API do fornecedor documentada | HTML sem tipo individual; API de estoque exige OAuth2 privado | Não integrar |
| Motonil | OpenCart / AF Systems, categoria 65, IDs de produto, mapa e fragmentos AJAX | Categoria inclui kart e consignação; sem atributo individual ou categoria filha confiável | Não integrar |
| Moto Marques Multimarcas | Catálogo externo Webmotors com dealer 3918827 e JSON público | Endereço da loja externa diverge da unidade solicitada; vínculo não comprovado | Não integrar |

Fases D/E não realizadas: a amostra de ativação de 10–20 anúncios e o adapter dependem da aprovação das fases anteriores. Não há falso positivo medido em amostra de ativação; esse valor é **não aplicável**, não uma alegação de precisão de 100%.

## Thomas — evidências

- [Catálogo oficial](https://thomasmotos.com.br/Veiculos): 75 cartões na resposta HTTP observada, total declarado 75; 75 UNKNOWN. O registro histórico M8.2 de 78 permanece intacto.
- IDs de anúncio em `/Veiculo/.../<id>/detalhes`. Três detalhes públicos inspecionados: 5058456 (Spin), 5534082 (Burgman), 2656970 (Tactic). Não apresentaram JSON-LD ou tipo individual seguro. Nomes serviram apenas para auditar contraexemplos, nunca para implementar classificação.
- Frontend usa AutoCerto; referências a `/Home/ObterMarcasPorTipo/1`, `/Home/ObterAnoVeiculo/1`, `/Home/ObterAnoVeiculo/2`, `/Home/ObterModelosPorMarca/`, `/Home/OrdenarVeiculos/` e `/BuscaRapida`. Esses caminhos não comprovam o tipo de cada anúncio.
- `/sitemap.xml` e `/sitemap_index.xml`: 404. Sem feed/exportação pública verificável nos links inspecionados. O script que retornou 403 no M8.2 não foi novamente solicitado.
- [Swagger oficial AutoCerto](https://integracao.autocerto.com/swagger/ui/index), [contrato V1](https://integracao.autocerto.com/swagger/docs/V1): `GET /api/Veiculo/ObterEstoque` retorna estoque da loja e exige OAuth2. Documentação pública não equivale a estoque público. Não houve solicitação de token, uso de credenciais ou consulta ao endpoint de estoque. `codigoUnidade` não autoriza consultar qualquer revenda.

## Motonil — evidências

- [MOTOS](https://www.motonil.com.br/MOTOS): 19 cartões, 19 UNKNOWN. Categoria 65 é mista.
- Detalhes públicos de consignação (1061), BMW S1000 RR (1755) e kart (1635) não forneceram JSON-LD nem `item_type`, `vehicle_type` ou equivalente determinístico.
- [Mapa oficial](https://www.motonil.com.br/index.php?route=information/sitemap): categoria MOTOS sem subcategorias; ramificações observadas pertencem às peças. Sitemap XML vazio; índice XML 404.
- JS do frontend referencia `extension/module/oclayerednavigation/category`, com fragmentos `result_html` / `layered_html`. Não foi inventada uma chamada sem os parâmetros observados nem interpretada a categoria como tipo seguro.
- Fornecedor referenciado no rodapé: [AF Systems](https://afsystems.com.br/); nenhuma API/feed de estoque público documentado localizado na investigação. Não há blacklist por título, cilindrada ou marca.

## Moto Marques — pesquisa exclusivamente externa

O domínio original não recebeu nenhuma nova requisição neste milestone. HTTP 403 e `Disallow: /` registrados no M8.2 continuam impedindo crawling, inclusive via navegador automatizado.

- [Loja Webmotors candidata](https://www.webmotors.com.br/motos/pr/loja.moto-marques-3918827): HTML público com `OfferCatalog`/`Vehicle`, JSON do frontend, `dealerInfo.id=3918827`, `filters.dealerId=3918827`, `filters.vehicleType=motos`. Resposta observada: 27 anúncios. Isso **não é estoque confirmado do parceiro solicitado**.
- Identidade da loja externa: Ney Braga 1440, Campo Mourão. [Site oficial da loja Suzuki](https://motomarques.com.br/nossas-lojas) corrobora esse endereço, enquanto a unidade Multimarcas solicitada consta na evidência anterior com Capitão Índio Bandeira 2261. Nome/grupo semelhante não prova mesma unidade ou mesmo estoque.
- [Robots Webmotors](https://www.webmotors.com.br/robots.txt) verificado; rotas restritas, incluindo API de detalhes, não foram consultadas. Nenhum cookie, token ou autenticação utilizado.
- Não foi atribuído fornecedor ao domínio bloqueado sem prova. Plataforma genérica que oferece feed não constitui vínculo oficial.

## Implementação e limites

`config/partner_sources.json` persiste seis evidências com tipo, URL, fornecedor, data, confiança categórica, acesso, identidade, classificação, campos, contagens e motivo. Confiança na procedência não significa autorização de coleta. `UNVERIFIED` é somente diagnóstico.

`PartnerSource` valida metadados e exige, para declarar aprovação: acesso público permitido, identidade comprovada, tipo determinístico, confiança elegível, amostra de 10–20 e zero falso positivo. Alterar JSON não registra adapter nem habilita parceiro. A aprovação manual exige evidências reais além da consistência do arquivo.

`inspect_document` e `audit_records` são validadores **offline**, não adapters universais. Contrato de teste explícito para JSON/API/feed; sitemap descobre URLs sem seguir links; HTML lê apenas JSON-LD. Tipos estruturados conflitantes, `Product`, `Vehicle`, nomes e categorias genéricas permanecem UNKNOWN. Identidade nativa é preservada; duplicatas bloqueiam o lote; IDs distintos não são fundidos por semelhança. Sem fonte aprovada não há publicação nem matching.

Avisos `SOURCE_UNAVAILABLE`, `SOURCE_STRUCTURE_CHANGED`, `TYPE_CLASSIFICATION_UNAVAILABLE` e `ALTERNATIVE_SOURCE_FAILED` são diagnósticos deduplicados por parceiro/fonte/código. Não são eventos recorrentes nem notificações inseridas no banco. O validador offline retorna DEGRADED quando uma fonte anteriormente aprovada perde o tipo, e nunca publica. Como não existe adapter novo aprovado, não existe execução automática alternativa a suspender neste milestone.

## CLI e dry-run

```powershell
python -m app.partners sources thomas_motos
python -m app.partners diagnose motonil
python -m app.partners diagnose moto_marques
python -m app.partners collect motonil --dry-run
```

`sources` e `diagnose` sem `--live` são consultas salvas. `collect --dry-run` reutiliza o diagnóstico público limitado de Thomas/Motonil: robots primeiro, intervalo mínimo de 2 segundos, limites de resposta/tempo, nenhuma repetição automática ou seguimento de detalhes. Não acessa a API autenticada nem o marketplace não aprovado. Moto Marques retorna o bloqueio já conhecido sem rede. O dry-run fica BLOCKED porque ainda não existe fonte classificável aprovada; falha não significa estoque vazio.

Métricas observadas e desconhecidos aparecem separadas de estoque. Métricas não medidas permanecem `null`; duração inclui acesso diagnóstico, não uma coleta de inventário aprovada. Nenhum banco é aberto por esses comandos. WR mantém seu coletor e scheduler existentes; este comando não substitui sua operação.

## Operação preservada

`config/partners.json`, registry, adapters, matching, decisões humanas, V16, M14, navegação e frequências não alterados. `run-all` continua contendo apenas WR. Nenhuma coleta real de candidato, matching ou consolidação cross-partner executada. Nada foi enviado a modelo para decidir tipo. HTML bruto e bancos de validação permanecem ignorados pelo Git.
