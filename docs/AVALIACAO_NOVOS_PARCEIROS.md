> Atualização M8.2 em 05/10/2026: a seção abaixo preserva a fotografia histórica do M8.1. A revalidação atual está em [Validação manual 8.2](VALIDACAO_MANUAL_PARCEIROS_8_2.md). Thomas tem 78 itens observados, Motonil 19. Moto Marques abriu no navegador comum, mas o robots consultado nele proíbe ChatGPT-User e agentes genéricos; HTTP simples segue 403. Nenhum candidato aprovado.

# Avaliação de novos parceiros — Milestone 8.1

Avaliação iniciada em 02/10/2026 e complementada em 05/10/2026. Requisições HTTP públicas com identificação MotoCoverageMonitor/0.3, sem login, cookies privados, proxy ou contorno de proteção. Amostragem técnica não equivale a coleta operacional completa.

| Critério | Moto Marques Multimarcas | Thomas Motos | Motonil |
|---|---|---|---|
| Principal | https://motomarquesmultimarcas.com.br/ | https://thomasmotos.com.br/ | https://www.motonil.com.br/ |
| Estoque observado | Não verificável | /Veiculos | /MOTOS |
| HTTP | 403 no acesso e robots; avaliação interrompida | 200 | 200 |
| robots.txt | 403; não foi possível verificar política | 404; política não publicada | 200, comentários sem diretivas de bloqueio |
| JavaScript necessário | Desconhecido | Não para listagem/detalhes examinados | Não para listagem/detalhe examinado |
| Paginação | Desconhecida | HTML informa 1–79 de 79, todos presentes | HTML informa 1–19 de 19, 1 página; limite selecionável |
| Filtros | Desconhecidos | Marca, modelo, ano, preço e ordenação | Ordenação e limite de itens |
| ID | Desconhecido | Número em /Veiculo/slug/ID/detalhes e idVeiculo | product_id, também presente nos botões públicos; nenhuma ação de carrinho executada |
| Detalhes | Desconhecidos | URL pública por ID | URL pública por slug |
| Imagem | Desconhecida | www.autocerto.com/fotos | Mesmo domínio, /image/cache/catalog |
| Fabricante | Desconhecido | Marca no título e filtro | Campo Marca no detalhe BMW examinado |
| Modelo/versão | Desconhecidos | Título e versão separada | Título livre com cor/ano; sem contrato estruturado uniforme verificado |
| Ano | Desconhecido | Listagem; fabricação/modelo no detalhe | Descrição livre |
| Preço | Desconhecido | Campo de preço | Campo de preço e descrição |
| Quilometragem | Desconhecida | Campo Km, com valores N/I | Descrição livre |
| Novo/usado | Desconhecido | Km zero não prova condição; não verificada | Texto ZERO KM em alguns itens; selo Novo também em usados, não confiável |
| Disponibilidade | Desconhecida | Presença na listagem, sem prova de venda | Em estoque no detalhe examinado |
| Estabilidade | Não avaliável | HTML renderizado acessível na amostra, sem garantia longitudinal | OpenCart acessível na amostra, sem garantia longitudinal |

## Decisões

- **Moto Marques: Não integrado — restrição técnica de acesso.** HTTP 403; nenhuma tentativa de contornar ou insistir após bloqueio.
- **Thomas: Não integrado — classificação de motocicletas não verificável.** A listagem inclui CHEVROLET SPIN. O detalhe do carro também usa a trilha Motos. Dois detalhes examinados não expõem tipo confiável. O endpoint público observado no JavaScript `/Home/ObterMarcasPorTipo/1` retorna CHEVROLET e TODOS; não é um filtro seguro de motos. Não foram inventados valores de tipo ou endpoints. Excluir por marca/título seria uma heurística fraca.
- **Motonil: Não integrado — dados insuficientes para seleção segura e uniforme.** A categoria MOTOS contém KART MIRIM e serviço de consignação. O kart menciona motor Honda; palavras ou fabricante não provam tipo. Sem metadados estruturados de tipo nos documentos examinados. Modelo/ano/km em texto livre também exigiriam validação adicional. Não se trata de site indisponível ou bloqueado.

Essas decisões dizem respeito às evidências disponíveis, não à impossibilidade definitiva de integração. Para reavaliar Thomas/Motonil, é necessário um filtro, feed ou campo público verificável que distinga motocicletas dos demais itens. Não há exclusões por IDs fixos nem collectors fictícios. Nenhum candidato foi habilitado ou persistido como estoque.

## Amostragem e limites

Thomas: uma listagem (79 itens), dois detalhes (carro e moto) e um endpoint de marcas observado. Motonil: página inicial, categoria (19 itens) e um detalhe BMW. Moto Marques: bloqueio encerrou a avaliação. HTML bruto fica apenas em reports/partner-assessment, ignorado pelo Git. Não houve coleta real completa de novos parceiros, pois nenhum passou pelo critério de integração. WR usa seu collector existente; nenhuma nova coleta da WR foi necessária para esta avaliação.

## Reavaliação M8.2

| Parceiro | Descoberta adicional | Decisão atual |
|---|---|---|
| Thomas | Menu e breadcrumb Motos também no carro; endpoint de marcas `/Home/ObterMarcasPorTipo/1` sem tipo individual; três detalhes auditados | DADOS INSUFICIENTES PARA CLASSIFICAÇÃO SEGURA |
| Motonil | Categoria técnica 65 mistura moto, kart e serviço; mapa HTML e rota `index.php?route=product/category&path=65&limit=25` confirmam a mistura | DADOS INSUFICIENTES PARA CLASSIFICAÇÃO SEGURA |
| Moto Marques | Browser público funciona; rotas `/multipla` e novo/usado observadas. HTTP 403 e robots com Disallow `/` para ChatGPT-User e `*`; inspeção encerrada | BLOQUEADO POR RESTRIÇÃO DE ACESSO |

A amostra mista de seis detalhes rejeita o uso da categoria genérica como prova de motocicleta. Os 97 cards observados são desconhecidos para publicação, sem estoque persistido. Não houve coleta adicional da WR. Ausência de rota segura observada não prova inexistência definitiva. Sitemaps de Moto Marques não foram consultados após a restrição explícita. Evidência, respostas às perguntas e URLs estão no relatório manual.
