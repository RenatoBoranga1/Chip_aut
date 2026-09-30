# Dicionário dos indicadores gerenciais — Milestone 13

A página **Indicadores gerenciais** é uma consulta. Não executa coleta, matching, manutenção, migração, decisão, publicação ou atualização de prioridade. Parceiros vêm do PartnerRegistry; a operação habilitada continua WR Motos.

## Período, população e unidade

As datas são inclusivas no fuso America/Sao_Paulo, convertidas para intervalo UTC com fim exclusivo. O dia atual termina no instante consultado; o corte aparece na página e CSV. A comparação usa a mesma duração transcorrida imediatamente anterior ao início. Portanto, durante o dia atual o período anterior pode começar em horário intermediário. Datas inválidas/futuras são rejeitadas; timestamps ausentes ou sem fuso não são inventados.

Os cards de eventos contam eventos no período. Os cards de situação reconstroem o encerramento. Estoque usa a última observação de cada ID e a última coleta COMPLETE como evidência de saída; PARTIAL não elimina veículos não observados, FAILED/CACHED não provam ausência. A criação de um anúncio usa first_seen_at, não o número de coletas.

Identidades completas usam a assinatura estrita existente: parceiro, fabricante, modelo, versão, ano. Não há fuzzy para agrupar demanda. Identidades incompletas não entram em possíveis novas identidades. Novo anúncio ≠ não encontrado automaticamente ≠ ausência confirmada pelo usuário.

## Cards e listas

| Indicador | Definição |
|---|---|
| Novos anúncios | IDs de anúncios cuja primeira observação ocorreu no período; inclui anúncios que saíram do estoque. |
| Possíveis novas identidades | Identidades completas distintas no estoque com matching não encontrado e sem ausência humana válida. Hipótese, não ausência. |
| Ausências confirmadas no período | Identidades distintas no estoque com ausência humana válida na base selecionada, decidida no período. |
| Ausências confirmadas acumuladas | Identidades distintas no estoque com ausência humana ainda válida no encerramento. |
| Revisões abertas no período | Itens da fila criados no período, incluindo identidades históricas. |
| Revisões concluídas no período | Itens distintos com ao menos uma decisão conclusiva (existe/ausente/ignorar) no período; não implica conclusão ainda válida. |
| Revisões pendentes | Itens de identidade vigente no estoque com estado pending, deferred ou invalidated no encerramento. |
| Decisões alteradas | Eventos de decisão no período com referência à decisão anterior; não conta reaproveitamento de memória. |
| Revisões reabertas | Itens distintos com evento de invalidação no período; não inclui reabertura inferida sem evento persistido. |
| Desenvolvimentos ativos | Itens vinculados ao parceiro em etapa diferente de concluída/descartada no encerramento. |
| Entradas em desenvolvimento | Itens vinculados ao parceiro criados no período. |
| Desenvolvimentos concluídos | Itens distintos que transitaram para COMPLETED no período; reabertura posterior não apaga a entrega histórica. |
| Desenvolvimentos descartados | Itens distintos que transitaram para DISCARDED no período. |
| Novos alertas | Alertas únicos por origem e ID criados no período; recorrências não são novos alertas. |
| Alertas relevantes | Alertas não arquivados/resolvidos de severidade ALTA ou CRITICA no encerramento, independentemente da data de criação. |
| Cobertura conhecida | Anúncios no estoque com resultado efetivo SUPORTADO, SEM_SUPORTE ou SUPORTE_PARCIAL na base consultada. |

Cada card tem uma lista construída da mesma população: seu tamanho é o valor exibido. As listas são paginadas em 30 registros. Ausências e possíveis identidades mostram um anúncio representativo por identidade; não todos os anúncios repetidos. Links levam à revisão operacional existente, que pode mostrar uma situação posterior ao corte histórico. O detalhe de desenvolvimento reutiliza a página existente.

## Revisão humana e tempos

A validade reaproveita `ReviewRepository._evaluate`, com ocorrência, observação e decisões anteriores ao corte. Presença exige que o alvo permaneça com a identidade confirmada; ausência/rejeição exige a mesma versão da base. Decisões futuras não vazam para o passado. A versão padrão é a última importação publicada até o corte; selecionar uma versão permite analisar a validade nessa versão, sem reativá-la.

Tempo de revisão = criação do item até sua primeira decisão conclusiva (CONFIRMAR_MATCH, NAO_EXISTE_NA_BASE ou IGNORAR), quando essa primeira conclusão está no período. Repetições posteriores não geram novas amostras. Média, mediana e tamanho da amostra são sempre apresentados juntos; sem amostra, valor indisponível, não zero. Tempo não representa horas de trabalho.

Revisões concluídas contam itens com evento conclusivo no período; podem ter sido reabertas posteriormente. Revisões reabertas contam itens com evento persistido de invalidação. Não se inventa uma reabertura apenas porque o estado reconstruído mudou. Decisões alteradas contam eventos com previous_decision_id; não julgam acerto nem produtividade pessoal.

## Desenvolvimento

Estado e responsável são reconstruídos dos eventos CREATE e alterações. Cada item vinculado ao parceiro conta uma vez, mesmo com vários anúncios de origem. Itens globais criados apenas a partir do scanner, sem vínculo WR, não pertencem ao recorte WR. A vinculação de origens não tem auditoria temporal própria suficiente para reconstituir sua data de criação: esse vínculo usa a relação disponível na consulta.

