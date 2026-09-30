# Milestone 10 — Atualização e versionamento da base do scanner

## Referência e baseline

Branch `milestone-3-wr-motos-wip`; SHA inicial
`76d9888fdb298bf016ed5023fb4d4ceeb2854cfa`. Status limpo, branch/remote/log conferidos,
fetch e pull fast-forward sem alterações. Somente WR Motos permanece integrada. Sem merge em main.

Baseline isolada do commit inicial: **807 testes aprovados em 270,42 s**. A primeira rodada
compartilhou o diretório durante a adição da migration e detectou somente expectativas antigas
de schema; por isso a baseline foi repetida em uma extração imutável do commit, sem alterações.

## Arquitetura e migration

- `services/scanner_validation.py`: validação de arquivo, parser existente e comparação normalizada.
- `services/scanner_service.py`: preparação, comparação, confirmação e publicação transacional.
- `database/scanner_repository.py`: versões, diferenças, impactos e histórico; leitura sem migration.
- `services/scanner_refresh.py`: atualização recuperável de matching/cobertura/revisão, sem coleta.
- `database/scanner_alert_repository.py`: avisos resumidos na central e consulta de desenvolvimento.
- `ui/scanner_panel.py` e `app/scanner_base.py`: interface em português e CLI administrativa.
- `config/scanner_import.json`: limites e proteções obrigatórias.

Migration **014_scanner_versions.sql**, aditiva. Migrations 001–013 inalteradas. Tabelas de
versões, diferenças, impactos, eventos, trabalhos derivados, alertas e histórico de alertas.
Reconhece importações antigas; índice parcial permite uma única versão Publicada. O snapshot
operacional continua sendo a última importação, compatível com todos os serviços anteriores.
Eventos possuem proteção contra UPDATE/DELETE; versões publicadas não podem ser excluídas.

## Upload, armazenamento e validação

XLSX por Streamlit, limite configurável de 30 MiB, extensão e assinatura real, CRC, estrutura,
colunas obrigatórias e de suporte, limite de 512 MiB descompactado e 10 mil membros ZIP.
Recusa macros, vínculos externos, caminhos internos suspeitos e entradas duplicadas. Leitor
existente recusa DTD/entidades e não executa fórmulas. Não expande área vazia por formatação.

Bytes recebidos são preservados como BLOB no SQLite privado com ID e SHA-256; nome é apenas
informativo e normalizado para basename. Nenhuma planilha operacional nova é adicionada ao Git.
Não modifica `data/RESUMO_MDL.xlsx`. Registros/datas inválidos bloqueiam publicação; conflitos,
duplicidades e status desconhecidos são exibidos, preservando a interpretação conservadora.

## Versionamento e comparação

Preparação validada ou rejeitada fica independente de `imports`; estados publicados e
substituídos são preservados. Arquivo com hash existente abre sua versão, sem republicação.
São comparados adicionados, removidos, alterados e mantidos. Alterações incluem nomenclatura,
status, sistemas e campos de suporte originais. Identidade usa normalização existente; versão
continua no modelo completo. Troca de chave gera adição/remoção e pista de revisão, sem fusão fuzzy.
V10–V16/MC não recebem semântica nova. Presença na base nunca comprova suporte.

## Decisões humanas e matching

Impacto usa decisões vigentes e seu escopo compartilhado existente. Ausência/rejeição vinculada
à versão anterior exige revalidação. Correspondência confirmada conserva validade se o alvo e
a identidade permanecem; remoção/alteração incompatível retorna à revisão. Suporte alterado é
sinalizado mesmo com vínculo válido. Dúvida permanece pendente. Histórico humano não é apagado.

Após publicação, anúncios ativos persistidos são agrupados pela coleta de origem e rematcheados
sem nova coleta/HTTP. São geradas novas coberturas e atualização da fila, preservando resultados
anteriores. Regras oficiais de revisão impedem reaproveitamento de memórias incompatíveis.

## Desenvolvimento, prioridade e alertas

Itens ativos com identidade estrita adicionada/alterada recebem aviso de possível atendimento.
Nenhuma etapa, responsável, checklist, prioridade ou conclusão é alterada automaticamente.
O detalhe mostra o aviso correspondente à versão ativa. Priorização do M9 é verificada após
publicação/atualização e pelo scheduler, preservando a escolha humana e histórico da avaliação.

Alertas com namespace próprio, por versão/parceiro e deduplicados: publicação com totais de
adições/remoções, decisões a revalidar, possível atendimento de desenvolvimento e falha de
publicação. Resumos evitam um alerta por linha. A central abre o detalhe da versão e preserva
histórico das ações, sem criar execução fictícia de coleta.

## Transação, concorrência e recuperação

Confirmação explícita, responsável e justificativa obrigatórios. O serviço confere novamente
bytes/hash, payload preparado, regras, base ativa e token de decisões/desenvolvimento. Comparação
desatualizada é recusada e precisa ser refeita. Publicação usa a unidade `BEGIN IMMEDIATE` existente:
snapshot, versão ativa, histórico, trabalho derivado e avisos são confirmados juntos.
Falha antes do commit reverte tudo; auditoria de falha separada não altera a base ativa.

