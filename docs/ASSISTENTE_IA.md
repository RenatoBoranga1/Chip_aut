# Assistente de IA operacional — Milestone 14

O assistente consulta os dados existentes, organiza evidências e oferece atalhos para as telas. Banco operacional, base publicada, decisões humanas e PartnerRegistry continuam sendo as fontes de verdade. Não há agente autônomo ou ferramentas de escrita.

## Arquitetura

Pergunta → guardrails → intenção determinística → consulta controlada → contexto limitado → provider → validação das referências → apresentação dos fatos e fontes.

- `services/ai_assistant_service.py`: coordenação, limites, tempos e auditoria.
- `services/ai_context_service.py`: 13 intenções, calendário e estado explícito da conversa.
- `services/ai_query_service.py`: conjunto finito de consultas, reutilizando serviços existentes.
- `database/ai_repository.py`: leituras do scanner e versões, sem herdar métodos de escrita.
- `services/ai_guardrails.py`: recusa de ações, redação de segredos/caminhos e validação das respostas.
- `services/ai_provider.py`: interface LLMProvider, FakeLLMProvider e implementação OpenAI.
- `ui/ai_assistant_panel.py`: chat Streamlit, sugestões, fontes, seleção de veículo e nova conversa.

O RAG é uma recuperação determinística de dados estruturados. Não há embeddings, índice vetorial ou envio do banco completo. Repositories existentes podem consultar agregados e conjuntos locais necessários às regras de negócio; apenas os fatos relevantes e limitados chegam ao provider.

## Limite deliberado de geração

O provider organiza os IDs de evidência por relevância. Não produz texto factual livre: a apresentação usa frases construídas com os valores recuperados. Todos os IDs devem aparecer exatamente uma vez; referências inventadas, omitidas, duplicadas ou uma resposta fora do contrato são rejeitadas.

Esse contrato reduz flexibilidade de linguagem, mas impede que uma resposta invente números, decisões ou suporte. Não é um chatbot de conhecimento geral. Campos de origem podem conter texto malicioso; permanecem dados, exibidos como texto simples, sem HTML, Markdown ativo ou execução.

## Somente leitura

AIRepository usa SQLite `mode=ro`, `PRAGMA query_only=ON` e authorizer que nega escrita, DDL, ATTACH e funções de arquivo/extensão. Não disponibiliza execute, SQL arbitrário ou métodos de persistência. Filtros e IDs são parâmetros de consultas fixas.

Consultas de revisão reutilizam a projeção somente leitura do DashboardRepository, incluindo validade da decisão na base atual. Prioridade vem de PrioritizationService.listing/detail, sem refresh ou simulação. Indicadores vêm de ManagementMetricsService, sem fórmulas novas. Desenvolvimento usa leituras paginadas com filtro de origem/parceiro; alertas usam read_alerts.

O provider só recebe JSON de dados e devolve referências. Não recebe objetos de serviço, callbacks, credenciais de banco, ferramentas, shell, Git, arquivos arbitrários, scheduler, collector ou navegador. Pedidos de alterar decisão/prioridade, publicar base, coletar ou excluir recebem:

> O Assistente de IA está em modo somente leitura. Essa ação exige uso da função operacional correspondente e confirmação humana.

Atalhos são cliques explícitos do usuário para abrir telas existentes. Não preenchem nem confirmam ações.

## Configuração

`config/ai_assistant.json` vem com `enabled=false`, `read_only=true`, até 50 fatos de contexto, 10 mensagens de histórico, 20 registros de resposta, timeout de 30 segundos, um retry e auditoria ligada. Os limites têm tetos validados. Fatos serializados têm orçamento adicional de 24 KB.

Sem configuração válida, a página mostra **Assistente de IA não configurado.** As outras páginas continuam operando.

Variáveis em `.env.example`:

| Variável | Uso |
|---|---|
| AI_ASSISTANT_ENABLED | true para habilitar explicitamente; false por padrão |
| AI_PROVIDER | fake para teste offline; openai para API |
| AI_MODEL | Modelo da conta que suporte Responses e Structured Outputs |
| AI_API_KEY | Segredo somente no ambiente |

O projeto não carrega `.env` automaticamente; exporte as variáveis no processo que inicia Streamlit. Nunca coloque a chave no JSON, no código ou no Git.

Exemplo offline em PowerShell:

```powershell
$env:AI_ASSISTANT_ENABLED='true'
$env:AI_PROVIDER='fake'
python -m streamlit run app/dashboard.py
```

Para API, configure provider/modelo/chave no ambiente antes de iniciar. Nenhum modelo é escolhido ou contratado automaticamente. O FakeLLMProvider é identificado na interface e não faz chamadas externas.

## Provider e falhas

LLMProvider define generate, healthcheck e get_model_info. Novos fornecedores podem implementar o mesmo contrato de referências sem receber ferramentas operacionais.

OpenAI usa Responses em HTTPS com saída JSON estruturada e `store=false`, conforme a [documentação oficial de Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses). Não usa ferramentas ou pesquisa web. O healthcheck atual verifica configuração local; não garante disponibilidade remota nem consome tokens.

Timeout configurável por acesso, corpo de resposta limitado a 100 KB, redirects desativados. Até um retry para timeout/conexão/429/500/502/503/504, com pausa de 0,5 s. Falhas 401/403, recusas, saída incompleta e contrato inválido não têm retry. A UI mostra **O serviço de IA está temporariamente indisponível.** Erros brutos e cabeçalhos não são expostos. Não foi realizada chamada paga de validação.

