# Resultados — Milestone 8.3

Estado: implementação, investigação e validação automatizada concluídas; validação no navegador pendente. Não declarar o milestone integralmente concluído enquanto a validação real no navegador estiver pendente.

## Referência e preservação

- Branch: `milestone-3-wr-motos-wip`; sem merge em main.
- SHA inicial real: `77a7f79d7c30c5b6e08f805506ab1c98e2f9f5cb` (posterior à referência c673830).
- Baseline real: **1.077 testes aprovados em 469,17 s**.
- Novos testes: **38 aprovados em 5,89 s**. Suíte completa final: **1.115 aprovados em 428,13 s (7:08)**.
- Ruff check, Ruff format (179 arquivos), compileall de app/services/database/ui e diff check: aprovados.

## Investigação e decisão

| Parceiro | Fontes investigadas | Aprovado / habilitado | Classificação / contagens |
|---|---|---|---|
| Thomas | HTML, três detalhes, endpoints frontend, sitemaps, API AutoCerto documentada | Não / não | Sem tipo individual; 75 UNKNOWN; API exige OAuth2 privado |
| Motonil | Categoria 65, três detalhes, mapa/subcategorias, JSON-LD, fragmentos AJAX, fornecedor AF Systems | Não / não | 19 UNKNOWN; categoria mista e sem atributo individual |
| Moto Marques | Apenas fontes externas: loja Webmotors 3918827 e identidade/endereço em site oficial da loja Suzuki | Não / não | 27 anúncios externos observados, vínculo com unidade solicitada não comprovado; UNKNOWN do parceiro não avaliado |

Apenas **WR Motos** continua habilitada. Nenhum novo adapter criado. O domínio bloqueado da Moto Marques não foi acessado neste milestone. Nenhum bypass, credencial privada, cookie ou IA classificadora utilizado.

Amostra de ativação de 10–20: não aplicável, fases A–C não aprovadas. Os três detalhes Thomas e três Motonil serviram para investigação semântica; não constituem amostra de aprovação. Falsos positivos de ativação: não medidos. Zero anúncios publicados de candidatos não equivale a precisão de 100%. Os 97 UNKNOWN do M8.2 permanecem como registro histórico; a observação M8.3 de Thomas/Motonil totaliza 94, sem misturar datas.

## Funcionalidade entregue

- `PartnerSource` e seis registros persistidos com URL, fornecedor, tipo, data, confiança, identidade, classificação e motivo.
- Diagnóstico CLI incorpora fontes alternativas; `sources` consulta metadados; `collect --dry-run` usa o diagnóstico HTTP limitado já existente, sem banco, publicação ou decisões.
- Dry-run validado com transporte injetado e respostas públicas previamente capturadas: Thomas 75 UNKNOWN, Motonil 19 UNKNOWN, ambos BLOCKED. Moto Marques bloqueada sem chamada de rede. Isso não é uma nova coleta ao vivo nem autorização de integração.
- Parsing offline de JSON/API/feed/JSON-LD e descoberta de sitemap com limites; nenhuma URL encontrada é seguida automaticamente.
- Validador explica UNKNOWN, carro, kart, serviço, identidade inválida e duplicatas; perda de tipo em fonte anteriormente aprovada produz DEGRADED, sem publicação.
- Quatro códigos de aviso diagnósticos deduplicados. Não são notificações persistidas; como não existe nova coleta habilitada, não há produtor operacional de alertas alternativos.
- Página Parceiros mostra evidências e motivos, sem acessar sites. Navegação e Assistente M14 preservados.

## Coleta, matching e regressões

Coleta real de novos parceiros: não aplicável. Matching exact/review/ambiguous/not_found: não executado, pois nenhuma fonte foi aprovada. Não houve alteração especial no matching ou consolidação cross-partner.

`run-all`, isolamento, configuração enabled, frequência WR e scheduler mantidos; não iniciado scheduler contínuo. Regressores existentes de WR, M14, V16 e decisões humanas fazem parte da suíte completa.

SQLite operacional: `integrity_check = ok`; SHA-256 antes/depois idêntico:
`80978b329e8eba42f977c0937254c968a456047c85df479fadd7ef382d587fbe`.
A base de navegador é cópia isolada e opera com `MOTO_READ_ONLY=1`, provider fake sem API.

## Performance e limites

Parsing + classificação das respostas capturadas (uma execução local, não benchmark): Thomas **0,109 s**, Motonil **0,033 s**. Tempos de descoberta e rede por requisição não foram instrumentados; não há duração total confiável a informar. Coleta aprovada e matching: não aplicáveis. O dry-run retorna duração própria de diagnóstico. Não há alegação de catálogo completo aprovado de nenhum candidato.

O parser offline aceita um contrato explícito de campos; ele não implementa a API privada AutoCerto nem transforma JSON genérico em integração. A API só pode ser reconsiderada com autorização/credenciais apropriadas e novo escopo. A loja Webmotors exige comprovação de identidade da unidade, além de validação semântica e amostra auditada.

## Navegador

Pendente: Parceiros, Visão geral, Possíveis novas motos, Fila de revisão, Alertas, Indicadores gerenciais e Assistente de IA. AppTest passou para painel de fontes e regressão do dashboard, mas não substitui essa inspeção. O navegador recusou conexão ao servidor iniciado no ambiente isolado; foi solicitado iniciar a versão atual no PowerShell do Windows, porta 8539.

## Arquivos e entrega

Principais arquivos: `partners/sources.py`, `config/partner_sources.json`, `partners/diagnostics.py`, `app/partners.py`, `ui/partner_diagnostics.py`, `tests/test_partner_sources.py`, `docs/FONTES_ALTERNATIVAS_PARCEIROS.md`. Documentos de avaliação/M8.2/operação e README atualizados.

Este relatório acompanha o commit `feat: add legitimate alternative partner inventory sources` na branch obrigatória; SHA e confirmação de push constam na entrega do chat. A pendência visual está explicitada acima. Bancos, HTML bruto, screenshots e logs não foram incluídos. Detalhes e fontes primárias: [investigação M8.3](docs/FONTES_ALTERNATIVAS_PARCEIROS.md).
