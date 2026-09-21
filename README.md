# Moto Coverage Monitor

Automação para identificar veículos de parceiros sem cobertura completa no scanner.
**Entrega atual: Milestones 1 e 2 — Base Scanner e Matching.** Parser, normalização,
consolidação, SQLite versionado, matching exato/aproximado e revisão manual via CLI
funcionam com a base real. Coletor WR Motos, dashboard, ações de desenvolvimento
e scheduler são etapas seguintes.

## Começar no Windows

Abra o PowerShell nesta pasta. Requer Python 3.12 ou superior.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m app.import_base "C:\Users\USER\Desktop\Automatização\RESUMO_MDL.xlsx"
```

Também é possível colocar o arquivo em `data/RESUMO_MDL.xlsx` e executar:

```powershell
.\.venv\Scripts\python.exe -m app.import_base data/RESUMO_MDL.xlsx
```

Linux/macOS: use `.venv/bin/python` nos mesmos comandos. Para execução sem testes,
instale apenas `requirements.txt`. Não há credenciais ou variáveis de ambiente obrigatórias.

O comando retorna o número da versão, quantidade de registros e veículos.
Cada execução cria uma versão, mesmo se o conteúdo for idêntico. A reimportação de
conteúdo idêntico deve gerar diferenças vazias, sem duplicar a identidade dos veículos.
O Excel original é aberto apenas para leitura. Seu SHA-256 é conferido antes e após o processamento.

Parâmetros opcionais:

```powershell
python -m app.import_base data/RESUMO_MDL.xlsx --db data/coverage.sqlite3 --reports reports --rules config/rules.json
```

## Resultados da inspeção real

- Aba `Planilha1`; colunas `LANC.`, `DATA`, `MONTADORA`, `MODELO`, `ANO`, `SISTEMA`,
  `CABO`, `LOCALIZACAO CABO` e `SIT.`.
- 3.993 registros válidos, 1.376 combinações textuais originais e 1.337 identidades normalizadas.
- 38 nomes normalizados de montadoras/categorias; 3.965 pares distintos veículo/sistema.
- 4 linhas exatamente duplicadas, preservadas na auditoria e sem inflar a quantidade de sistemas.
- 8 datas contêm `xxx`. Mantêm-se os registros, com data nula e ocorrência de auditoria.
- Uma célula em H1048568 contém apenas localização do conector. A linha é rejeitada,
  preservando o conteúdo em `import_issues`.
- Um conflito de sistema: HONDA POP 110I 2025, linhas 1605 e 2128.
- Dados náuticos e outras categorias estão presentes. Não há classificação de tipo de veículo
  suficientemente confiável para excluí-los automaticamente.
- `KAWASSAKI` permanece separada de `KAWASAKI` até revisão. `SEA-DOO`/`SEADOO`
  são unificadas por alias explícito; `SHINERAY/SBM`, `SBM` e `SHINERAY` são preservadas.

Esses números documentam a execução entregue; **nenhuma contagem é constante no código**.
Consulte `reports/import-0001/RELATORIO_BASE.md` para a lista de montadoras, exemplos e status.
Cada relatório JSON registra as regras usadas, a origem e o hash do arquivo.

## Interpretação de status

Regras ficam em `config/rules.json` e são copiadas para cada versão no banco.

| Valor | Interpretação inicial |
|---|---|
| LANC. = Sim/sim | Suporte declarado |
| LANC. = NÃO / NÃO LANÇAR | Sem suporte lançado |
| ANALISE em LANC. ou SIT. | Em análise |
| SIT. = OK | Evidência de suporte, sujeita a conflito com LANC. |
| V10–V16, MC, MODO COLABORATIVO, observações livres | SEM_STATUS até confirmação |

Valores não mapeados não se tornam suporte positivo. `SIT.` vazia não significa
falta de suporte quando `LANC.` tem indicação explícita conhecida.
`SUPORTADO` significa que **todos os sistemas registrados** têm suporte declarado;
não prova que todos os sistemas eletrônicos possíveis daquela moto estão cobertos.

Dentro de um mesmo sistema, estados divergentes geram `SEM_STATUS` e uma ocorrência.
Entre sistemas, suporte positivo e negativo produzem `SUPORTE_PARCIAL`. Em seguida
prevalecem `EM_ANALISE`, `SEM_STATUS`, ou o estado unânime. Os sistemas de cada classe
são preservados separadamente para inspeção, mesmo quando o status agregado tem outra precedência.

Para confirmar versões como lançadas, adicione os valores individualmente ao mapa
`release_status`, por exemplo `"V16": "SUPORTADO"`, após validar a regra de negócio.
Reimporte: a versão anterior continuará disponível com a política anterior.

## Modelo de domínio e arquitetura

```text
app/import_base.py              CLI, logs e tratamento de falhas
scanner_base/excel_reader.py    Leitura OOXML em fluxo
scanner_base/parser.py          Cabeçalhos, validação, datas e proveniência
scanner_base/normalizer.py      Identidade conservadora e aliases
scanner_base/status.py          Regras de status independentes
scanner_base/aggregator.py      Consolidação por veículo e sistema
scanner_base/models.py          SystemRecord, Motorcycle, ParsedBase
database/repository.py         Transações, snapshots e diferenças
database/migrations/           Esquema SQLite versionado
services/import_service.py     Orquestração da importação
services/report_service.py     Relatórios Markdown, JSON e CSV
config/rules.json              Política de classificação
tests/test_scanner.py          Testes unitários e de integração
data/coverage.sqlite3          Banco entregue com importações reais
reports/import-NNNN/           Resultados por execução
```

`SystemRecord` mantém campos originais, aba/linha, identidade normalizada, sistema,
estado e motivo, lançamento, data, cabo e localização. `Motorcycle` agrega a chave
`MONTADORA|MODELO_NORMALIZADO|ANO`, quantidade de sistemas, listas por suporte,
data mais recente e todos os rótulos de lançamento. A identidade persistente tem ID próprio.

O parser reconhece cabeçalhos por nome, permite outras posições/ordens, registra abas
ignoradas e cabeçalhos repetidos, recusa cabeçalhos duplicados e não preenche identidades
vazias por arraste. Anos ambíguos (como 2024/2025) são rejeitados. Datas usam a época
1900/1904 do workbook. Fórmulas e erros Excel nas linhas de dados exigem revisão;
valores de cache não são tratados como fonte confiável.

Normalização remove acentos, diferenças de caixa, espaços e hífens do modelo.
Não remove cilindrada, versão, prefixos de fabricante nem pontuação potencialmente
significativa (`+`, `/`). BMW F 900R, F900 R e F-900-R têm a mesma identidade.
Suzuki DL 650 XT V-Strom e V-Strom 650 XT são candidatos ao matching aproximado,
com confirmação manual; não se tornam aliases automáticos.

## Matching — Milestone 2

Depois de instalar as dependências atualizadas, execute:

```powershell
python -m app.match --manufacturer BMW --model "F900 R" --year 2025
python -m app.match --manufacturer SUZUKI --model "V-Strom 650 XT" --year 2024
python -m app.match --manufacturer BMW --model "F 900 GS" --version PLUS --year 2025
```

Use o executável da `.venv` no lugar de `python` se ela não estiver ativada.
`--db` escolhe o banco, `--rules` escolhe a política de matching e `--reports` escolhe
a pasta dos resultados. A montadora e o modelo são obrigatórios. Ano ausente ou
ambíguo (2024/2025) produz REVISAR, sem escolher um ano silenciosamente.
`--version` participa da identidade; uma versão já presente como sufixo de tokens
no modelo não é anexada duas vezes.

Cada execução fica salva em `matching_runs` e em `reports/matching/match-NNNN.json`.
O relatório contém consulta original, chave normalizada, versão da base, versão do
algoritmo/RapidFuzz, política completa, candidatos, scores, motivos e bloqueios.
As consultas de demonstração incluídas no pacote são exemplos executados contra a
base real; **não são anúncios coletados de parceiros**.

### Resultados possíveis

| Tipo | Significado | Confirmação |
|---|---|---|
| EXATO_NORMALIZADO | Montadora + modelo + ano iguais após normalização | Automática, confiança 100 |
| CORRESPONDENCIA_PROVAVEL | Fuzzy acima do limiar e sem ambiguidade/bloqueios | Revisão humana obrigatória |
| REVISAR | Campos incompletos, baixa confiança, versões ou candidatos próximos | Revisão humana obrigatória |
| NAO_ENCONTRADA_NA_BASE | Nenhum candidato passou pelos filtros e limiar | Sem vínculo; confiança 0 |

A confiança é um score heurístico de identidade, **não uma probabilidade calibrada**
nem um percentual de suporte. Apenas o match exato preenche `scanner_key` e
`scanner_status` automaticamente. Fuzzy deixa esses campos nulos e exibe o status
de cada candidato separadamente. Assim uma sugestão de moto suportada não vira
automaticamente uma conclusão de cobertura. Ausência de candidato não prova
inexistência: pode ser causada por grafia, alias desconhecido ou dados insuficientes.

### Regras e cálculo

`config/matching.json` configura limiar de candidatos (55), provável (88), margem de
ambiguidade (8 pontos), máximo de candidatos exibidos (5), pesos e tokens de versão.
Os aliases de fabricante vêm da política salva na importação consultada, garantindo
consistência com as chaves daquela base.

1. Igualdade da chave normalizada tem precedência, com score 100.
2. Fuzzy considera apenas a mesma montadora normalizada e o mesmo ano.
3. Modelos são divididos em letras, números e pontuação significativa, inclusive
   quando aparecem unidos (`DL650XT`). A ordem original não é perdida na auditoria.
4. A assinatura numérica principal usa o primeiro número >= 50, ou o primeiro número
   disponível. Assinaturas diferentes eliminam o candidato. Essa é uma heurística
   de identificação, não uma extração garantida da cilindrada real; também protege
   designações como R1/R6 e Harley 114/117.
5. Score bruto = 0,65 × token_sort_ratio + 0,25 × token_set_ratio + 0,10 × ratio
   compacto, calculados pelo RapidFuzz. `token_set` não decide isoladamente.
6. Tokens protegidos diferentes/incompletos descontam 18 pontos. Números secundários
   diferentes ou informação numérica ausente bloqueiam a classificação provável.
   Diferenças de palavras continuam visíveis, inclusive as não protegidas.
7. Scores com bloqueios ficam abaixo do limiar provável; todo fuzzy é limitado a 99.
   Scores finais abaixo do limiar de candidatos são omitidos.
8. A diferença entre os dois melhores scores é avaliada antes de limitar a lista
   exibida. Empate ou margem insuficiente gera REVISAR; ordenação usa a chave como
   desempate estável, nunca como autorização de escolha.

As regras são deliberadamente conservadoras. Novas abreviações e versões devem ser
validadas com casos reais; não há lista fixa de motos, aprendizagem automática nem
alteração das identidades importadas. Modelos com números comerciais incomuns podem
ficar sem candidato, e o usuário pode corrigir a consulta e executá-la novamente.

### Revisão manual auditável

```powershell
python -m app.review_match list
python -m app.review_match show 2
python -m app.review_match decide 2 --candidate "SUZUKI|DL650XTVSTROM|2024" --reviewer "Seu nome" --note "Identidade conferida"
python -m app.review_match decide 2 --no-match --reviewer "Seu nome" --note "Nenhum candidato corresponde"
```

Substitua `2` pelo ID exibido na execução. Para escolher outro banco, informe
`--db caminho.sqlite3` **antes** de `list`, `show` ou `decide`.
Só é possível confirmar uma chave presente nos candidatos daquela execução.
Se a opção correta não estiver exibida, corrija a consulta ou amplie `max_candidates`
na política e gere outra execução. A lista retorna todas as pendências ainda não revisadas.

Revisor e justificativa são obrigatórios. Uma nova decisão não sobrescreve a anterior:
o histórico permanece e a mais recente determina `effective_result`. O resultado
automático original continua em `automatic_result`. A confirmação humana usa confiança
nula, pois não inventa uma porcentagem; o score automático continua disponível.

Cada decisão vale para uma execução e uma versão da base. Não é reaplicada como
alias nem herdada por consultas futuras. `is_current_base=false` identifica um
resultado histórico quando houver nova importação. Nesse caso o status exibido é
o da versão antiga; execute outra consulta para avaliar a base vigente.
O JSON exportado pelo matching é um retrato daquela execução: use `show` para
consultar decisões posteriores. Nenhuma decisão humana real foi simulada no banco
entregue; os testes de confirmação usam bancos temporários.

### Módulos adicionados

```text
matching/models.py               Consulta, candidato e resultado
matching/rules.py                Validação da política configurável
matching/fuzzy_matcher.py        Tokens, evidências, filtros e score
matching/matcher.py              Exato, fuzzy, ambiguidade e revisão
database/matching_repository.py  Execuções, fila e decisões históricas
database/migrations/002_matching.sql
services/matching_service.py     Integração com a versão vigente da base
app/match.py                    Consulta por linha de comando
app/review_match.py             Listagem, inspeção e decisões
tests/test_matching.py          Regras e fluxo completo da CLI
```

A migração 002 é aplicada automaticamente ao abrir o repositório. Ela acrescenta
`matching_runs` e `matching_reviews`, sem modificar os registros das importações
anteriores. Migrações são numeradas, transacionais e aplicadas uma única vez.

### Área usada excessiva

O XLSX de 9,4 MB declara `A1:AMJ1048568`, com XML de aproximadamente 75,7 MB.
O leitor SAX percorre os bytes XML em blocos de 1 MiB, ignorando células sem conteúdo
e sem materializar o retângulo declarado. A memória escala com células preenchidas
e shared strings, não com o produto de linhas e colunas formatadas. O leitor não
interrompe em lacunas: assim detecta a célula isolada no fim. Ainda precisa percorrer
o XML serializado; não promete tempo independente do tamanho físico do arquivo.
O parser rejeita DTD e arquivos maiores que 512 MiB descompactados.
Openpyxl é usado na conversão de datas e nas fixtures de teste, não para expandir
a área formatada do arquivo real. Pandas não é necessário nesta etapa.

### Banco e histórico

`imports` guarda origem, hash, política, relatório e diferenças.
`motorcycles` mantém a identidade e primeira importação.
`motorcycle_snapshots` mantém o estado de cada veículo por versão.
`system_records` mantém cada registro original por versão.
`import_issues` mantém rejeições, ambiguidades e conflitos.

A última versão define a base vigente. Veículos removidos não aparecem no snapshot
vigente, mas suas identidades e versões antigas continuam no banco.
Importações são transacionais, com foreign keys, WAL, timeout e bloqueio de escrita
antes de comparar com a versão anterior. Falha durante a gravação faz rollback completo.
Relatórios em arquivos são escritos após o commit; falha nessa exportação não apaga
uma importação já concluída no banco. Logs de erro incluem traceback e código de saída 1.

O SQL fica isolado no repositório. PostgreSQL exigirá outro adaptador e migrações;
não basta trocar a URL. Faça backup do banco com a aplicação parada ou pela API
de backup do SQLite para incluir corretamente eventuais arquivos WAL.

## Relatórios e auditoria

Cada `reports/import-NNNN/` contém:

- `RELATORIO_BASE.md`: leitura humana com estrutura, métricas, montadoras e exemplos.
- `report.json`: métricas, política, hash e diferenças para a versão anterior.
- `motorcycles.json`: lista consolidada com sistemas por estado.
- `motorcycles.csv`: consulta no Excel, delimitador `;`, UTF-8 com BOM.
- `issues.json`: inconsistências com as linhas de origem.

CSV neutraliza prefixos que possam ser interpretados como fórmulas ao abri-lo no Excel.
Os valores originais permanecem no JSON e no SQLite. Os exemplos do relatório são
amostras; a lista completa está em `motorcycles.json` e no CSV.

## Validação

```powershell
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
python -m compileall -q app scanner_base matching database services
python -c "import app.import_base, app.match, app.review_match, matching.matcher, database.matching_repository"
```

Testes cobrem identidade, versões distintas, aliases, anos inválidos, datas, regras de
status, conflitos, duplicidades, área esparsa, ordem de colunas, abas extras, fórmulas,
reimportação, remoção, diferenças e rollback. As fixtures usam arquivos temporários.
`VALIDACAO.md` registra a validação histórica do Milestone 1.
`VALIDACAO_MILESTONE_2.md` registra os testes e a execução da entrega atual.

## Docker (importação)

```powershell
docker build -t moto-coverage-monitor .
docker run --rm -v "${PWD}/data:/app/data" -v "${PWD}/reports:/app/reports" moto-coverage-monitor data/RESUMO_MDL.xlsx
```

Copie o Excel para `data/` antes. O container usa Python 3.12; os volumes preservam
o banco e os relatórios. Esta receita está preparada, mas não foi executada nesta entrega.

Para usar o matching na imagem, substitua o entrypoint:

```powershell
docker run --rm -v "${PWD}/data:/app/data" -v "${PWD}/reports:/app/reports" --entrypoint python moto-coverage-monitor -m app.match --manufacturer BMW --model "F900 R" --year 2025
```

## Próximos milestones

3. Inspecionar robots.txt, termos, HTML e tráfego público da WR Motos; só então
   implementar `PartnerCollector` e registro de adaptadores independentes do comparador.
4. Comparação scanner/parceiros com estados de atenção.
5. Streamlit: oportunidades, base scanner, parceiros e decisões persistidas.
6. Histórico de anúncios, first/last_seen, verificações independentes do dashboard,
   agendamento diário às 07:00 e alertas.

Playwright será instalado no Milestone 3 se a inspeção não revelar uma fonte pública
estruturada adequada. Não há `app.monitor` nem dashboard executável ainda, e nenhum
agendamento ou acesso à WR Motos foi ativado neste milestone.
