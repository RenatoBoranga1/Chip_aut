# Atualização e versionamento da base do scanner

## Fluxo operacional

Abra **Atualização da base do scanner**. A barra lateral inicia expandida e mantém o
controle nativo para recolher/expandir, inclusive em telas pequenas.

1. Consulte a importação operacional e seu SHA-256.
2. Envie um `.xlsx`, informe responsável e observações e clique em **Validar e comparar arquivo**.
3. Confira os totais, diferenças, campos de suporte e impactos nas decisões/desenvolvimento.
4. Corrija registros ou datas inválidos na origem e envie um novo arquivo, se a versão foi rejeitada.
5. Para uma versão validada, informe responsável e justificativa da publicação, marque a confirmação
   e clique em **Confirmar publicação**. Cancelar mantém a preparação no histórico sem publicá-la.

O upload não publica e a navegação não reprocessa Excel nem executa matching. A preparação
salva o conteúdo recebido, sem alterá-lo, em BLOB na tabela `scanner_versions` do banco privado.
Cada preparação tem ID próprio, nome somente informativo e SHA-256. Nenhum nome enviado é
usado como caminho. O original `data/RESUMO_MDL.xlsx` permanece intocado; o diretório `data/`
e extensões de planilha/banco continuam ignorados pelo Git.

## Validação

Limite padrão 30 MiB, extensão, assinatura ZIP, CRC, estrutura OOXML, limites de conteúdo
descompactado e entradas, ausência de macros/vínculos externos, cabeçalho reconhecido e
colunas de suporte. DTD/entidades são recusados pelo leitor existente. Fórmulas não são executadas;
linhas com fórmulas/erros são rejeitadas. O parser continua percorrendo apenas XML e células
materializadas, sem expandir a dimensão artificial de aproximadamente um milhão de linhas.

Aba necessária significa uma tabela reconhecida com MONTADORA, MODELO, ANO, SISTEMA e uma
coluna LANC./SIT.; não existe nome fixo de aba. Abas auxiliares são sinalizadas. Modelo completo
preserva versão conforme as regras existentes; não se inventa uma identidade por aproximação.
Registros inválidos e datas inválidas bloqueiam publicação. Duplicidades exatas e conflitos
são mostrados; conflitos preservam o status conservador do parser, sem fabricar suporte.
V10–V16 e MC permanecem sem interpretação nova.

## Comparação e impacto

A comparação usa chaves normalizadas. Mesma chave com nomenclatura, status ou campo de suporte
alterado fica em Alteradas; mudanças de identidade geram removida/adicionada. Coincidência de
fabricante/ano entre removidas e adicionadas gera apenas pista de revisão, nunca fusão automática.
Detalhes e impactos são paginados (30); histórico de versões tem 20 registros por página.

Decisões usam a regra oficial de escopo da revisão: ausência/rejeição da base anterior precisam
de revalidação; confirmação de presença continua válida quando o alvo e sua identidade permanecem.
Mudanças de suporte são destacadas mesmo com identidade preservada. Dúvida continua pendente.
Nenhuma decisão anterior é apagada nem substituída por decisão humana fabricada.

Desenvolvimento recebe aviso de possível atendimento quando sua identidade estrita passa a
constar ou é alterada. Presença não confirma suporte. Etapa, responsável, checklist, prioridade
e histórico do item não são modificados. A prioridade operacional é recalculada pelo mecanismo
do Milestone 9 quando ativado; sua escolha manual permanece e a versão da base é registrada.

## Publicação, concorrência e recuperação

Migration aditiva 014 registra versões, diferenças, impactos, eventos, trabalhos derivados e
alertas. Importações antigas são reconhecidas. `MAX(imports.id)` continua sendo a única referência
operacional usada pelo matching: inserir o novo snapshot e marcar a versão publicada ocorre
na mesma transação `BEGIN IMMEDIATE`. Índice parcial admite uma única versão Publicada.

Antes de confirmar, o serviço relê/revalida os bytes, hash, resultado preparado e regras;
confere a importação usada na comparação e o estado das decisões/desenvolvimento. Mudança
concorrente exige **Atualizar comparação** e nova confirmação. Falha anterior ao commit reverte
a publicação; a versão anterior permanece ativa. O histórico de falha é registrado separadamente.
SHA já registrado abre a versão existente e impede publicação redundante.

Após commit, um trabalho persistido rematcheia os anúncios atuais já salvos e revalida a fila,
sem executar coleta ou HTTP. Essa etapa também é transacional. Falha deixa o trabalho Pendente,
visível no detalhe, com **Retomar atualização**. O scheduler tenta novamente nos seus ciclos.
Uma versão mais recente substitui trabalhos antigos pendentes. O histórico de matching e
cobertura anterior permanece. Até a conclusão, as consultas existentes sinalizam resultados
da base anterior como desatualizados. A priorização usa sua própria verificação recuperável.

Alertas são resumos deduplicados por versão/parceiro: publicação (incluindo adicionadas/removidas),
revalidação humana, possível atendimento de desenvolvimento e falha. A central oferece acesso
à versão e ações de leitura/encerramento, sem inventar execução de coleta.

## CLI

```powershell
python -m app.scanner_base current
python -m app.scanner_base list
python -m app.scanner_base validate nova.xlsx
python -m app.scanner_base compare nova.xlsx --author "Renato" --note "Atualização recebida"
python -m app.scanner_base show --version 3
```

Os IDs são exemplos. `show` fornece `parent_import_id` e `impact_token` da comparação.
Para publicar explicitamente:

```powershell
python -m app.scanner_base publish --version 3 --parent 2 --token TOKEN_DA_COMPARACAO --author "Renato" --note "Diferenças conferidas" --confirm
python -m app.scanner_base resume --version 3
```

`--db` seleciona o banco; `--read-only` ou `MOTO_READ_ONLY=1` impede comandos de escrita.
`validate` apenas lê; `compare` prepara e persiste sem publicar. A CLI antiga `app.import_base`
permanece para bootstrap de banco vazio e recusa atualização de uma base já existente. O serviço
interno antigo permanece compatível com integrações/testes administrativos, registrando versões;
para atualizações operacionais use o novo serviço com confirmação.

## Configuração e limites

`config/scanner_import.json` ou `MOTO_SCANNER_IMPORT_CONFIG`: versão de configuração 1,
`enabled`, `max_upload_mb` e proteções obrigatórias. Publicação automática não é permitida.
Desabilitar impede escritas, preservando consultas e histórico. O arquivo inteiro fica no
banco privado; planeje espaço/backups conforme o volume de versões. Os históricos publicados
não têm exclusão no painel; eventos têm triggers de imutabilidade.

Reversão de uma versão publicada como base ativa não foi exposta neste milestone. Recuperar
um backup consistente, com os processos parados, continua sendo procedimento administrativo;
não há botão que apenas troque um ponteiro deixando decisões e avaliações incoerentes. Uma
futura reversão deverá ser uma nova publicação auditada com todos os impactos revalidados.

Os pesos de prioridade e as regras de suporte não mudaram. Só WR Motos permanece integrada.