## Consultas e exemplos

| Intenção | Pergunta | Origem |
|---|---|---|
| SCANNER_LOOKUP | Mostre BMW F 850 GS 2023 | Veículos da base publicada |
| APPLICATION_LOOKUP | Quais sistemas ela tem? | Aplicações do veículo selecionado |
| CABLE_LOOKUP | Qual cabo é utilizado? | Sistema, cabo, local e atributos por aplicação |
| REVIEW_LOOKUP | Por que revisão #123 caiu em revisão? | Automático, candidatos, score, decisão e validade |
| PARTNER_LOOKUP | Por que Thomas Motos não está integrada? | Registry e avaliação salva |
| DEVELOPMENT_LOOKUP | Quais aguardam informações? | Etapa, dias, prioridade e parceiros |
| PRIORITIZATION_LOOKUP | Por que prioridade #12? | Pontuação, sugerida, efetiva, override e motivos persistidos |
| MANAGEMENT_METRICS | Resuma os últimos 30 dias | Serviço gerencial existente |
| ALERT_LOOKUP | Quais são os principais alertas? | Alertas não resolvidos/arquivados do parceiro |
| BASE_VERSION_LOOKUP | Quais versões da base? | Histórico de versões |
| RECENT_CHANGES | Quais motos novas apareceram esta semana? | Primeira observação do anúncio |
| GENERAL_HELP | Como usar? | Política de consulta |
| UNKNOWN | Pergunta fora do escopo | Sem consulta externa ou conhecimento geral |

Para selecionar diretamente: `Mostre veículo #ID`. A busca aceita fabricante, modelo e ano; múltiplas correspondências geram opções. O sistema não escolhe silenciosamente uma versão. Após seleção, “ela” usa selected_vehicle_id. Alterar banco, parceiro ou base invalida a seleção.

“Quantos veículos existem?” retorna contagens distintas de veículos, aplicações e sistemas. A validação da V16 encontrou 3.361 veículos, 8.744 aplicações e 616 sistemas. Esses números são consultados, não constantes no código.

Cada aplicação mantém seu sistema e cabo. Um cabo vazio, vídeo, FIPE, imobilizador ou função sem valor significa **Não há informação registrada para esse campo.** Não é prova de ausência. Suporte indefinido continua indefinido.

## Períodos e semântica

Hoje, ontem, esta semana (segunda-feira até hoje), últimos 7/30 dias (incluindo hoje), este mês, mês passado e este ano são convertidos para datas explícitas no fuso America/Sao_Paulo. Sem período, consultas temporais usam últimos 30 dias.

Comparações usam o período anterior equivalente calculado pelo ManagementMetricsService, exibido na resposta; não se inventa comparação com um mês cheio quando o serviço usa duração equivalente. Listas de estado atual (revisão, prioridade, alertas) não são séries históricas.

Novos anúncios usam primeira observação no período, inclusive anúncios que depois saíram do estoque. Não equivalem a novas identidades para o scanner. Reaparecimentos usam a semântica existente da última coleta; a resposta declara esse limite, sem alegar reconstrução semanal. Estoque mais antigo é ordenado pela primeira observação. Desenvolvimento parado há mais de 30 dias usa tempo na etapa.

## Evidências, limites e navegação

Respostas factuais têm fontes com tipo, referência e base quando aplicável. A UI mostra Fontes consultadas, recorte temporal e “Mostrando N de T”. Resultados maiores abrem a tela de origem; o assistente não exporta tabelas completas ao provider. Os atributos e candidatos exibidos são limitados.

O menu tem 12 itens: Assistente de IA ocupa a terceira posição e Possíveis novas motos a quarta. A ordem relativa das páginas anteriores permanece. As cinco páginas ocultas continuam ocultas; atalhos internos podem abri-las pela política existente.

O histórico fica apenas na sessão Streamlit, limitado a 10 mensagens (usuário e assistente). Nova conversa limpa mensagens, seleção e opções; não há arquivo de conversas. Não há memória semântica persistente ou interpretação universal de linguagem natural. Perguntas fora das regras pedem mais informação.

## Auditoria e privacidade

Auditoria local em `logs/ai_assistant.jsonl`, ignorada no Git, com rotação de 1 MB e dois backups. Registra timestamp, pergunta com redação, intenção, tipos de fontes, provider/modelo, duração e sucesso. Não registra resposta completa, contexto recuperado ou chave. Padrões de credenciais e caminhos e o valor de AI_API_KEY são removidos; isso não substitui uma solução geral de DLP. Não informe segredos em perguntas.

A auditoria grava somente metadados fora do banco operacional. Não é uma ferramenta do modelo e não aceita destino de arquivo vindo da conversa. Pode ser desativada na configuração administrativa. Falha de auditoria gera aviso sem interromper as consultas.

Somente fatos delimitados, pergunta e histórico curto de perguntas são enviados ao provider configurado. HTML raw, notas técnicas completas, planilhas, banco, logs, caminhos e credenciais não são enviados. Com provider fake, tudo fica local.

## Validação

Testes usam fixtures isoladas e FakeLLMProvider; o transporte OpenAI é simulado. Há cobertura de prompt injection, escrita, SQL/shell, ausência de provider, timeout/retry, saída inválida, fontes, contagens, sistemas/cabos, ambiguidade, decisões, prioridade persistida, indicadores, períodos, limites, troca de base, chat e nova conversa.

Consulte [Resultados do Milestone 14](../RESULTADOS_MILESTONE_14.md) para medições, validação real, status do navegador e entrega Git.
