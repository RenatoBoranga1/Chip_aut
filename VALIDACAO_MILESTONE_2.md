# Validação — Milestone 2: Matching

Execução em 21/09/2026 no Windows, Python 3.14.7 e RapidFuzz 3.14.6.
Entrega: correspondência exata, fuzzy, confiança configurável, candidatos e revisão
manual auditável por linha de comando. Dashboard e coletor continuam nos próximos marcos.

## Resultado dos checks

- **97 testes aprovados em 1,71 s**: 48 da base scanner e 49 de matching/integração.
- Ruff: `All checks passed!`.
- Formatação: 29 arquivos Python verificados.
- Compilação e imports: sem erros.
- Regressão sobre a base real: 1.337 de 1.337 veículos encontraram a própria chave exata.
- Regressão dos dados de origem: 3.993 de 3.993 registros da importação vigente
  encontraram a identidade consolidada correta a partir dos campos originais.
- As duas verificações de identidade, carregamento do banco e migração levaram
  aproximadamente 0,21 s nesta máquina. Esse tempo não inclui importar o Excel.
- Migração 002: aplicada sem modificar o conteúdo das cinco tabelas do Milestone 1.
  A comparação usou hashes das linhas antes/depois, incluindo as duas importações históricas.
- SQLite: `integrity_check = ok`, nenhuma violação de foreign key.
- Nenhuma decisão humana foi fabricada: há zero registros em `matching_reviews`
  no banco entregue. Testes de revisão usaram bancos temporários.

## Demonstrações com a base real

As consultas abaixo são cenários de validação, não anúncios coletados.

| ID | Consulta | Resultado | Score | Observação |
|---:|---|---|---:|---|
| 1 | BMW F900 R, 2025 | EXATO_NORMALIZADO | 100 | Chave BMW/F900R/2025; status do scanner SEM_STATUS |
| 2 | Suzuki V-Strom 650 XT, 2024 | CORRESPONDENCIA_PROVAVEL | 88,71 | Candidato DL 650 XT V-STROM; confirmação pendente |
| 3 | BMW F 900 GS, 2025 | REVISAR | 64,02 | Versão incompleta e candidatos próximos |
| 4 | BMW F900 R, 2024/2025 | REVISAR | 0 | Ano ambíguo; nenhum ano presumido |
| 5 | BMW F900 R, 2027 | NAO_ENCONTRADA_NA_BASE | 0 | Nenhum candidato elegível para esse ano |

O exemplo `Suzuki V Strom DL650XT` também é coberto por teste: ordem e espaços
podem variar, mas o resultado segue como sugestão com revisão, nunca verdade absoluta.
O exemplo `BMW F-900-R` é coberto como equivalência exata a `BMW F 900R`.

O banco entregue contém cinco execuções de demonstração, três delas na fila de revisão.
Resultados completos: `reports/matching/match-0001.json` a `match-0005.json`.
Resumo verificável: `reports/matching/verification.json`.

## Comandos executados

Na raiz do projeto, usando o Python do ambiente virtual da sessão:

```powershell
python -m pip install rapidfuzz
python -m ruff check . --fix
python -m ruff format .
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
python -m compileall -q app scanner_base matching database services
python -c "import app.import_base, app.match, app.review_match, matching.matcher, database.matching_repository"
python -m app.match --manufacturer BMW --model "F900 R" --year 2025
python -m app.match --manufacturer SUZUKI --model "V-Strom 650 XT" --year 2024
python -m app.match --manufacturer BMW --model "F 900 GS" --year 2025
python -m app.match --manufacturer BMW --model "F900 R" --year "2024/2025"
python -m app.match --manufacturer BMW --model "F900 R" --year 2027
```

Testes de subprocesso executaram `app.review_match list`, `show` e `decide` em banco
temporário e validaram reabertura, correção de decisão, rollback de decisões inválidas,
base atual versus histórica e códigos de saída de erro.

## Arquivos adicionados

- `matching/__init__.py`, `models.py`, `rules.py`, `fuzzy_matcher.py`, `matcher.py`.
- `config/matching.json`.
- `database/migrations/002_matching.sql` e `database/matching_repository.py`.
- `services/matching_service.py`.
- `app/match.py` e `app/review_match.py`.
- `tests/test_matching.py`.
- Este relatório e os resultados em `reports/matching/`.

## Arquivos atualizados

- `database/repository.py`: aplicação transacional de migrações numeradas.
- `requirements.txt`: RapidFuzz fixado em 3.14.6.
- `pyproject.toml`: versão 0.2.0 e descrição dos dois milestones.
- `Dockerfile`: inclui o pacote de matching.
- `README.md`: comandos, fórmula, limites, política, revisão e roadmap.
- `data/coverage.sqlite3`: migração e execuções, mantendo o histórico anterior intacto.

## Limites conhecidos

Scores fuzzy são heurísticos, não probabilidades calibradas. Não houve medição
de precisão/recall contra anúncios rotulados de parceiros; essa avaliação depende
do coletor e de revisão de amostras reais. Os testes verificam regras e regressões.

Fabricante e ano são filtros estritos. O número principal é uma assinatura comercial
conservadora, não uma garantia de cilindrada. Grafias e nomenclaturas desconhecidas
podem ficar sem candidato. Diferenças de versão nunca autorizam confirmação automática.

V10–V16 e MC continuam com a semântica conservadora do Milestone 1; o matching não
altera esses estados nem interpreta uma correspondência como cobertura completa.
Decisões são locais à execução e não se propagam para futuras consultas. Não existe
interface gráfica de revisão nesta etapa; o fluxo está funcional na CLI e no SQLite.

Docker e Python 3.12 não foram executados nesta sessão. Não houve acesso à WR Motos.
