# Milestone 10.1 — conclusão da base consolidada V16

Conferência de 02/10/2026. Repositório RenatoBoranga1/Chip_aut; branch milestone-3-wr-motos-wip. SHA inicial: `42a2d9d86a6353bf0b1a6045eb1904db8e341e7b`. Baseline completa: **940 testes aprovados em 261,10 s**, antes das alterações. O suporte principal já estava no commit `6a53c7f`; foi auditado e complementado, sem reconstruir milestones anteriores.

## Arquivo real

Arquivo `APLICACAO_V16_0_NOVO.xlsx`, aba principal **APLICACAO GERAL**, formato `APPLICATION_GENERAL`. SHA-256: `7b7965da68f6a19cbb08a78be94e7e2073ac952616cbd02edd6cba8a2c9e3aeb`, idêntico antes/depois. RESUMO_MDL.xlsx, original e cópia local, conserva SHA-256 `32aac84eedec3e8b34e48920bc4bf03c17ccc773886cd84490d2e6f64f57cfdc`. Nenhum Excel real foi alterado ou adicionado ao Git.

| Medida do consolidado | Total |
|---|---:|
| Linhas de dados lidas e válidas | 8.744 |
| Veículos normalizados | 3.361 |
| Aplicações preservadas (linhas) | 8.744 |
| Aplicações sem repetição exata | 8.734 |
| Chaves veículo/sistema/cabo | 8.702 |
| Sistemas normalizados distintos | 616 |
| Linhas exatamente duplicadas | 10 |
| Chaves com atributos divergentes | 32 |
| Conflitos de suporte | 0 |
| Registros estruturalmente inválidos | 0 |

A tabela contém também uma linha de cabeçalho, que não conta como aplicação. Os 206 valores FIPE “Verificar nome” são preservados sem conversão booleana. APLICAÇÃO V16 contém 337 registros com VERS. V15.0: é metadado complementar e não é somada ao consolidado. VERSOES tem seis divergências de totais históricos, sinalizadas sem correção automática. VERS. identifica a introdução da aplicação, nunca a versão publicada do arquivo.

## Lacuna corrigida

O relatório anterior exibia Conflitos: 0 porque contava apenas divergências de suporte, embora guardasse os 32 avisos APPLICATION_VARIANT. Agora conta separadamente chaves com variantes técnicas, linhas variantes e conflitos de suporte. O resumo total e a confirmação exibem 32 conflitos. Relatórios históricos recebem somente uma projeção de leitura dos avisos preservados; os bytes, relatórios armazenados, eventos e decisões não são reescritos.

## Arquitetura e modelo

ScannerBaseAdapter mantém LegacyScannerBaseAdapter e ApplicationGeneralScannerBaseAdapter, com detecção central e cabeçalhos por nome. Formatos desconhecidos são bloqueados. Motorcycle/motorcycles/motorcycle_snapshots equivalem a ScannerVehicle: identidade normalizada fabricante + modelo + ano, com ID persistente e snapshot por importação. SystemRecord/system_records equivale a ScannerApplication: ID, importação, veículo, origem/linha, sistema, cabo, versão de introdução, tipo de teste, flags e metadados originais no payload JSON. Matéria-prima textual permanece em raw_fields/raw.

Matching continua PartnerVehicle → Motorcycle, sem matching por aplicação. SIM/NÃO são reconhecidos; outros valores permanecem raw com interpretação nula e aviso. Nenhum atributo novo comprova suporte. Persistência e snapshots usam lotes; índice existente por importação/veículo atende as consultas. Migration atual: **014_scanner_versions.sql**. Nenhuma migration nova necessária e nenhuma antiga editada.

## Comparação e impacto

Ensaio isolado partiu da cópia pré-V16 preservada no Milestone 13 (importação 2), porque o banco operacional já estava na V16. Comparação: **1.337 → 3.361 veículos**, 2.329 adicionados, 305 removidos, 1.032 alterados, zero inalterados. Há 895 pistas de revisão de identidade; não são fusões automáticas nem correspondências confirmadas.

Aplicações técnicas: 3.967 → 8.702 chaves, 8.628 adicionadas, 3.893 removidas, 74 com atributos alterados, zero trocas inequívocas de cabo e zero mantidas. Diferenças de nomenclatura entre formatos participam desse resultado; nenhuma aproximação une registros silenciosamente.

