# Milestone 7.1 — Confirmação humana de presença na base

25/09/2026. Continuação de `fc950cd7c7a0d07bb4280a0af3e2c08ca163164a`,
branch `milestone-3-wr-motos-wip`. Milestone 8 adiado por solicitação do usuário;
somente WR Motos permanece integrada. Sem merge em main.

## Inspeção e baseline

README, relatório 7, fila, memória humana, dashboard, scanner, alertas,
oportunidades, desenvolvimento, imagens, persistência e testes inspecionados.
Baseline antes de editar: **664 aprovados em 135,34 s**. A árvore estava limpa
na referência informada; fetch não trouxe alteração da branch.

A confirmação já exigia chave real, autor, justificativa, versão otimista e
solicitação idempotente. A melhoria torna esse fluxo acessível diretamente na
linha do anúncio, sem duplicar matching ou decisões.

## Estados e fonte de verdade

`services/review_presentation.py` projeta rótulos a partir da avaliação vigente
da revisão. Não persiste outra decisão nem cria nova tabela:

| Decisão humana | Fonte existente | Situação na base |
| --- | --- | --- |
| Pendente | Sem decisão válida | Automática encontrada, ambígua ou pendente de confirmação |
| Existe na base | CONFIRMAR_MATCH válido, com scanner_key | Existe na base — confirmado |
| Não existe na base | NAO_EXISTE_NA_BASE vigente | Ausência confirmada |
| Em dúvida | DEIXAR_PENDENTE | Em dúvida |

Memória manual legada válida também é reconhecida. Resultado automático exato
sozinho nunca fabrica decisão humana. Rejeição de candidato e caso ignorado
permanecem sem afirmação de presença/ausência: mostram Pendente e acesso ao
histórico. Decisão invalidada volta a Pendente, preservando evento anterior.

Novo anúncio no parceiro não significa nova moto para a base. Não encontrado
automaticamente não declara ausência. Ausência confirmada não significa sem
suporte. O resultado automático original permanece consultável.

## Formulário e busca

- Link final **Registrar decisão** ou **Ver / alterar decisão**, na linha correta.
- Abre outra aba diretamente com revisão e parceiro na URL; valida ambos.
- Resumo com foto/placeholder, fabricante, modelo completo, versão, ano, parceiro,
  anúncio, resultado automático e decisão atual. Motivos e sugestões em seção
  expansível; cobertura, prioridade e auditoria permanecem disponíveis abaixo.
- Candidatos automáticos compatíveis aparecem primeiro no seletor existente.
- **Buscar na base do scanner** filtra fabricante, ano e texto/modelo/chave, com
  tolerância a espaços e hífens. Mostra a quantidade de resultados e permite
  selecionar explicitamente um registro, inclusive fora dos candidatos fuzzy.
- Confirmação de presença exige chave da base atual. Fabricante e ano devem ser
  compatíveis, conforme as regras anteriores; não foi relaxada a validação.
- Modelo completo do scanner conserva a versão: não foi inventado campo separado.
- Autor e justificativa obrigatórios; versão otimista e idempotência preservadas.
- Nova decisão acrescenta histórico. Confirmar uma identidade não muda suporte.
- Reutilização na próxima coleta usa a memória já existente, respeitando escopo,
  identidade, base e validade do alvo. Ausência expira em nova versão da base.

O formulário foi extraído para `ui/human_decision.py`, compartilhado pelo detalhe
anterior e pelo novo acesso direto. Não existe um segundo caminho de escrita.

## Situação no parceiro e origem

Consulta somente leitura usa IDs das observações, coletas completas/parciais,
marcador de saída do estoque e histórico de reutilização do pipeline:

- **Novo anúncio**: primeira observação na coleta efetiva mais recente.
- **Já conhecido**: observado anteriormente; inclui nova verificação completa que
  reutilizou uma coleta/cobertura sem rematching.
- **Reapareceu**: ID conhecido antes da coleta completa anterior, ausente naquela
  coleta e novamente observado.
- **Saiu do estoque**: ausência já confirmada pela persistência de coleta completa.

Cache/falha não cria desaparecimento; parcial não marca itens faltantes como
ausentes. Consultas são sempre por parceiro, sem colisão entre IDs iguais.
Primeira/última aparição vêm do anúncio, não da criação da revisão.
Indicadores são relativos à última observação efetiva, não a uma janela de dias.

Origem da pendência pode combinar novidade do parceiro, não encontrado
automaticamente, ambiguidade, aproximação ou suporte incompleto. Suporte só é
apresentado como motivo quando o resultado efetivo já permite essa afirmação.

## Telas e integrações

Fila: Foto, Revisão, Fabricante, Modelo, Ano, Resultado automático, Decisão humana,
Situação no parceiro, Origem da pendência e Ação. Cobertura e prioridade saíram
somente dessa tabela; filtros, detalhe, banco e regras continuam disponíveis.

