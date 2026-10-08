# Milestone 14 — Assistente de IA operacional

## Referência e escopo

- Repositório: RenatoBoranga1/Chip_aut.
- Branch: `milestone-3-wr-motos-wip`.
- SHA inicial: `1f4329bd5ba0ca4ff8cc7e81d14f2da6f84c700f`.
- Baseline executada: **1.003 testes aprovados**, 450,85 s.
- Nenhum milestone anterior foi refeito. Nenhum parceiro foi habilitado. Não houve merge em main.
- Configuração distribuída desabilitada; ativação explícita por ambiente. Nenhuma API paga foi chamada.

## Arquitetura e dados

`ai_assistant_panel` → `AIAssistantService` → intenção determinística → `AIQueryService` → repositories/serviços existentes → fatos limitados → `LLMProvider` → validação de IDs → resposta com fontes.

O repositório próprio abre SQLite por URI `mode=ro`, ativa `query_only` e restringe operações com authorizer. As consultas operacionais reutilizam serviços existentes em modo somente leitura. O provider recebe apenas contexto serializado; não recebe repository, SQL, ferramenta, shell, navegador, scheduler ou collector.

A recuperação de evidências é determinística, sem embeddings nem cópia integral da base. O LLM só pode ordenar IDs dos fatos recuperados, preservando exatamente o conjunto recebido. Não pode gerar números, fatos, links ou comandos livres. Essa restrição reduz flexibilidade linguística, mas mantém a fonte de verdade nos dados do sistema.

Há 13 intenções: scanner, aplicações, cabos, revisão, parceiros, desenvolvimento, priorização, indicadores, alertas, versões, mudanças recentes, ajuda e desconhecida. Listas mostram o limite e o total quando disponível. Navegação para páginas existentes requer clique explícito.

- Scanner: separa veículos, aplicações e sistemas; mostra atributos por aplicação e ausência de informação sem convertê-la em negativa.
- Revisão: resultado automático, decisão humana registrada, data, motivo, vínculo e validade; não cria decisões.
- Parceiros: consulta o cadastro/diagnóstico existente; apenas WR Motos permanece habilitada.
- Desenvolvimento: consulta estágio, idade, parceiros e prioridade; não cria nem conclui itens.
- Priorização: usa pontuação persistida, motivos e overrides; não recalcula nem grava.
- Indicadores: reutiliza `ManagementMetricsService`, períodos explícitos em America/Sao_Paulo e comparação com período anterior.
- Alertas, versões e anúncios: consultas limitadas, com IDs e fontes. Reaparecimento segue a semântica da coleta existente.

## Provider, contexto e segurança

Interface com `generate`, `healthcheck` e `get_model_info`; `FakeLLMProvider` para execução offline e adapter OpenAI Responses com saída estruturada. O healthcheck é local e não confirma disponibilidade remota. Modelo e chave vêm do ambiente; nenhum modelo pago é escolhido automaticamente.

Limites: 50 fatos de contexto, 10 mensagens, 20 linhas iniciais, fatos serializados limitados a 24 KB, pergunta de 2.000 caracteres, resposta HTTP de 100 KB e no máximo uma repetição para falhas transitórias. Timeout configurável; erros não expõem detalhes internos.

Pedidos de escrita, SQL e shell são bloqueados. A proteção principal é arquitetural: provider sem ferramentas e saída restrita a IDs verificados. Conteúdo recuperado é dado, não instrução. Texto da UI não interpreta HTML/Markdown vindo das fontes. Caminhos e padrões de credenciais são expurgados antes de provider/auditoria.

A auditoria registra pergunta redigida, intenção, tipos de fonte, provider/modelo, duração, status e timestamp em arquivo rotativo ignorado pelo Git, fora do banco operacional; não registra a resposta completa. Redação por padrões não substitui revisão de dados sensíveis antes de habilitar um serviço externo.

Ambiguidades exigem escolha explícita; follow-up conserva veículo e versão. Mudança de base ou escopo invalida a seleção. Nova conversa limpa o contexto.

## Validação automatizada

A primeira execução completa da implementação passou com **1.075 testes** em 435,49 s. A validação no navegador encontrou um caso adicional: “E quais cabos ela usa?” tratava “usa” como termo de modelo. A correção acrescentou duas regressões para “usa” e “utiliza”; **execução final: 1.077 testes aprovados em 502,14 s (8:22)**, incluindo os 1.003 anteriores e 74 novos casos. Ruff check, Ruff format (176 arquivos), compileall e git diff --check passaram.

Os testes cobrem fixtures conhecidas, contagens, aplicações/cabos, atributos vazios, ambiguidade, decisões humanas, parceiros, desenvolvimento, prioridades, métricas, alertas, períodos, versão, histórico limitado, provider ausente, falha/timeout, retries, saída inválida, injeção, SQL/shell, imutabilidade do banco e painel Streamlit. Os 1.003 testes anteriores foram preservados.

