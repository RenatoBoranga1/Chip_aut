# Validação manual de parceiros — 8.2

## Relatório intermediário (antes de implementação)

Investigação concluída em 05/10/2026. SHA inicial c66865bdaa37879d323fe54725ba0ee547025ee6; branch correta, árvore limpa e fetch realizado. Baseline medida: 972 testes em 303,09 s.

| Parceiro | Resultado da investigação | Decisão |
|---|---|---|
| Thomas | HTML público e IDs estáveis; menu Motos e breadcrumb também incluem Chevrolet Spin; sem tipo por anúncio | DADOS INSUFICIENTES PARA CLASSIFICAÇÃO SEGURA |
| Motonil | Categoria técnica 65/MOTOS e rota alternativa confirmadas; a mesma categoria inclui kart e serviço | DADOS INSUFICIENTES PARA CLASSIFICAÇÃO SEGURA |
| Moto Marques | HTTP simples 403 na raiz, robots, www e /multipla. Navegador comum abre a raiz; robots no navegador declara User-agent: * / Disallow: / | BLOQUEADO POR RESTRIÇÃO DE ACESSO |

Nenhum candidato aprovado. Não haverá novo adapter nem habilitação. Implementação subsequente limitada a diagnóstico, métricas de classificação desconhecida, avisos e apresentação das evidências. Não foi realizada coleta operacional completa.

## Thomas: respostas obrigatórias

1. Existe link visível **Motos**, mas aponta para `/Veiculos`, estoque misto. Não há seletor de tipo nos filtros (marca/modelo/ano/preço).
2. Não foi encontrado parâmetro de tipo utilizado pela busca pública. O script monta `/BuscarVeiculo?marca=...&modelo=...&precoDe=...&precoAte=...&anoDe=...&anoAte=...`.
3. Endpoint público observado: `/Home/ObterMarcasPorTipo/1`; também há ObterModelosPorMarca, ObterAnoVeiculo e OrdenarVeiculos no JavaScript da página.
4. A resposta do endpoint examinado foi `[Value=5, Caption=CHEVROLET; Value=0, Caption=TODOS]`. Retorna IDs/rótulos de marcas, não tipo por anúncio; o nome do endpoint não comprova semântica de outros números.
5. Nenhuma regra determinística de seleção de motos foi validada. Não testamos IDs de tipo inventados, listas de marcas nem variações de URL por força bruta.
6. Amostra em três detalhes: `5058456` (Spin), `5534082` (Burgman ADX), `2656970` (Tactic). Todos usam breadcrumb Motos, campo oculto idVeiculo e itemprop=name, sem vehicle_type/category. O breadcrumb falha já no carro.
7. Spin é contraexemplo concreto; Tactic é caso limítrofe sem tipo explícito no documento e permanece desconhecido. Quilometragem zero e câmbio Manual não são prova de motocicleta.

Listagem HTTP e navegador mostraram 78 cards nesta validação (8.1 tinha 79). IDs em `/Veiculo/<slug>/<ID>/detalhes`. HTML servidor; não requer JavaScript para ler anúncios. Fabricante/modelo/título, versão, ano, preço/km e imagem disponíveis, mas não resolvem tipo. Sem paginação adicional apresentada na amostra. Script externo functions.js da Autocerto retornou 403 na inspeção direta: não insistimos. O script inline permitiu observar as rotas acima.

## Motonil: respostas obrigatórias

1. Existe `/MOTOS`, mas não é exclusiva de motocicletas.
2. O HTML contém a categoria **65** no seletor de busca e nos parâmetros `path=65`; a rota observada `/index.php?route=product/category&path=65&limit=25` foi validada e também contém 19 itens mistos.
3. Serviço e kart estão na mesma categoria 65; não foi exposta categoria distintiva confiável nos detalhes examinados.
4. Detalhes expõem product_id, título, descrição e breadcrumb; nenhum tipo estruturado confiável encontrado.
5. Filtrar por category_id/path não elimina os contraexemplos.
6. Não há exclusão verificável de serviço sem inferir texto. Não foi criada blacklist de IDs ou títulos.
7. HTML estável entre página de categoria e rota alternativa observadas, mas a estabilidade semântica necessária para motos não foi demonstrada.

Mapa HTML oficial `/index.php?route=information/sitemap` só lista MOTOS, ACESSÓRIOS e PEÇAS/subcategorias de peças. Não apareceu subcategoria exclusiva de motocicletas ou feed/RSS público nessa navegação. Script público oclayerednavigation.js troca product/category por extension/module/oclayerednavigation/category e recebe fragmentos result_html/layered_html: não estabelece tipo novo. Busca pública usa product/search + category_id e um ajaxSearch de texto; não há evidência de classificação individual confiável. Não chamamos ações de carrinho, propostas ou newsletter.

## Moto Marques: respostas obrigatórias

