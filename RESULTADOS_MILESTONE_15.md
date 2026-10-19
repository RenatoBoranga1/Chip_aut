# Resultados — Milestone 15

## Estado e baseline

- Branch: `milestone-3-wr-motos-wip`.
- SHA inicial real: `27fff3b1fd7760ac9d214202ee1ed861440576d7`, árvore limpa, alinhada ao origin após fetch.
- Baseline executada antes das alterações: **1.155 aprovados em 262,50 s**.
- M8.4 visualmente homologado pelo usuário na solicitação; semântica operacional preservada.
- Trabalho iniciado e validado em 19/10/2026. Nenhum merge em main.

## Arquitetura e entregas

| Área | Resultado |
|---|---|
| Inbox | Serviço genérico para Thomas/Moto Marques, configuração por ambiente e política JSON; migração 016 |
| Detecção | CSV/XLSX por parceiro, hash SHA256, estados persistidos, cache de metadados, 100 novos/alterados por passagem |
| Validação | Leitura limitada, parsing CSV estrito, XLSX sem execução de macros, rejeição de fórmulas, erros recuperáveis |
| Preview | Até 20 linhas, total/válidas/inválidas/duplicadas, ausência de fabricante/modelo/ano/ID |
| Comparação | Novos, alterados, mantidos e ausentes contra estoque ativo consolidado válido; nenhuma alteração automática |
| Anomalias | Redução forte, mudança de IDs e qualidade baixa; níveis Informação/Atenção/Bloqueio e limiares configuráveis |
| Confirmação | Responsável, autorização/unidade, motocicletas e reconhecimento das anomalias; importador M8.4 reutilizado |
| Rejeição | Confirmação, responsável e motivo auditados; arquivo original preservado |
| Idempotência | Hash por parceiro, conteúdo já importado reconhecido; scans iguais não geram outra prévia/importação |
| Stale preview | Revisão, hash do arquivo e marcador do estoque conferidos novamente; divergência bloqueia publicação |
| Transação | Inbox e importação confirmadas na mesma unidade de trabalho; falha de matching reverte publicação |
| Motonil | ID externo, fallback conservador por URL válida, memória de decisões humanas e invalidação por identidade alterada |
| Triagem | Pendentes por padrão; conhecidos disponíveis explicitamente para reclassificação |
| Lote | Até 100 itens, um parceiro, confirmação e responsável; revisões/identidades validadas integralmente antes de publicar |
| Memória | Reutiliza Moto/Kart/Serviço/Outro; Unknown continua pendente. Somente Moto segue ao matching |
| Staleness | Thomas/Moto Marques 7 dias, Motonil 3 dias por padrão; configuração externa; WR usa sua política existente |
| Alertas | Seis tipos M15 agregados por parceiro/tipo, resolução/reabertura por transição, sem spam por polling repetido |
| Scheduler | Polling de preparação respeita intervalo por parceiro; run-now de arquivo prepara inbox, sem publicação |
| run-all | Mantém WR/auth/staging compatíveis e acrescenta inbox configurada; nenhum arquivo manual é aprovado sozinho |
| Indicadores | Arquivos aguardando/ inválidos, última atualização, dias, pendências, triagens evitadas e percentual |
| IA | Consultas locais de saúde/pendências/atualização e memória; botão para Parceiros; ações de escrita bloqueadas |
| Histórico | Detecção, validação, confirmação, rejeição, triagem, coleta e avisos com data, responsável e resultado |
| Performance | Metadados evitam reabrir arquivos conhecidos; hash sempre relido na confirmação; índices por parceiro/nome/hash |

Medição controlada com 100 arquivos sintéticos em cópia separada: primeira detecção/validação **18,632 s**; scan posterior **1,778 s**, com 100 conhecidos ignorados, nenhum novo arquivo ou erro. Valores são desta máquina, não garantia de latência para qualquer arquivo.

## Segurança e dados

Nenhuma credencial real, arquivo real novo ou consulta pública de parceiro foi necessária. Sem scraping adicional, bypass, exclusão/movimentação automática de arquivos, mudança de pesos ou escrita pelo Assistente. Confirmações de base/desenvolvimento continuam nos fluxos existentes.

Validação usa `reports/milestone-15/validation.sqlite3`, cópia SQLite de leitura da base operacional, com fixtures sintéticas. Banco operacional preservado: SHA256 **9ffce4d8fce8eaa88d0f8c2cf6c9d2f33a3ce53349cdfd3e7250a0a8450a5eee** no início e na conferência posterior.

- SQLite da cópia e operacional: `integrity_check = ok`; `foreign_key_check` vazio, ambos abertos em leitura para conferência.
- Nenhum banco, arquivo de estoque, segredo, log ou screenshot deve compor o commit.

## Testes e verificações

