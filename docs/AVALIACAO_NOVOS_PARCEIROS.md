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
