# Milestone 9 — Priorização operacional inteligente

## Baseline e escopo

Branch: `milestone-3-wr-motos-wip`. SHA inicial: `9729f1fb36304e543fab6c47bbec6eadf91242ea`.
Inspeção e sincronização realizadas antes das alterações. Baseline: **741 testes aprovados
em 208,10 s**. Entrega limitada ao Milestone 9 e à WR Motos; sem merge em main.

## Arquitetura

Motor puro `services/prioritization_engine.py`, política validada em
`services/prioritization_policy.py` e `config/prioritization.json`, orquestração em
`services/prioritization_service.py`, persistência em `database/prioritization_repository.py`,
alertas próprios em `database/prioritization_alert_repository.py`, interface sem SQL em
`ui/prioritization_panel.py` e CLI `app/prioritization.py`.

Migration aditiva `013_prioritization.sql`: casos, avaliações, intervenções, manutenção,
alertas e histórico de alertas. Triggers protegem os registros históricos contra alteração
ou exclusão. Migrations anteriores preservadas. Sugestão e prioridade efetiva são separadas.

## Indicadores, pesos e faixas

| Critério | Peso inicial | Interpretação |
|---|---:|---|
| Situação na base | 30 | Ausência confirmada e sem suporte são condições distintas; não encontrado, ambiguidade, suporte parcial e desconhecido têm fatores próprios |
| Permanência observada | 20 | Exige pelo menos duas observações em dias distintos; satura em 30 dias |
| Tempo pendente | 20 | Idade operacional ou de revisão, saturada em 30 dias |
| Encaminhamento | 15 | Sem item conhecido recebe fator integral; aguardando informação recebe metade; demais estados não acrescentam |
| Evidência adicional | 10 | Maior sinal aplicável, sem multiplicação por quantidade de alertas |
| Qualidade e atualidade | 5 | Identidade completa, dados recentes e sem avisos relevantes de identidade |

Pesos normalizados pela soma. Alta: >=75; média: >=45 e <75; baixa: <45.
Sem comparação vigente ou identidade mínima, pontuação nula e dados insuficientes.
Não se usam imagens, ano mais novo, demanda presumida ou volume de alertas como importância.

## Evidências e confiabilidade

Cada contribuição contém pontos e motivo derivados da mesma regra de cálculo. Evidências
incluem datas, observações, versão da base, coleta, decisão vigente e desenvolvimento.
Evidência suficiente exige identidade/comparação disponíveis, atualidade e ausência de
pendências de confirmação. Evidência parcial explicita dúvida, desatualização ou avisos.
Dados insuficientes impedem pontuação oficial. Não são probabilidades estatísticas.

## Revisão humana

Reutiliza a decisão oficial revalidada do Milestone 7.1. Presença usa o candidato confirmado;
ausência depende da decisão vigente e versão da base; dúvida permanece pendente, inclusive
quando existe matching exato automático. Nenhuma decisão humana é criada pela priorização.

## Desenvolvimento

Avaliação visível no detalhe do item, com navegação de retorno. Etapa, responsável e prioridade
manual do desenvolvimento permanecem independentes. Não há criação automática de tarefas.
Estados ativo, aguardando informação, validação, concluído e descartado são considerados.

## Alertas

Avisos próprios de prioridade alta, alta pendente e alta desatualizada, integrados à central
com histórico e ações. IDs possuem namespace próprio, sem coleta fictícia. Deduplicação por
fato/avaliação. Casos com desenvolvimento relacionado não geram alertas redundantes.

## Histórico e intervenção

Avaliações materialmente alteradas guardam política completa e hash, evidências, critérios,
pontuação, data e origem. Repetição idêntica não insere nova avaliação. Alteração manual exige
autor/justificativa, valida revisão concorrente e registra antes/depois. Recálculo preserva
a escolha; restauração da sugestão também gera auditoria imutável.

## Dashboard e simulador

