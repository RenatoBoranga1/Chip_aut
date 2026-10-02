# Base consolidada V16

O adaptador central detecta `APLICACAO GERAL` e mantém o formato legado RESUMO_MDL. Somente a aba consolidada gera aplicações. APLICAÇÃO V16 e VERSOES são metadados: divergências de versões e totais geram avisos, sem somar registros históricos à base.

## Campos e identidade

As 13 colunas são reconhecidas pelo cabeçalho, inclusive quando reordenadas: VERS., MONTADORA, MODELO, ANO, SISTEMA, CABO, TIPO DE TESTE, NOVO SISTEMA, VÍDEO, TABELA FIPE, IMOBILIZADOR, FUNÇÕES AVANÇADAS e SCOOTER. Fabricante, modelo, ano e sistema são obrigatórios em cada registro; atributos técnicos vazios são aceitos. Cabeçalhos ausentes/duplicados, fórmulas e erros no conjunto principal impedem uma publicação válida.

A identidade permanece fabricante + modelo + ano, usando o normalizador existente, sem aproximação. VERS. é a versão de introdução da aplicação, separada da versão publicada da base. Sistema, cabo e versão não criam veículos adicionais. Valores originais são preservados. Flags reconhecem SIM/NÃO; valores desconhecidos ficam sem interpretação, com aviso e texto original disponível. `config/scanner_application.json` permite limitar anos (intervalo máximo existente: 1885–2100).

Presença não comprova suporte. Nenhuma coluna nova, tipo de teste, flag ou número de versão é convertido automaticamente em suporte: o novo formato permanece SEM_STATUS enquanto não houver regra documentada.

## Contagem e diferenças

Distinguem-se veículos, linhas de aplicação, aplicações sem repetição exata, chaves veículo/sistema/cabo e nomes distintos de sistema. Repetições exatas são diagnosticadas e preservadas para auditoria. Variantes técnicas e cabos diferentes também são preservados.

A comparação mantém o diff de veículos e acrescenta aplicações adicionadas/removidas/alteradas, atributos e sistemas. Uma troca de cabo é identificada apenas quando existe uma correspondência inequívoca de um cabo anterior para um novo no mesmo veículo/sistema; múltiplas alternativas permanecem adições/remoções. Mudanças de nomenclatura não são fundidas por similaridade.

## Publicação e consulta

O fluxo existente mantém upload, staging, SHA-256, comparação, confirmação humana, publicação transacional e atualização derivada recuperável. Upload não publica. Hash repetido não publica novamente; comparação desatualizada exige nova validação. Histórico e decisões permanecem preservados. Presença humana continua válida quando a identidade é determinística; ausência é vinculada à versão. Desenvolvimento não é encerrado automaticamente. Na publicação, prioridades sem mudança de evidência/política são retidas, incluindo decisões manuais; o agendamento temporal continua disponível.

A busca da base inclui sistema e cabo, retornando veículos sem multiplicá-los. O detalhe apresenta aplicações e atributos em tabela paginada. Indicadores gerenciais separam veículos/aplicações/sistemas. Nenhuma migração SQL foi necessária: payloads JSON e índices existentes comportam os atributos adicionais. Persistência usa lotes para veículos e snapshots.

## Limitações

Totais históricos de VERSOES não são a autoridade do consolidado. Fórmulas não são executadas. Textos técnicos desconhecidos exigem interpretação humana; não inferimos suporte. O painel não oferece rollback operacional. As publicações de validação usam bancos temporários; a planilha original não é alterada nem incluída no Git.


## Conclusão e conferência dos conflitos

O resumo separa `application_conflicts` (chaves veículo/sistema/cabo com variantes), `application_variant_rows` (linhas adicionais divergentes) e `support_conflicts` (conflitos de status). `conflicts` soma as duas classes de conflito; várias variantes da mesma chave não multiplicam a quantidade de chaves conflitantes. Avisos e registros originais continuam preservados. Conflito é informação para conferência humana, não autorização para inferir suporte ou descartar variantes.

Relatórios V16 antigos que não tinham esses contadores são apresentados com uma projeção somente leitura dos avisos salvos no staging ou em import_issues. O JSON histórico e seus eventos não são reescritos; a interface informa a conferência. Não há releitura da planilha durante a navegação.

Antes da confirmação, o painel repete arquivo, veículos, aplicações, sistemas, duplicidades, conflitos, diferenças e decisões afetadas. O botão Consultar veículos da base ativa abre a página interna existente sem reativá-la no menu lateral. A listagem diferencia Aplicações (linhas) de Sistemas; o detalhe mantém cabo, versão de introdução, tipo de teste e todos os atributos originais.

Na conferência de 02/10/2026, o banco operacional já continha a publicação V16 de 30/09/2026, importação 3. Nenhuma nova publicação operacional foi feita nesta conclusão. A mesma planilha não deve ser republicada: o SHA já registrado abre a versão existente. Uma futura troca operacional depende de autorização e confirmação explícitas.