Etapa derivada usa outra transação e trabalho durável. Falha deixa Pendente; botão/CLI/scheduler
permitem retomar sem repetir publicação. Trabalho de versão ultrapassada é substituído. Prioridade
usa sua manutenção recuperável existente, independentemente da conclusão do trabalho de matching.
A CLI antiga de importação recusa atualizar banco já inicializado; bootstrap permanece disponível.

## Interface e barra lateral

Nova página com upload, versão atual, SHA, contagens, diferenças/impactos paginados (30), histórico
de versões (20), detalhe de suporte, avisos, eventos, comparação e confirmação. Renderização não
faz parsing ou matching. Cancelar não publica. Modo somente leitura bloqueia escritas.
Identificada a causa do menu inacessível: o CSS antigo escondia `stToolbar`, que também contém
o botão de expansão. O CSS passou a esconder somente o botão Deploy e o menu do Streamlit.
Sidebar inicia expandido; controles nativos de recolher/reabrir testados em 390 px, sem
segunda navegação. Seleção da versão permanece estável durante envio do formulário.

## Testes e navegador

807 testes anteriores preservados; expectativas de schema atualizadas para 14. **39 novos testes**
cobrem upload, corrupção/macros, tamanho, hash, duplicidade, travessia de caminho, parser esparso,
campos obrigatórios, staging, diferenças, nomenclatura, conflitos, confirmação, concorrência,
rollback transacional, adulteração, falha/retomada, revalidação, desenvolvimento, prioridade,
alertas, scheduler, CLI, histórico, modo somente leitura, dashboard e seleção após envio.

Fluxo Edge/Playwright concluído com fixture isolada: upload, prévia sem mudar referência ativa,
recusa sem confirmação, publicação confirmada, reload, sidebar expandido em desktop e navegação
única em tela de 390 px. Nenhum erro JavaScript de página. Capturas inspecionadas visualmente,
mantidas fora do Git. Verificações Ruff, formatação, compileall, imports e diff sem erros.

## Validação real controlada e desempenho

Referência: cópia do banco e cópia sintética derivada do XLSX original, sem publicar no banco real.
Dados originais: 3.994 registros identificados, 3.993 válidos, 1.337 motos, 4 duplicidades,
1 conflito, 1 linha rejeitada e 8 datas inválidas; 2.329 registros com situação não definida.

- Validação/leitura do arquivo original: **6,3830 s**.
- Preparação e comparação sintética: **7,6354 s**.
- Antes/depois: **1.337 motos** em cada versão.
- **2 adicionadas, 2 removidas, 1 alterada e 1.334 mantidas**.
- Uma pista de identidade pendente; alteração de modelo aparece como removida/adicionada.
- Nenhuma decisão humana ou item de desenvolvimento afetado no conjunto real disponível.
- Preparação **Rejeitada** pelos problemas preexistentes de linha/data, comprovando o bloqueio.
- Importação operacional permaneceu ativa. Integridade SQLite ok e nenhuma violação de FK na cópia.

SHA-256 do dump do banco original, antes e depois:
`3ce061697c03113686625f496b37144ca2103caa4cbb8da854a764e133bff250`.
SHA-256 de ambas as cópias originais do Excel, antes e depois:
`32aac84eedec3e8b34e48920bc4bf03c17ccc773886cd84490d2e6f64f57cfdc`.

## Limitações

A versão real contém inconsistências que devem ser corrigidas em nova planilha antes de publicação.
Não houve alteração/migration no banco operacional original nesta entrega. A migration será aplicada
na primeira operação de escrita autorizada. Preparações aumentam o banco por guardarem os bytes
originais; planeje backups/espaço. Históricos/diferenças são paginados na interface, mas a comparação
precisa carregar uma base normalizada por vez. As medidas cobrem o volume observado, sem promessa
de escala ilimitada. Similaridade não resolve mudanças de identidade automaticamente.

Rollback de versão anterior não foi exposto: requer nova publicação auditada e revalidação integral;
um botão que trocasse apenas o ponteiro seria inconsistente com os serviços existentes. Recuperação
transacional e retomada de derivados estão implementadas/testadas. Biblioteca interna de importação
legada permanece para compatibilidade administrativa; atualizações operacionais devem usar o novo
serviço ou CLI com confirmação. Não foram implementados novos parceiros nem o Milestone 11.

## Resultado final

**846 testes aprovados em 272,61 s** (807 preservados + 39 novos). Após a correção
do CSS da barra lateral, os 39 testes específicos passaram novamente em 33,81 s,
e os controles de recolher/reabrir foram confirmados no navegador em 390 px.
Ruff, formatação, compileall, imports e git diff --check aprovados.
Somente código, testes e documentação integram o commit; dados, capturas e logs ficam locais.
