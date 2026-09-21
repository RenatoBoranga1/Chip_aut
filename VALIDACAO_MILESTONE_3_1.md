# Validação técnica — Milestone 3.1

Continuação de f87816e em milestone-3-wr-motos-wip. Windows/Python 3.14.7.
Os 153 testes anteriores passaram antes das alterações e foram preservados.
Validação final: **220 testes aprovados**, Ruff lint e format (54 arquivos),
compileall e imports aprovados. SQLite: integrity_check `ok`, nenhuma violação
de foreign key. Hashes das tabelas de origem/histórico e da planilha permaneceram
iguais; nenhuma decisão manual foi adicionada. Todos os vínculos exatos anteriores
mantiveram sua chave original.

## Escopo

- Equivalências explícitas e ruído configuráveis, com evidência por regra.
- Visão canônica separada dos dados originais e da chave de memória manual.
- Detecção de colisões e proteções adicionais de versões, sem fuzzy automático.
- Inventário offline, comparação com baseline persistido e efeito por regra.
- Diagnóstico de ano/grafia/versão; lista conservadora de provável ausência.
- Nenhuma mudança da planilha, dados importados, coleta ou condição 0 km.

## Comandos

```powershell
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
python -m compileall -q app scanner_base matching database services partners
python -c "import app.refine, app.coverage, app.collect, matching.identity, matching.matcher, services.refinement_service, services.matching_service, database.matching_repository"
python -m app.refine 2 --baseline-coverage 1
```

A suíte inclui teste positivo e negativo para cada regra, todos os tokens de
proteção adicionados, configuração inválida, aliases entre fabricantes, colisões,
restrição de ano, contexto da memória, ausência conservadora, identidade incompleta,
ablação das regras e recusa de baseline de outra versão da base.
Os testes usam dados sintéticos e não dependem da rede.

## Evidências operacionais locais

- `reports/refinement/REFINAMENTO.md`: antes/depois e alterações explicadas.
- `reports/refinement/inventory.json`: todos os anúncios, diagnósticos e políticas.
- `reports/refinement/probable_absence.json`: provável lacuna por identidade/ano.
- `reports/refinement/coverage/`: cobertura recalculada mantendo candidatos separados.
- `reports/refinement/validation.json`: testes, integridade SQLite, hashes antes/depois.

Banco, relatórios reais e evidências não são versionados. A comparação utiliza
a mesma coleta e a mesma versão da base, sem nova coleta, nova importação ou
decisões manuais simuladas. Hashes das tabelas de origem, histórico de coleta,
memória e planilha são comparados antes/depois. Novos matching_runs e coverage_runs
são intencionais; nenhum resultado histórico é sobrescrito.

## Decisões e limites

Nenhuma equivalência entre anos ou remoção de ABS/Adventure/Touring é habilitada.
Omissão de cilindrada não é preenchida. Termos vagos de publicidade não são removidos
sem evidência; apenas frases delimitadas e conhecidas entram nas regras.
Scores fuzzy não são probabilidades e os pesos continuam os anteriores. Experimentos
de sensibilidade constam no inventário; sem conjunto rotulado, não medem precisão.

Uma equivalência exata configurada é diferente de aceitar o candidato de maior score.
Todos os candidatos fuzzy continuam sem vínculo automático. A categoria de provável
ausência é uma hipótese sobre a planilha, não uma atribuição de status SEM_SUPORTE.
Casos ambíguos e variantes não comprovadas continuam dependentes de revisão humana.
Não foram executados Docker/Python 3.12, dashboard ou agendamento.