Tempo de etapa = entrada até saída, para passagens encerradas no período. Reentrada gera outra passagem; duração anterior ao início do período permanece na amostra. Etapas abertas não entram na média. Tempo total até conclusão = criação até primeira transição COMPLETED dentro do período, por item; reabertura não apaga a entrega. Top 10 usa tempo na etapa vigente, com responsável, prioridade operacional quando avaliada e última atualização. Não confunde prioridade manual de desenvolvimento com a prioridade do Milestone 9.

Prazos vêm exclusivamente de config/development.json: atualmente 7 dias aguardando informação, 30 em desenvolvimento, 14 em validação. Demais etapas não recebem prazo inventado. Não há avaliação individual ou ranking de responsáveis.

## Taxas

- Conclusivas / casos com decisão no período: itens distintos com conclusão divididos pelos itens distintos com qualquer decisão.
- Novas revisões concluídas / novas revisões: coorte criada no período que também teve conclusão nesse período.
- Novos desenvolvimentos concluídos / novos desenvolvimentos: mesma regra de coorte, usando criação e transição COMPLETED.
- Decisões reaproveitadas / decisões conclusivas válidas: anúncios com estado reused divididos pelos anúncios com presença/ausência humana válida no encerramento.
- Matching automático resolvido / anúncios com matching vigente: resultado automático sem requires_review dividido pelos anúncios avaliados na versão consultada. Não significa suporte nem confirmação humana.
- Cobertura conhecida / estoque: SUPORTADO, SEM_SUPORTE ou SUPORTE_PARCIAL divididos pelo total de anúncios no estoque.

Numerador e denominador aparecem juntos. Denominador zero gera indisponível. Aumento/redução recebem setas neutras; não são classificados como bons/ruins.

## Séries e cobertura

Histórico de cobertura/matching: última avaliação de cada dia, versão e anúncio. Usa data de avaliação, não data da coleta reutilizada. Reexecuções no mesmo dia/base/ID não duplicam pontos. Série mostra a cobertura registrada naquela avaliação; ausência histórica não é ausência válida na base atual. Dias sem avaliação não são preenchidos com zero. Não somar pontos para medir novas motos. Dados de dias diferentes são populações diferentes, não uma pesquisa estatística controlada.

Decisão humana: distribuição e percentual no encerramento, e série de eventos humanos por dia e ação. Eventos não equivalem a estoque diário de decisões. Ausências são detalhadas por fabricante, ano e origem de pendência. Recorrência conta IDs distintos para a mesma identidade no período, não coletas repetidas.

Cobertura mantém os significados existentes, inclusive EM_ANALISE e SEM_STATUS. Nenhuma interpretação nova é atribuída a V10–V16/MC.

## Base e versões

Somente imports publicados podem ser selecionados. Total e distribuição da base usam fabricante/modelo/ano. Filtros de responsável, prioridade e estados operacionais não pertencem à base global, como explicado na página.

Adicionadas/removidas/alteradas comparam com a publicação imediatamente anterior. Na primeira importação, todas são adições. O relatório M10 é usado quando disponível sem filtros de identidade; para recortes, compara os snapshots de veículos, desconsiderando apenas record_count. Casos com revalidação solicitada e eventos de invalidação são globais à publicação. Decisões válidas reavaliadas contam decisões distintas em itens cuja ocorrência foi avaliada na base selecionada, com validade ainda preservada; isso não registra uma nova decisão humana.

## Prioridades, alertas e filtros

Prioridades usam última avaliação e override anteriores ao corte, com identidade compatível com o anúncio. Sem avaliação: Não avaliada. Não há recálculo. As tabelas opcionais ausentes são sinalizadas, sem migração.

Alertas contam uma vez por origem (pipeline/desenvolvimento/prioridade/scanner) e ID. Status vem do histórico anterior ao corte; recorrências não aumentam novos alertas. Severidade/tipo dos alertas de pipeline são os valores armazenados atuais, pois não existe trilha completa de classificação histórica. Alertas gerais sem vínculo são excluídos quando filtros de veículo/estado exigem correspondência.

Filtros operacionais são aplicados à situação reconstruída no encerramento; nas séries históricas, fabricante/modelo/ano pertencem ao registro da avaliação, enquanto prioridade/responsável/estado vêm do vínculo no encerramento. Isso permite analisar eventos do recorte selecionado sem alegar reconstrução de dimensões sem histórico. Desenvolvimento vinculado a várias origens usa contexto humano/base do primeiro anúncio encontrado e maior prioridade operacional; um anúncio com vários desenvolvimentos usa o mais recente para os filtros de etapa/responsável.

## Cache, integridade e limites

Repository usa SQLite mode=ro, query_only e transação de leitura única para os dois períodos. Não há migração nem snapshot gerencial novo: observações, ocorrências e eventos já permitem os cálculos acima. Lacunas são explicitadas, não corrigidas silenciosamente.

Cache em memória limitado a 12 relatórios, chave com caminho, identidade do arquivo SQLite e WAL (mtime/ctime/tamanho), parceiro, período, versão, filtros, prazos e janela de 30 segundos. Qualquer escrita de coleta/decisão/desenvolvimento/publicação/priorização altera a chave; cópias profundas protegem o valor cacheado. A escala validada está documentada no relatório; o histórico é carregado por parceiro e pode exigir agregação adicional em bancos muito maiores.

CSV UTF-8 com BOM e separador ponto e vírgula inclui corte, versão, filtros, definições, cards, tempos, etapas, taxas, estatísticas da base e comparações. Protege células contra fórmula. Não inclui raw_text, fotos, justificativas ou nomes de revisores. Um filtro explícito de responsável pode aparecer como metadado do recorte exportado.