1. Sim, 403 no cliente HTTP simples identificado (MotoCoverageMonitor/0.3), sem cookies.
2. Confirmado na raiz, robots, www (URL oficial indexada) e `/multipla` (rota observada no frontend); não generalizamos para todas as rotas do domínio.
3. Sitemaps não foram acessados após a restrição de robots ter sido verificada; disponibilidade desconhecida, não ausência comprovada.
4. Rotas legítimas observadas no navegador: `/multipla`, `/multipla/veic_status/Novo`, `/multipla/veic_status/Usado`. A primeira também retorna 403 no HTTP simples.
5. Raiz renderiza cards e links `/motos/...-ID.html`; asset público all.min.js foi identificado, mas não buscado após conhecer a proibição. Não foi validado endpoint JSON alternativo.
6. Sim, navegador comum abriu sem login e sem challenge. Nenhum cookie foi exportado/reutilizado e nenhum user-agent foi rotacionado.
7. HTTP simples está restrito. Além disso, robots visto no navegador declara `User-agent: *` / `Disallow: /`, também proíbe bots específicos. A investigação terminou nesse ponto.
8. Busca encontrou o endereço oficial com www; também 403 por HTTP. Nenhuma fonte oficial alternativa permitida foi comprovada. Resultados indexados não autorizam copiar um catálogo bloqueado.

## Robots e sitemaps

| Parceiro | robots.txt | sitemap.xml | sitemap_index.xml |
|---|---|---|---|
| Thomas | 404 | 404 | 404 |
| Motonil | 200, comentários sem regras operacionais | 200, corpo vazio | 404 |
| Moto Marques | HTTP 403; navegador mostra Disallow: / para * | Não acessado após restrição | Não acessado após restrição |

Ausência de robots não é autorização irrestrita. Consulta conservadora: intervalo mínimo de 2 s nas requisições diagnósticas, sem retry após restrição, sem login, proxies, stealth ou desafios.

## Auditoria manual de amostra mista

| Parceiro / ID | Conteúdo examinado | Evidência estruturada de tipo | Resultado seguro |
|---|---|---|---|
| Thomas / 5058456 | Chevrolet Spin 1.8 LTZ 2024, carro; breadcrumb Motos | Breadcrumb contraditório | UNKNOWN |
| Thomas / 5534082 | Burgman ADX 125, scooter; mesmo breadcrumb | Sem tipo individual | UNKNOWN |
| Thomas / 2656970 | Hisun Tactic 400i; tipo não explícito no detalhe | Sem tipo individual | UNKNOWN |
| Motonil / 1061 | Oferta de consignação, texto descreve serviço | Categoria 65/MOTOS | UNKNOWN |
| Motonil / 1755 | BMW S1000 RR; descrição diz MOTO | Categoria 65/MOTOS, sem tipo específico | UNKNOWN |
| Motonil / 1635 | Kart Mirim, descrição de kart com motor Honda Biz | Categoria 65/MOTOS | UNKNOWN |

Regra candidata “categoria/breadcrumb Motos => motocicleta” foi reprovada por **pelo menos três falsos positivos** (carro, kart, serviço). Não foi colocada em produção. Política segura: seis desconhecidos, zero publicações, zero positivos classificados. Verdadeiros/falsos positivos e falsos negativos de um classificador ativo não são aplicáveis: não há classificador aprovado; abstenção não é prova de acurácia 100%. A amostra serve para refutar a regra fraca, não para estimar qualidade estatística.

No diagnóstico da página inteira, todos os 78 cards Thomas e 19 cards Motonil ficam UNKNOWN; esses números são itens observados, não contagens confirmadas de motos. Excluídos determinísticos por tipo: zero, pois não há campo confiável. Moto Marques: quantidade desconhecida; nenhum censo realizado. Nenhum UNKNOWN vira PartnerMotorcycle ou anúncio persistido.

## Evidências e limites

HTML e registros brutos locais em reports/partner-assessment-8-2, ignorados pelo Git. Documentos completos não são versionados. Fixtures de diagnóstico são mínimas, sanitizadas e não servem de collector. Fontes: [Thomas](https://thomasmotos.com.br/Veiculos), [Motonil categoria](https://www.motonil.com.br/MOTOS), [mapa oficial Motonil](https://www.motonil.com.br/index.php?route=information/sitemap), [Moto Marques robots](https://motomarquesmultimarcas.com.br/robots.txt).

A investigação eliminou a dúvida sobre as rotas examinadas; não demonstra inexistência universal de qualquer endpoint. Nenhum parâmetro ou endpoint não observado foi inventado. Para nova aprovação será necessária evidência pública melhor e, no caso Moto Marques, mudança das restrições de acesso. A regra de amostra 10–20 seguida de coleta completa só se aplica a parceiro candidato à aprovação; nenhum chegou a essa etapa.

## Complemento M8.3

O resultado acima é histórico. Na avaliação de 08/10/2026, Thomas apresentou 75 UNKNOWN e Motonil 19 UNKNOWN; não são anúncios publicados. Nenhuma nova visita ao domínio bloqueado da Moto Marques. Detalhes em [fontes alternativas](FONTES_ALTERNATIVAS_PARCEIROS.md).
