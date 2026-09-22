# Milestone 4.1 — Interface operacional em português

Continuação do commit `513213b` na branch `milestone-3-wr-motos-wip`, sem merge
em main. Objetivo: linguagem clara para quem opera o sistema, preservando os
contratos existentes. Baseline executada antes das alterações: **342 testes
aprovados**. Resultado final: **390 testes aprovados**, com 48 testes adicionais.

## Inventário e exemplos

A inspeção encontrou termos ingleses nos títulos, cabeçalhos, filtros, detalhes,
seletores de candidatos, mensagens de validação e histórico. Além disso, tabelas
exibiam enums crus e os expansores mostravam dicionários técnicos de auditoria,
scanner e metadados de coleta.

| Antes | Agora |
|---|---|
| Matching | Correspondência |
| Score / confidence | Pontuação de similaridade |
| Reviewer | Revisor |
| Confirmar match | Confirmar correspondência |
| pending / resolved | Pendente / Resolvido |
| ignored / deferred | Ignorado / Adiado |
| invalidated / reused | Precisa de nova revisão / Reaproveitado |
| high / medium / low | Alta / Média / Baixa |
| EXATO_NORMALIZADO | Correspondência exata |
| CORRESPONDENCIA_PROVAVEL | Correspondência provável |
| AMBIGUOUS | Ambíguo |
| NAO_ENCONTRADA_NA_BASE | Não encontrado na base |
| CONFIRMADO_AUSENTE_NA_BASE | Ausência confirmada na base atual |
| SUPORTADO / SEM_SUPORTE | Suportado / Sem suporte |
| SUPORTE_PARCIAL / EM_ANALISE | Suporte parcial / Em análise |
| SEM_STATUS | Situação não definida |
| COMPLETE / CACHED | Concluída / Dados temporários reutilizados |
| scanner_key / external_id | Chave da base / Identificador do anúncio |
| first_seen / last_seen | Primeira aparição / Última aparição |
| before_state / after_state | Situação anterior / Nova situação |
| token_sort / blockers | Similaridade sem considerar a ordem / Impedimentos |
| STALE_BASE_VERSION | A base mudou; a decisão precisa de nova revisão |

## Arquitetura e preservação

`ui/textos.py` centraliza cabeçalhos, enums, ações, ordenações, ajudas e traduções
de explicações geradas pelo sistema. `label`, `value`, `cell` e `row_labels`
produzem cópias para apresentação; não modificam o retorno dos serviços.
A tradução de textos explicativos é limitada a conteúdo gerado pelo sistema,
nunca ao anúncio original ou à justificativa escrita por um revisor.

Filtros usam `format_func`: o usuário vê “Alta”, mas o serviço continua recebendo
`high`. Ações traduzidas continuam mapeadas para os cinco comandos originais.
Identificadores e chaves de candidatos são preservados integralmente.
Nenhum service, repository, enum persistido ou migration foi alterado.

Valores desconhecidos não quebram a interface: geram log com o identificador
original e mostram “Informação ainda sem tradução”. Cabeçalhos desconhecidos usam
“Informação adicional”, sem sobrescrever outra coluna. Erros técnicos inesperados
recebem mensagem operacional genérica; o diagnóstico permanece no log.

As tabelas usam `st.table` para evitar menus técnicos da grade interativa. A
paginação, filtros e ordenação existentes permanecem nos controles próprios.
Células são formatadas como texto na fronteira visual para evitar avisos de
conversão entre números e “Não informado”. Os links de anúncios continuam abrindo
o destino original. A barra de ferramentas de desenvolvimento é ocultada no painel.

Os expansores substituem JSON técnico por informações rotuladas: identidade e
abrangência da memória, histórico auditável, motivos de invalidação e avisos/falhas
de coleta. Metadados técnicos completos permanecem disponíveis no banco e na CLI.

## Páginas e operações revisadas

As nove páginas foram revistas: Visão geral, Fila de revisão, Estoque WR Motos,
Sem suporte, Suporte parcial, Possíveis novas motos, Base do scanner, Busca global
e Histórico. Filtros traduzidos: prioridade, situação da revisão, fabricante,
ano, resultado automático, cobertura e parceiro; busca textual e ordenação
continuam disponíveis. Seletores mantêm os identificadores internos.

Botões e ações: confirmar correspondência, rejeitar candidato, confirmar ausência
na base atual, adiar, ignorar, salvar decisão, atualizar, iniciar outra revisão
e abrir anúncio. Mensagens de erro, sucesso, formulário desatualizado, vazio e
modo somente leitura estão em português. Ajuda explica correspondência e cobertura.

O aviso de identidade continua explícito: “Confirmar a identidade da moto não
altera automaticamente a situação de suporte.” O aviso de 0 km explica que os dois
filtros retornaram os mesmos anúncios, sem pressupor que a classificação seja válida.

## Validação

- 342 testes existentes preservados; somente dois nomes de páginas tiveram a
  capitalização ajustada nas expectativas do teste de interface existente.
- 48 testes novos: traduções, cabeçalhos, fallback com log, explicações, preservação
  de dados originais, ausência dos principais enums crus nas nove páginas,
  filtros com valores internos, cinco ações auditadas e validação de erro.
- AppTest executou as nove páginas, incluindo detalhe, busca, filtro de prioridade
  e todas as ações. Cada ação salvou o comando original em banco temporário,
  preservou o resultado automático e não duplicou a decisão após reexecução.
- Suíte final: **390 aprovados**. Ruff check, formatação, compilação, imports e
  `git diff --check` aprovados.
- Streamlit iniciado localmente na porta 8503, com base real somente leitura.
  Playwright/Edge abriu as nove páginas, aguardou o fim de cada renderização e
  confirmou títulos, tabelas, ausência dos principais termos crus e ausência
  de erros de página. O comando agent-browser estava indisponível.
- Capturas da home e da fila inspecionadas visualmente. Evidências locais em
  `reports/milestone-4-1/`; não adicionadas ao Git.
- Varredura dos arquivos de interface revisada: ocorrências restantes como
  `matching`, `reviewer` e `status` são chaves internas ou entradas da tradução,
  não rótulos exibidos diretamente.

A base real manteve 158 anúncios, 142 pendências, 57 prioridades altas e 85 médias.
Hashes de todas as tabelas permaneceram iguais antes/depois; zero decisões humanas
criadas, integridade SQLite aprovada e nenhuma falha de chave estrangeira.
O SHA-256 do Excel segue
`32aac84eedec3e8b34e48920bc4bf03c17ccc773886cd84490d2e6f64f57cfdc`.

## Arquivos

Criados: `ui/__init__.py`, `ui/textos.py`, `tests/test_ui_textos.py` e este relatório.
Alterados: `app/dashboard.py`, `tests/test_dashboard.py` e `README.md`.

## Limites e execução

Nomes próprios, marcas, modelos, chaves, URLs, nomes de sistemas, textos originais
e notas de usuários não são traduzidos automaticamente, para preservar a evidência.
Controles próprios do navegador ou textos auxiliares fornecidos pelo Streamlit
podem depender da versão e do idioma do navegador; a interface operacional usa
rótulos em português. Um código novo desconhecido exige adicionar tradução ao mapa.
A submissão foi exercitada com AppTest; a navegação visual usou a base real sem escrita.

A execução permanece `python -m streamlit run app/dashboard.py`. Para consulta
somente leitura, defina `MOTO_READ_ONLY=1`; banco e parceiro continuam configurados
por `MOTO_DB` e `MOTO_PARTNER`. Não houve coleta nova, deploy ou agendamento.
