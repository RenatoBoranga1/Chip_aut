# Operação assistida — Milestone 15

A semântica operacional do M8.4 permanece: WR automática; Thomas/Moto Marques por arquivo; Motonil semiautomática com triagem. **Operacional** significa canal disponível. **Saúde** e **Atualização** expressam a situação dos dados e das pendências.

## Rotina

1. Disponibilize as exportações autorizadas nas inboxes configuradas.
2. Deixe o scheduler preparar as revisões ou use **Verificar pastas de entrada** em Parceiros.
3. Confira prévia, comparação e anomalias. Confirme ou rejeite cada arquivo.
4. Na Motonil, confira os desconhecidos e identidades alteradas. Use lote para itens conferidos e revisão individual para exceções.
5. Consulte saúde, alertas e indicadores. O assistente pode informar e abrir Parceiros, sem confirmar ações.

## Saúde e desatualização

Política em `config/partner_operations.json`: Thomas/Moto Marques alertam após 7 dias desde a última importação; Motonil após 3 dias desde a última coleta concluída para staging. Prazos são configuráveis. WR mantém sua política de coleta existente. Sem primeira atualização, a situação é **Aguardando ação**, sem inventar data ou idade.

Estados: **Saudável**, **Atenção**, **Desatualizado**, **Aguardando ação**. Arquivo inválido, anomalia ou erro de coleta/auth levam a Atenção; dados acima do prazo levam a Desatualizado; arquivo ou triagem pendente levam a Aguardando ação. As contagens permanecem visíveis mesmo quando há mais de um motivo.

Alertas `PARTNER_FILE_WAITING`, `PARTNER_FILE_INVALID`, `PARTNER_IMPORT_STALE`, `PARTNER_IMPORT_ANOMALY`, `PARTNER_TRIAGE_PENDING`, `PARTNER_TRIAGE_STALE` são agregados por parceiro/tipo, reabertos/resolvidos por transição. Polls iguais não geram novos eventos ou ocorrências. O alerta legado TRIAGE_PENDING é resolvido quando o novo fluxo mantém a pendência equivalente, evitando aviso duplicado.

Abrir páginas e consultar IA é somente leitura. **Atualizar saúde e pendências**, scan, confirmação, rejeição, classificação e ticks do scheduler mantêm os alertas persistidos. A saúde mostrada é calculada com a data atual mesmo entre ticks.

## Motonil

ID externo reaparecendo não cria outra pendência. Sem ID, somente uma URL pública válida da Motonil pode fornecer chave estável; título isolado não fundamenta reutilização. Título, URL ou categoria alterados invalidam a decisão. Unknown/Indefinido continua pendente.

A memória reutiliza decisões humanas de Moto, Kart, Serviço ou Outro. Somente Moto segue ao matching. A taxa de reaproveitamento mede decisões conhecidas reutilizadas sobre observações das coletas registradas, incluindo repetições ao longo do tempo; não representa identidades únicas. Eventos anteriores ao M15 só contabilizam o reaproveitamento que já registravam.

Triagem em lote aceita até 100 itens da Motonil, exige confirmação e responsável, registra valor anterior/novo e motivo opcional. Para Moto, marca/modelo/ano são conferidos por item. Todas as revisões e identidades são validadas antes de publicar; um item antigo, outro parceiro ou identidade inválida reverte o lote inteiro. A revisão individual mantém a justificativa obrigatória do fluxo anterior. Reclassificações de conhecidos exigem seleção explícita na interface.

## Histórico, indicadores e IA

Histórico assistido reúne detecção, validação, confirmação, rejeição, criação/resolução de triagem, avisos de desatualização e coleta para staging. Guarda responsável, data e resultado, sem credenciais. Nenhuma senha/token é solicitado na inbox.

Indicadores e Parceiros mostram arquivos aguardando/ inválidos, última atualização, dias, triagem, reaproveitamento e taxa. Perguntas como “Qual parceiro está desatualizado?”, “Há arquivos aguardando confirmação?” e “Por que a Moto Marques está em atenção?” usam dados locais. O botão Abrir Parceiros é navegação; o assistente não recebe comandos, ferramentas ou acesso de escrita.

Ver [inbox e comandos](INBOX_PARCEIROS.md), [modos](MODOS_INTEGRACAO_PARCEIROS.md) e [triagem](TRIAGEM_MOTONIL.md).
