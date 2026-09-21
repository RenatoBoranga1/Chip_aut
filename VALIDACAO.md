# Validação da entrega — Milestone 1

Executada em 21/09/2026, Windows, Python 3.14.7, openpyxl 3.1.5,
pytest 9.1.1 e Ruff 0.16.8. Compatibilidade declarada: Python 3.12+.
Docker/Python 3.12 não foram executados nesta sessão.

## Comandos executados

Na raiz do projeto, com o Python do ambiente virtual da sessão:

```text
python -m ruff check . --fix
python -m ruff format .
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
python -m compileall -q app scanner_base database services
python -c "import app.import_base, scanner_base.parser, database.repository"
python -m app.import_base "C:\Users\USER\Desktop\Automatização\RESUMO_MDL.xlsx"
```

A importação real foi executada duas vezes. As correções automáticas do lint
ajustaram a ordem de imports; todos os checks foram repetidos após as alterações.

## Resultados

- Pytest: **48 passed in 0.47s**.
- Ruff lint: **All checks passed!**
- Ruff format: **17 files already formatted**.
- Compilação e imports: concluídos sem erros.
- Importação final: 3.993 registros; 1.337 veículos; aproximadamente 5,9 s até commit.
- Segunda versão: zero adições, remoções ou alterações de status/sistemas.
- SQLite `PRAGMA integrity_check`: `ok`.
- SQLite `PRAGMA foreign_key_check`: nenhuma violação.
- Banco entregue: 2 importações, 1.337 identidades, 2.674 snapshots,
  7.986 registros de sistemas e 4.686 ocorrências de auditoria.
- Verificação independente com Openpyxl, limitada aos nove campos e às linhas
  de dados identificadas: 3.993 registros e 1.376 combinações textuais originais.
- Hash do arquivo original permaneceu
  `32aac84eedec3e8b34e48920bc4bf03c17ccc773886cd84490d2e6f64f57cfdc`.

## Arquivos criados

- `app/import_base.py`: comando de importação.
- `scanner_base/{excel_reader,parser,normalizer,status,aggregator,models}.py`:
  leitura em fluxo, validação, domínio e consolidação.
- `database/repository.py` e `database/migrations/001_initial.sql`: histórico e transações.
- `services/{import_service,report_service}.py`: processamento e relatórios.
- `config/rules.json`: aliases e semântica configurável de status.
- `tests/test_scanner.py`: 48 casos executados.
- `requirements.txt`, `requirements-dev.txt`, `pyproject.toml`, `.gitignore`,
  `.dockerignore`, `Dockerfile` e `README.md`: instalação, execução e documentação.
- `data/coverage.sqlite3`: banco com duas importações reais.
- `reports/import-0001/` e `reports/import-0002/`: relatórios, lista consolidada e inconsistências.

## Limitações de negócio e escopo

As versões V10–V16, MC e observações livres precisam de confirmação de significado.
Por isso 781 veículos estão em SEM_STATUS na política conservadora atual. Os demais:
525 SUPORTADO, 13 SEM_SUPORTE, 17 EM_ANALISE e 1 SUPORTE_PARCIAL.
Suporte agregado se refere aos sistemas registrados, sem presumir cobertura integral
dos sistemas ausentes da planilha.

O Milestone 1 não coleta parceiros, executa fuzzy matching, agenda verificações
nem apresenta dashboard. Esses componentes estão descritos no roadmap do README.
O arquivo Excel não foi alterado nem incluído no pacote; pode ser importado diretamente
do caminho original ou colocado em `data/` pelo usuário.