Possíveis novas motos: decisão humana, situação no parceiro/na base, primeira
aparição e ação direta. Preserva grupos de ausência confirmada, hipótese e revisão.
Casos explicitamente Em dúvida permanecem em Ainda em revisão. Estoque também
apresenta as novas situações. Interface nova em português, incluindo placeholders.

Alertas de novidade usam **Novo anúncio no parceiro** e explicam que isso não
declara ausência na base. Eventos históricos não são reescritos; seu tipo e o
detalhe da interface deixam a distinção explícita. Nenhuma tarefa de desenvolvimento
é criada automaticamente por novidade, falha de matching ou decisão de revisão.

## Testes e verificações

**664 anteriores + 42 novos = 706 aprovados em 156,66 s.**
Um teste anterior de apresentação foi adaptado à remoção solicitada da coluna
Prioridade; continua verificando que o filtro seleciona exatamente os IDs de
alta prioridade. Nenhum teste anterior foi excluído.

Casos novos: quatro estados humanos, exato sem confirmação, invalidação sem
escrita, alteração e histórico, vínculo obrigatório/incompatível/inexistente,
busca compacta e filtros, seleção fora do fuzzy, memória na coleta seguinte,
novidade/saída/retorno, cache/parcial/falha, reutilização do pipeline, IDs iguais
em parceiros diferentes, motivos, links diretos, layout, somente leitura,
alertas e ausência de criação automática de desenvolvimento.

Após ajuste exclusivamente textual dos placeholders, **90 testes de UI/revisão
passaram em 34,73 s**. Ruff, formatação, compileall, imports principais,
integridade/chaves estrangeiras SQLite e `git diff --check` passaram.
Não há nova migration; 001–011 permanecem intactas.

## Navegador e dados reais

Playwright com Edge instalado (agent-browser indisponível): link real da tabela
abre a revisão correta; confirmação sem chave é recusada; busca manual seleciona
registro fora do fuzzy; grava presença e depois ausência, preservando duas decisões
na fixture; retorno à fila e oportunidades exibe a decisão. Nenhum desenvolvimento
foi criado. Zero erros de página/console. Capturas de fila, formulário, busca e
oportunidades inspecionadas; servidor novo usado após ajustes de apresentação.

Um ensaio de automação foi ajustado para preencher novamente o autor ao iniciar
outra revisão; o aplicativo corretamente manteve essa exigência. A inspeção visual
identificou dois placeholders padrão em inglês, corrigidos e novamente verificados.

Dados reais usados somente para leitura: **171 anúncios, 154 revisões, zero
decisões humanas reais**. Fila, oportunidades e formulário somente leitura passaram
no navegador; botão Salvar ausente. Abertura da home e fila observada em **7,950 s**,
incluindo primeira navegação/imagens, sem representar benchmark ou SLA.

Banco real permanece na migration 010, sem escrita/migração durante navegação.
SHA-256 do dump lógico antes/depois:
`244a95098afa5e9cef8d84246b5ac922e9f5b5af0416b938978fda7d81530f3c`.
Excel original preservado:
`32aac84eedec3e8b34e48920bc4bf03c17ccc773886cd84490d2e6f64f57cfdc`.
SQLite real e fixtures: integridade `ok`, sem violações de FK.

Evidências locais em `reports/milestone-7-1/`, ignoradas pelo Git: auditorias,
fixtures, resultados do navegador e capturas. Não houve nova coleta do catálogo,
reimportação da planilha ou decisão fictícia no banco real.

## Limitações e arquivos

- A busca respeita fabricante/ano já conhecidos. Corrigir identidade incompleta ou
  ano/fabricante incorreto do anúncio exige o fluxo de origem; esta etapa não cria
  edição de anúncio nem vínculo incompatível.
- Links de tabela abrem nova aba. A aba original precisa de Atualizar dados para
  refletir uma decisão feita na outra; a nova aba oferece retorno à fila.
- Sem autenticação corporativa: autor continua declaração local auditada.
- Rejeição/ignorar não são novas categorias de presença; ficam detalhadas na auditoria.
- “Novo” descreve a última coleta, não idade cronológica. Ausência humana é por versão.
- Matching, memória, suporte, agendamento e desenvolvimento mantêm suas regras.
  Nenhum parceiro novo, IA, OCR, reconhecimento visual ou atualização de base.

Arquivos principais: `app/dashboard.py`, `ui/human_decision.py`,
`services/review_presentation.py`, `services/dashboard_service.py`,
`database/dashboard_repository.py`, `ui/textos.py`, `ui/vehicle_images.py`,
`ui/alert_panel.py`, `services/alert_service.py`, `tests/test_human_confirmation.py`,
`tests/test_ui_textos.py`, `README.md` e este relatório.

Entrega Git prevista na mesma branch, com mensagem
`feat: improve human base confirmation workflow`; SHA e confirmação remota são
informados na entrega final após commit/push.