Na população da cópia: zero decisões humanas e zero desenvolvimentos impactados; o histórico de decisões ficou idêntico. Fixtures existentes exercitam presença humana válida, remoção de alvo, ausência vinculada à versão anterior, possível atendimento sem concluir desenvolvimento e retenção de prioridades manuais. Priorização recalcula apenas evidências/políticas afetadas pela publicação; as rotinas temporais seguem preservadas.

## Dashboard, busca e indicadores

A confirmação repete os totais e impactos antes da ação explícita. Aplicações e sistemas aparecem como quantidades diferentes na listagem por veículo. O painel de atualização oferece Consultar veículos da base ativa, mantendo Base do scanner oculta no menu. Busca combina fabricante, modelo, ano, sistema e cabo sem multiplicar veículos. Busca real MX-AT1601 retornou 524 veículos. A amostra BMW|F850GSRALLYE|2023 contém oito aplicações. Detalhe paginado mantém sistema, cabo, versão de introdução, tipo de teste, vídeo, FIPE, imobilizador, funções avançadas e scooter. Milestone 13 distingue veículos, aplicações e sistemas.

## Validação e desempenho

Somente bancos temporários em reports/v16-completion foram preparados/publicados pelos ensaios. Staging preservou a versão anterior; confirmação obrigatória e publicação transacional foram verificadas. Resultado derivado DONE, SQLite integrity_check = ok e foreign_key_check vazio. Persistência confirmou 3.361 veículos e 8.744 aplicações. Os testes mantêm a verificação de rollback e hash duplicado.

| Etapa local | Segundos |
|---|---:|
| Leitura, validação e parsing | 2,0165 |
| Comparação | 2,3245 |
| Staging completo | 6,2912 |
| Persistência em lote | 1,4136 |
| Publicação temporária com atualização derivada | 7,7632 |

Tempos medidos nesta máquina, com verificações concorrentes, sem promessa de SLA. Evidências locais ignoradas pelo Git: reports/v16-completion/validation.json e capturas/relatório do navegador. Testes focados: 86 aprovados. Oito novos testes reforçam contagem por chave, separação de suporte, cinco sistemas por veículo, cabos/versões, formato desconhecido, leitura histórica sem escrita, staging, confirmação e consulta técnica pela navegação interna.

## Prontidão e preservação operacional

O arquivo é estruturalmente válido e tecnicamente apto ao fluxo de publicação, com os 32 conflitos e demais avisos sujeitos à conferência humana. A inspeção somente leitura encontrou **importação 3 já publicada**, com o mesmo SHA. Essa publicação foi feita anteriormente pelo usuário (auditoria de 30/09/2026) e foi preservada; nenhuma nova publicação operacional foi executada. O fluxo de deduplicação impede publicar novamente o mesmo arquivo. Uma futura mudança ativa aguarda autorização explícita.

Limitações: presença não equivale a suporte; nomes alterados não são unidos por fuzzy; fórmulas não são executadas; totais históricos não são autoridade do consolidado; rollback operacional por botão não está exposto. Classificações técnicas desconhecidas e variantes exigem interpretação humana. Não foram adicionados parceiros nem alterações de permissões/menu.

Arquivos principais desta conclusão: scanner_base/adapters.py, services/scanner_validation.py, database/scanner_repository.py, services/dashboard_service.py, ui/scanner_panel.py, ui/textos.py, app/dashboard.py, tests/test_v16_completion.py, docs/NOVA_BASE_APLICACAO_V16.md e README.md. Apenas código, testes e documentação entram no commit. O SHA final é informado na entrega e pode ser consultado pelo commit `feat: complete V16 scanner base migration support`; sem hash autorreferente neste arquivo.


## Resultado final da conclusão

**948 testes aprovados em 311,86 s**: os 940 existentes preservados e oito novos. Ruff check, ruff format --check (154 arquivos), compileall app/services/database/ui/scanner_base e git diff --check aprovados. Navegador Edge/Playwright: fluxo de upload, staging, resumo com 32 conflitos, confirmação/publicação exclusivamente temporária, busca por cabo e detalhe por sistema passaram em 37,591 s, sem erros JavaScript. Capturas inspecionadas visualmente; menu simplificado preservado. A CLI agent-browser não estava disponível, por isso foi utilizado o Playwright já instalado com Edge.

Commit e push destinados exclusivamente a milestone-3-wr-motos-wip, sem merge em main. A publicação operacional preexistente permanece na importação 3, com o mesmo SHA do arquivo real.