Página em português com oito métricas, filtros solicitados, seis ordenações estáveis,
oito casos por página, imagens existentes, motivos, evidências e histórico paginado.
PartnerRegistry limita o parceiro configurado. Links para revisão, anúncio e desenvolvimento.
Simulador compara configurações sobre os mesmos dados, sem alterar banco, alertas ou prioridades.

## Testes

Suíte completa: **807 aprovados em 213,05 s**, incluindo os 741 existentes e 66 novos casos.
Cobertura: determinismo, limites, políticas inválidas, dados ausentes, decisões humanas,
recorrência, deduplicação, prioridade manual, concorrência, transações, histórico, simulação,
pipeline, importação, desenvolvimento, scheduler, isolamento de parceiro, paginação, CLI,
Streamlit e integridade SQLite. Expectativas de versão dos testes antigos passaram de 12 a 13.

## Validação operacional e performance

Backup consistente do banco WR usado em `reports/milestone-9/wr-validation.sqlite3` (ignorado
pelo Git). Original na versão 11; cópia migrada até 13. Tabelas operacionais anteriores foram
comparadas por conteúdo e preservadas. Integridade SQLite ok e nenhuma violação de FK.

- 171 anúncios avaliados: **0 alta, 4 média, 167 baixa, 0 sem evidência mínima**.
- 114 aguardando decisão humana; 0 prioridades manuais; 0 itens de desenvolvimento relacionados.
- Primeira avaliação: 171 avaliações novas, **0,1431 s**.
- Repetição: 171 examinadas, **0 avaliações novas**, **0,1847 s**.
- Nenhuma inconsistência estrutural nova encontrada. Conflito conhecido de 0 KM não influencia identidade/pontuação.

Esses resultados representam atenção operacional segundo a política inicial, não uma conclusão
sobre necessidade de desenvolvimento. Nenhuma decisão fictícia foi aplicada aos dados WR.

SHA-256 do dump original antes/depois:
`3ce061697c03113686625f496b37144ca2103caa4cbb8da854a764e133bff250`.
SHA-256 de ambas as cópias de RESUMO_MDL.xlsx:
`32aac84eedec3e8b34e48920bc4bf03c17ccc773886cd84490d2e6f64f57cfdc`.

## Limitações e ativação

Pesos são hipóteses configuráveis, não modelo calibrado de demanda. A primeira avaliação requer
Reavaliar casos ou CLI explícito; o banco operacional original não foi migrado nesta validação.
Depois da ativação, hooks verificam mudanças relevantes e o scheduler verifica política/tempo.
Comandos legados são percebidos no próximo ciclo ou reavaliação manual. Atualização temporal
requer scheduler ativo. Não há recálculo durante renderização. Alertas de desatualização são
emitidos na manutenção de casos altos, não por leitura da página.

Carregamento em lote das evidências complementares; consultas atuais reutilizam a validação
de decisões já existente. Histórico e miniaturas não são carregados integralmente. A validação
de desempenho cobre 171 anúncios locais, não constitui benchmark para volumes ilimitados.
Sem IA generativa, novos parceiros, alteração do scanner ou notificações externas.


## Verificação complementar de interface — 29/09/2026

Fluxo executado no Edge com Playwright, em fixture isolada: validação de campos obrigatórios,
alteração para prioridade baixa, recálculo preservando a escolha humana, restauração automática,
simulação com comparação integral do dump SQLite antes/depois e navegação para a segunda página.
Nenhum erro JavaScript de página. Capturas do detalhe e da tabela foram inspecionadas visualmente;
são evidências locais ignoradas pelo Git. O formulário usa identificador distinto do estado de
controle de concorrência. O teste Streamlit também abre o detalhe e verifica o bloqueio de gravação
em modo somente leitura. Banco original, ambas as planilhas e migrations antigas reconferidos.

A cópia dos 171 anúncios WR também foi aberta no navegador em modo somente leitura;
a página e o detalhe carregaram, com reavaliação e gravação manual bloqueadas.
Ruff, formatação, compileall, imports principais e git diff --check aprovados.

Reexecução final com o detalhe coberto: **807 testes aprovados em 430,06 s**.