## Validação real controlada e performance

Consultas somente leitura confirmadas contra SQL direto na base ativa 3:

| Evidência | Resultado |
| --- | --- |
| Veículos | 3.361 |
| Aplicações | 8.744 |
| Sistemas distintos | 616 |
| BMW F 850 GS 2023 | Três correspondências: IDs 35, 42 e 45 |
| BMW F 850 GS Premium 2023, ID 42 | Dez aplicações; sistemas e cabos conferidos |
| Revisões pendentes | 202; primeiras 20 exibidas |
| Cadastro de parceiros | Quatro registros, somente WR ativa |
| Integridade SQLite | `ok` |
| Hash do banco antes/depois das consultas | Inalterado |

Tempo total observado com provider falso: contagens 0,033–0,034 s; busca ambígua 0,066 s; veículo 0,030 s; sistemas 0,034 s; cabos 0,039 s; revisão 0,169 s; parceiros 0,038 s; resumo 30 dias 0,665 s. Intenção, consulta, contexto, provider e total são medidos separadamente. Esses valores não estimam a latência de um LLM remoto.

Evidências locais ignoradas pelo Git: `reports/milestone-14/real-readonly.json`, cópia SQLite de validação e logs em `../../work/`. Nenhum banco, planilha, conversa real, log ou screenshot é incluído no commit.

## Navegador

Servidor de validação iniciado pelo usuário em `127.0.0.1:8536`, usando cópia da base, modo somente leitura e provider falso. A execução inicial em ambiente isolado não era acessível pelo navegador.

Verificados: menu com Assistente de IA em terceiro e Possíveis novas motos em quarto; cinco páginas continuam ocultas; abertura do painel; pergunta de contagens; resposta correta; fontes; ambiguidade de BMW com três opções e seleção explícita do ID 42. Após a correção do follow-up, o navegador integrado deixou de responder aos comandos de recarga, leitura e abertura de nova aba (timeouts CDP). A consulta corrigida foi repetida diretamente na cópia real: manteve veículo 42, retornou dez aplicações e levou 0,044 s. Isso não substitui a repetição visual. Permanecem pendentes no navegador: follow-up corrigido, clique em sugestão, nova conversa, provider ausente, loading, erro e tela pequena. Esses comportamentos têm cobertura automatizada onde indicada, mas o milestone ainda não está aprovado integralmente pelo critério visual. O usuário foi avisado e solicitado a reabrir a página.

### Retomada visual em 6 de outubro

O usuário reiniciou o dashboard na porta 8537, com file watcher desabilitado, cópia de validação e FakeLLMProvider. Foram então verificados no navegador:

- Follow-up corrigido: “Mostre veículo #42” seguido de “E quais cabos ela usa?” manteve a BMW F 850 GS Premium 2023 e exibiu dez de dez aplicações, incluindo sistemas e cabo MX-AT1601.
- Nova conversa: acionamento por teclado limpou mensagens e seleção, reexibindo as sugestões.
- Sugestão “Resumo de hoje”: acionamento gerou resposta com 17 registros e período explícito 2026-10-06 a 2026-10-06, America/Sao_Paulo.
- Carregamento: exibiu “Consultando dados e organizando evidências...” antes da resposta.
- Tela pequena: viewport 390 × 844 com texto legível, navegação recolhida e entrada de conversa disponível.

Esses resultados substituem as pendências correspondentes do registro anterior. **Restam somente provider ausente e serviço indisponível no navegador.** O diagnóstico local `../../work/m14_browser_scenarios.py`, fora do repositório, reutiliza o painel real com provider ausente, timeout simulado e recuperação offline; não acessa API externa nem grava dados operacionais. Na retomada de 8 de outubro, a porta 8538 inicialmente recusou conexão. A aprovação visual integral permanece pendente até executar os dois cenários.

## Limitações e documentação

Não é chat de conhecimento geral nem busca semântica irrestrita: intenções e termos são determinísticos. Perguntas desconhecidas não são respondidas com conhecimento externo. Dados ausentes continuam ausentes. Não há pesquisa web, previsão, ação autônoma nem escrita operacional. O adapter remoto foi testado com HTTP simulado; disponibilidade e qualidade de um modelo real não foram avaliadas.

Arquivos principais: `services/ai_assistant_service.py`, `services/ai_context_service.py`, `services/ai_query_service.py`, `services/ai_guardrails.py`, `services/ai_provider.py`, `database/ai_repository.py`, `ui/ai_assistant_panel.py`, `config/ai_assistant.json` e `tests/test_ai_assistant.py`.

Guia de operação, configuração, exemplos e limitações: [ASSISTENTE_IA.md](docs/ASSISTENTE_IA.md). README e guia de navegação atualizados.
