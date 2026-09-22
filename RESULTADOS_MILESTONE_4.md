# Milestone 4 — Dashboard operacional

Data: 22/09/2026. Repositório `RenatoBoranga1/Chip_aut`, branch
`milestone-3-wr-motos-wip`. Continuação do commit `30579f1`, sem reconstruir os
Milestones 1, 2, 3, 3.1 ou 3.2. Nenhum merge em main.

## Entrega

Streamlit 1.64.0 fixado nas dependências. `app/dashboard.py` contém apresentação;
`services/dashboard_service.py` prepara consultas, filtros e comandos;
`database/dashboard_repository.py` concentra SQL e usa leitura transacional.
As ações chamam `ReviewRepository.decide`, também usado pela CLI. Matching,
prioridade, memória e diagnóstico reutilizam os componentes existentes.
Não há SQL ou implementação de matching no frontend.

| Página | Operação disponível |
|---|---|
| Visão geral | Estoque, fila, prioridades, matching, cobertura e última coleta |
| Fila de Revisão | Filtros, detalhe, candidatos, evidências e cinco ações auditadas |
| Estoque WR Motos | Anúncios atuais e resultados automático/efetivo |
| Sem suporte | Identidades válidas com SEM_SUPORTE |
| Suporte parcial | Identidades válidas com SUPORTE_PARCIAL e sistemas |
| Possíveis novas motos | Ausência confirmada, provável ausência e revisão separadas |
| Base do Scanner | Snapshot atual, sistemas e status, somente leitura |
| Busca global | Anúncios, fila e scanner com normalização textual |
| Histórico | Coletas, diferenças de IDs, ocorrências e decisões auditadas |

Filtros por prioridade, estado, fabricante, ano, matching, cobertura, parceiro e
texto, conforme a listagem. Ordenação por prioridade, recência, antiguidade ou
modelo. Tabelas exibem 50 linhas por página; histórico consulta lotes de 30.
As consultas de listagem retiram HTML bruto e texto integral antes de transferi-los
para Python; apenas o detalhe selecionado carrega o texto do anúncio. O scanner
usa o snapshot atual, sem carregar versões históricas completas na interface.
As listas atuais são carregadas em memória para filtros e contadores; não há cache
persistente nem promessa de escalabilidade para milhões de anúncios.

## Decisões e integridade

Confirmar match, rejeitar candidato, confirmar ausência na base atual, ignorar e
manter pendente exigem reviewer e justificativa. Confirmar/rejeitar também exige
candidato explícito válido na base atual. Regras preexistentes de marca, ano,
identidade e escopo de memória continuam aplicadas.

A migração aditiva 007 registra recibos idempotentes e transições anterior/posterior.
As migrações 001–006 não foram alteradas. Decisão, recibo, transição e atualização
da fila são atômicos. Repetir um identificador com os mesmos dados retorna o recibo;
reutilizá-lo com dados diferentes é rejeitado. Duas requisições simultâneas com o
mesmo identificador criam uma única decisão.

O formulário guarda versão derivada do item, execução, base, decisão aplicável e
última coleta observada. Uma mudança concorrente bloqueia submissões antigas.
Mudança de identidade recém-coletada invalida a projeção da memória anterior e
bloqueia decisão até gerar a nova cobertura, mesmo antes de sincronizar a fila.
Após sucesso, o recibo substitui o formulário até uma nova revisão explícita.

Resultado automático, decisão humana e resultado efetivo são apresentados
separadamente. O suporte vem da base atual e de seus sistemas; confirmar identidade
não promove suporte. Memórias negativas obsoletas não são usadas como conclusões
atuais. Relatórios históricos e observações originais permanecem preservados.
Navegação abre SQLite com `mode=ro` e `query_only`, sem executar migrações ou refresh
persistido. `MOTO_READ_ONLY=1` também impede os comandos de decisão no serviço.

## Validação automatizada

Baseline antes das alterações: **295 testes aprovados**.
Entrega: **342 testes aprovados**, incluindo 47 novos casos do dashboard.
Ruff check, Ruff format check, compileall e importação dos módulos executados.

