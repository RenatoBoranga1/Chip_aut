# Resultados — Milestone 10.1

Branch: `milestone-3-wr-motos-wip`. SHA inicial: `e069c2bc6ddb8da32ca93e045b09580e02d41962`. Baseline: 883 testes; resultado final: **922 aprovados**, 151,11 s. Sem merge em main.

## Arquivo real e importação isolada

APLICACAO_V16_0_NOVO.xlsx, SHA-256 `7b7965da68f6a19cbb08a78be94e7e2073ac952616cbd02edd6cba8a2c9e3aeb`, preservado. Consolidado: **3.361 veículos, 8.744 linhas, 8.734 aplicações sem repetição exata, 8.702 chaves veículo/sistema/cabo e 616 sistemas distintos**. Dez repetições exatas e 32 variantes técnicas preservadas. Nenhuma linha inválida. Há 206 valores FIPE “Verificar nome”, preservados sem interpretação booleana. A aba complementar tem divergência de versão; resumos históricos têm seis divergências de total, tratadas como avisos.

Comparação contra cópia pré-V16 (importação 2, preservada no Milestone 13): 1.337 → 3.361 veículos; 2.329 adicionados, 305 removidos, 1.032 alterados e zero inalterados. 895 sugestões para revisão de identidade não efetuam associação automática. Comparação técnica: 3.967 → 8.702 chaves; 8.628 adicionadas, 3.893 removidas e 74 com atributos alterados; nenhuma troca inequívoca de cabo. Mudanças de nomes entre formatos explicam parte do diff e exigem conferência humana.

Persistência temporária confirmou 3.361 veículos/8.744 aplicações, SQLite íntegro, nenhuma violação de chave estrangeira e decisões históricas inalteradas. Busca MX-AT1601: 524 veículos. Um veículo amostrado apresentou oito aplicações. Impacto em decisões/desenvolvimentos existentes na cópia: zero; cenários com decisões, ausências, desenvolvimento e prioridades são cobertos por fixtures dedicadas.

## Desempenho e interface

Comparação: 0,7498 s; staging: 2,1765 s; persistência em lote: 0,4538 s; publicação com atualização derivada: 2,2389 s. Medições locais, sem promessa de SLA.

Navegador Edge/Playwright: upload real em banco temporário, staging preservando versão ativa, confirmação explícita, publicação de teste e busca por cabo passaram em 21,82 s, sem erros JavaScript. Capturas e JSON ficam em reports/milestone-10-1 (ignorados pelo Git). AppTest também verifica formato, histórico de versão e detalhe técnico.

## Preservação operacional

Durante o trabalho, a V16 foi publicada pelo usuário na interface (auditoria de Renato Boranga em 30/09/2026). Essa publicação foi preservada: banco operacional permaneceu na importação 3 antes/depois da validação. Nenhum script deste trabalho publicou automaticamente nesse banco. Os ensaios partiram da cópia anterior e publicaram somente em bancos temporários. Arquivos Excel, SQLite e evidências operacionais não entram no Git.

## Arquitetura e verificação

Adaptadores em scanner_base/adapters.py; comparação em scanner_base/application_diff.py; integração com validação/importação/publicação existentes; busca e tabela técnica; contadores gerenciais; retenção de prioridades não afetadas. Sem migração nova e sem mudanças nas identidades. Os 39 novos testes incluem formato legado, validação, duplicidades, atributos, agrupamento, diferenças, publicação explícita/atômica, rollback transacional, hash, histórico humano, desenvolvimento, prioridade e interface. Consulte docs/NOVA_BASE_APLICACAO_V16.md para regras e limites.