- 38 testes novos cobrem inbox E2E CSV/XLSX para ambos os parceiros, gates humanos, rejeição, mapping, snapshot/incremental, anomalias 100→4, hash/revisão/estoque antigos, rollback, cache, grande/ inválido, recuperação de VALIDATING, paths, locks, staleness/dedupe, scheduler, run-all, IA e AppTest.
- Cenário Motonil: 10 itens, 6 memórias reutilizadas, 4 pendentes; 2 Moto, 1 Kart, 1 Serviço; somente motos publicadas.
- Após ajuste de formulário e seletor: **38 aprovados em 21,81 s**, incluindo submissão AppTest sem publicação prévia.
- Regressão final da comparação, incluindo URLs de anúncio/imagem inalteradas: **38 aprovados em 38,12 s**. Campos source_url/primary_image_url são traduzidos para os campos de arquivo antes de comparar, evitando falsos alterados.
- Ruff check aprovado; Ruff format --check: **203 arquivos formatados**; compileall app/services/database/ui aprovado; git diff --check aprovado.
- Primeira suíte completa: **1.192 aprovados em 437,65 s**.
- Suíte completa de fechamento, incluindo o 38º teste novo: **1.193 aprovados em 385,22 s**. Regressões finais da inbox/comparação: **38 aprovados**, incluídos no total e não somados novamente.

## Navegador

Ambiente de teste na porta 8552, AI_PROVIDER=fake, exclusivamente banco e arquivos sintéticos. Validação concluída:

- Parceiros: semântica operacional M8.4 preservada; última coleta WR exibida na saúde, sem mudar sua política.
- Inbox: detecção de 2 arquivos Thomas e 1 XLSX Moto Marques; preview e comparação renderizados sem publicação.
- Anomalia: Thomas passou de referência de 100 anúncios para arquivo com 4; prévia mostrou 4 mantidos e 96 ausentes com alerta de forte redução e preservação no incremental.
- Rejeição: exportação errada rejeitada com motivo e responsável; arquivo original preservado.
- Confirmação Thomas: reconhecidas origem, motocicletas e anomalias; mensagem de importação com matching; estoque permaneceu 100 no incremental.
- Confirmação Moto Marques: XLSX de 10 linhas válidas confirmado com matching; 10 anúncios ativos.
- Motonil: seis decisões previamente humanas reaproveitadas; somente quatro desconhecidos apareceram. Lote de duas Moto confirmado após marca/modelo/ano por item; Kart e Serviço confirmados separadamente. Resultado: 4 Moto, 3 Kart, 3 Serviço, zero pendências, somente 4 anúncios no matching.
- Saúde: Thomas, Motonil e Moto Marques saudáveis, zero arquivos aguardando, zero inválidos ativos e zero triagem. Alertas resolvidos.
- Visão geral, Alertas, Indicadores gerenciais e Fila de revisão abriram sem erro de consulta. A fila da Thomas apresentou 100 registros após a importação assistida. Indicadores exibiram os dados novos e memória 6/16 observações (37,5%).
- Assistente: consulta de arquivos retornou contagens locais e referência de origem; pedido para confirmar arquivo recusado em modo somente leitura. Sem provider externo.

O navegador identificou recolhimento de painéis durante digitação; a revisão foi agrupada em formulário e retestada após reiniciar o servidor. Teste adicional identificou captura indevida da lista de outro parceiro no formatador do seletor; corrigido com mapa de rótulos estável. Nenhuma pendência visual remanescente.

Evidências locais em `reports/milestone-15/confirmacao-thomas.jpg`, `confirmacao-marques.jpg`, `triagem-lote.jpg`, `saude-final.jpg`, `assistente-somente-leitura.jpg`, ignoradas pelo Git.

## Limites

- Inbox é plana, CSV UTF-8 e XLSX, 10 MB/5.000 linhas/100 colunas; até 50 MB descompactados. Sem leitura recursiva, macro ou execução de fórmula.
- Configuração de pastas é opt-in; polling exige processo scheduler iniciado pelo operador. Nenhuma tarefa do Windows foi instalada.
- Cache usa tamanho/mtime/ctime; uma alteração que preserve todos os metadados pode só ser percebida na confirmação, que sempre relê hash.
- Sem ID/URL estável, o fallback de linha segue limitado ao mesmo conteúdo de arquivo, com aviso explícito.
- A tela e CLI listam 200 entradas recentes; leitura individual por ID permanece disponível. Histórico visual mostra 100 eventos recentes; banco mantém os demais.
- A taxa de memória mede observações reutilizadas ao longo das coletas, não identidades únicas; eventos anteriores ao M15 têm a informação que registravam.
- Diferenças de estoque usam o estado consolidado de importações já confirmadas. Ausentes em incremental nunca são retirados.

## Arquivos principais

`services/partner_inbox_service.py`, `services/partner_health_service.py`, `services/partner_operations_config.py`, `database/inbox_repository.py`, `database/migrations/016_partner_inbox.sql`, `config/partner_operations.json`, `ui/partner_inbox.py`, `app/partner_inbox.py`, `tests/test_partner_inbox.py`.

Integrações existentes: importador, staging, scheduler, run-all, painel Parceiros e consultas da IA. As únicas alterações nos testes de migração anteriores ajustam a expectativa de versão 15 para 16, sem remover testes.

[Operação diária](docs/OPERACAO_ASSISTIDA_PARCEIROS.md) · [Inbox e CLI](docs/INBOX_PARCEIROS.md).

Commit: `feat: add assisted partner operations and inbox automation`, na branch obrigatória. Suíte, verificações, integridade SQLite e navegador aprovados. SHA final, confirmação do push e estado Git são informados na entrega. O hash do próprio commit não é gravado no arquivo que o compõe.