A cobertura adicional inclui consultas sem mutação, ausência de HTML nas listas,
filtros e busca, cinco ações, estados de auditoria, separação identidade/suporte,
memória obsoleta, idempotência, submissões paralelas, formulários antigos, nova
identidade coletada sem cobertura, rollback de dados inválidos, isolamento de
parceiro, modo somente leitura, paginação e ausência de SQL no frontend.

AppTest verifica as nove páginas, submissão de confirmação em banco temporário,
atualização efetiva e da visão geral, rerun sem duplicar e erro visível sem falso
sucesso. Todos os testes de decisões usam fixtures, nunca decisões fictícias na
base real.

## Smoke local e limites

Servidores locais iniciados com Streamlit: fixture na porta 8501 e base real em
modo somente leitura na porta 8502. Playwright com Edge headless foi usado porque
o comando agent-browser não estava instalado. As nove páginas reais abriram sem
erros de página do navegador. Capturas e evidência JSON ficaram nos relatórios
locais ignorados pelo Git (`reports/milestone-4/smoke`).

A confirmação e sua atualização foram verificadas por AppTest. A tentativa de
completar esse mesmo fluxo por cliques no navegador ficou limitada pela automação
do seletor de candidato; não houve confirmação salva por esse smoke de navegador.
Portanto, não se declara validação integral da submissão por cliques reais.

## Base real consultada sem escrita

| Medida | Resultado |
|---|---:|
| Anúncios atuais | 158 |
| Itens na fila / pendentes | 142 / 142 |
| Prioridade alta / média / baixa | 57 / 85 / 0 |
| Motocicletas no snapshot scanner | 1.337 |
| Matching EXATO_NORMALIZADO | 54 |
| Matching REVISAR | 43 |
| Matching AMBIGUOUS | 8 |
| Matching NAO_ENCONTRADA_NA_BASE | 53 |
| Cobertura SUPORTADO | 16 |
| Cobertura SEM_SUPORTE | 3 |
| Cobertura SUPORTE_PARCIAL | 1 |
| Cobertura SEM_STATUS | 34 |
| Cobertura EM_ANALISE | 0 |
| Identidade pendente (REVISAR + AMBIGUOUS) | 51 |
| Não encontrada na base | 53 |
| Ausências confirmadas humanamente | 0 |
| Hipóteses de provável ausência | 14 |
| Casos ainda em revisão na página de oportunidades | 43 |

Última coleta persistida: 3, 14 páginas, 316 ocorrências brutas, 158 duplicadas e
158 IDs líquidos, sem erros registrados e 158 avisos FILTROS_ZERO_KM_CONFLITANTES. Comparada à coleta 2: nenhum ID novo,
158 reencontrados e nenhum desaparecido. O conflito observado entre os filtros
0 KM permanece sinalizado; os resultados não comprovam um conjunto independente
de motos zero quilômetro. Nenhuma nova coleta foi necessária nesta entrega.

Hashes do conteúdo de **todas as tabelas** antes/depois da navegação e consultas
foram iguais. `integrity_check=ok`, `foreign_key_check` sem erros, zero decisões
humanas. O banco real continuou na versão 006: a leitura não o migrou para 007.
A migração e decisões foram exercitadas em bancos temporários dos testes.

SHA-256 do Excel preservado:
`32aac84eedec3e8b34e48920bc4bf03c17ccc773886cd84490d2e6f64f57cfdc`.
Evidências locais: `reports/milestone-4/before-read-only.json` e
`reports/milestone-4/real-validation.json`. Banco, relatórios de operação e dados
brutos não foram adicionados ao commit do dashboard.

## Execução e escopo

Consulte o README para instalação, `python -m streamlit run app/dashboard.py` e
variáveis `MOTO_DB`, `MOTO_PARTNER`, `MOTO_READ_ONLY`. Não há caminho de usuário
fixo no aplicativo. O servidor fica em 127.0.0.1 por padrão, sem autenticação.
Agendamento, envio de mensagens, deploy e alterações no scanner original não
fazem parte desta entrega. O dashboard consulta o estado persistido; a atualização
do catálogo e dos relatórios continua pelos comandos existentes.
