# Resultados — Milestone 8.4

Implementação iniciada em 08/10/2026; fechamento e revisão em 19/10/2026.
Branch: `milestone-3-wr-motos-wip`. Nenhum merge em main.
SHA inicial real: `4bd13751a6a822767d7e87ec3b0c574c196eeece`, alinhado ao origin no início.
Baseline: **1.115 testes aprovados em 443,56 s**.

## Arquitetura e canais

| Parceiro | Estado padrão | Canal |
|---|---|---|
| WR Motos | ATIVO_AUTOMATICO | PUBLIC_COLLECTION existente |
| Thomas Motos | ATIVO_MANUAL | FILE_IMPORT CSV/XLSX; AUTHENTICATED_COLLECTION opcional |
| Motonil | ATIVO_COM_TRIAGEM | STAGED_COLLECTION, classificação humana |
| Moto Marques Multimarcas | ATIVO_MANUAL | FILE_IMPORT CSV/XLSX |

`partners/integration.py` separa disponibilidade operacional e automação. O registro de collectors públicos e as avaliações M8.1–M8.3 permanecem preservados. Migração 015 adiciona importações, mapeamentos, staging, eventos imutáveis e alertas.

## Entregas funcionais

1. **Thomas sem credencial:** importação manual funciona; autenticação informa configuração pendente.
2. **Thomas auth:** token oficial por ambiente, endpoint fixo AutoCerto, tipo exato configurado, dados mínimos, sem login automático, redirects ou persistência de segredos. FakeAuthenticatedSource cobre validação sem credencial real. Automação requer autorização, auditoria e habilitação explícitas.
3. **Importador genérico:** CSV/XLSX, leitura limitada, fórmulas rejeitadas, colunas sugeridas/editáveis, perfil salvo por parceiro, preview de até 20 linhas, contagens de válidas/inválidas/duplicadas/sem ID/ano/modelo.
4. **Confirmação:** exige responsável, autorização/unidade e motocicletas conferidas. Upload/preview não publicam. Histórico guarda nome simples, hash, contagens, modo, ação, responsável e resultado.
5. **Idempotência:** mesmo parceiro/conteúdo/mapeamento/modo reutiliza lote; ID nativo atualiza anúncio. Fallback sem ID/URL só é estável para o mesmo arquivo.
6. **Incremental/snapshot:** incremental preserva ausentes; snapshot completo confirmado exige linhas válidas e IDs estáveis para retirar ausentes. Falha no matching reverte a publicação.
7. **Motonil staging:** coleta limitada permitida da categoria mista. Nenhum desconhecido é publicado; decisões são humanas, com responsável, justificativa e controle de revisão.
8. **Memória/reclassificação:** decisão reutilizada enquanto identidade não muda; mudança invalida classificação. Retirar classificação Moto inativa ocorrência e revisão, sem apagar histórico. Kart pode virar Moto após confirmação.
9. **Pipeline:** PartnerVehicleAd → normalização → matching existente → revisão. Origens aparecem nas consultas consolidadas, oportunidades, desenvolvimento e indicadores. Priorização aceita os novos parceiros e respeita sua manutenção habilitada.
10. **Multi-origem:** teste cobre quatro origens para uma identidade ScannerVehicle e um DevelopmentItem após ação humana explícita; nenhuma duplicação automática dessas entidades.
11. **run-all/scheduler:** somente fontes habilitadas e compatíveis; arquivo manual é ignorado. Motonil pode agendar staging; Thomas auth só após os controles. WR preservada; falha de um parceiro não impede resultado dos demais.
12. **CLI:** status com modos; import com dry-run/mapping/modo/confirmação; stage/triage Motonil; auth Thomas. Dry-run de arquivo não cria banco.
13. **Alertas:** pendência inicial derivada em leitura e falha/linhas inválidas/triagem/auth deduplicados. Indicadores mostram quatro parceiros operacionais, automáticos, manuais, triagem e importações.
14. **Dashboard:** novos controles dentro de Parceiros; seletor inclui parceiros com estoque publicado; modos traduzidos. A avaliação histórica de scraping permanece explicitamente identificada.
15. **Assistente M14:** consulta modos, pendências e última importação; somente leitura, sem ferramentas de escrita ou classificação por IA.

## Validação

- Primeira suíte completa: **1.151 aprovados em 418,26 s**.
- Suíte completa de 19/10: **1.153 aprovados em 376,90 s**, incluindo dois casos de XLSX corrompido.
- Regressões finais: **105 aprovados em 33,88 s** (operações, arquitetura e diagnóstico). Incluem o teste adicional de run-all com registro público desabilitado, acrescentado após a coleta da suíte completa; elevação total para 1.154 testes distintos cobertos entre as execuções. Os 105 não são somados integralmente aos 1.153, pois há sobreposição.
- Ruff check: aprovado. Ruff format --check: 193 arquivos formatados. Compileall app/services/database/ui: aprovado. Git diff --cached --check: aprovado.
- SQLite operacional e cópia de validação: `PRAGMA integrity_check = ok`.
- SHA256 operacional preservado: `80978b329e8eba42f977c0937254c968a456047c85df479fadd7ef382d587fbe`.
- Fixtures são geradas nos testes; arquivos CSV/XLSX sintéticos e banco para navegador ficam em `reports/milestone-8-4`, ignorados pelo Git.
- Navegador em 09/10: Visão geral e Parceiros abriram; quatro modos/status corretos; CSV Thomas selecionado e controles de mapeamento renderizados. Confirmação, XLSX, triagem e demais páginas ainda não concluídos.
- Em 19/10, a porta 8541 não estava ativa. O servidor iniciado no ambiente de execução não ficou acessível ao navegador; solicitada reinicialização no PowerShell do Windows. **Não considerar validação visual completa enquanto esses fluxos não forem exercitados.**

## Limitações explícitas

Não foram usados credenciais ou arquivos reais dos novos parceiros. Thomas precisa confirmar conta/unidade e valor oficial TipoVeiculo antes da automação. Motonil usa coleta limitada até staging, não certifica catálogo completo, e depende de confirmação de marca/modelo/ano. Moto Marques não sofreu scraping direto; a origem/unidade do arquivo é confirmada pelo operador. Arquivos alterados sem código/URL podem gerar outra ocorrência. Dados de validação não são estoque real. Nenhuma alteração na base V16 ou no banco operacional foi necessária.

## Arquivos principais e operação

- `partners/integration.py`, `partners/authenticated_source.py`.
- `database/inventory_repository.py`, `database/migrations/015_partner_operations.sql`.
- `services/partner_inventory_import.py`, `services/motonil_staging_service.py`, `services/partner_operation_scheduler.py`.
- `ui/partner_operations.py`, `app/partners.py`, `app/scheduler.py`, `app/dashboard.py`.
- `tests/test_partner_operations.py`: regressões, integração, AppTest e fixtures sintéticas.
- [Modos](docs/MODOS_INTEGRACAO_PARCEIROS.md), [importação](docs/IMPORTACAO_ESTOQUE_PARCEIROS.md), [triagem](docs/TRIAGEM_MOTONIL.md), [auth](docs/THOMAS_AUTHENTICATED_SOURCE.md).

Implementação preparada para commit `feat: add operational integration modes for all partners` e push na mesma branch. SHA final, resultado do push e estado Git são informados na entrega; o SHA do próprio commit não é gravado no arquivo que o compõe. **Milestone ainda não homologado integralmente: falta concluir os fluxos de navegador descritos acima.**
