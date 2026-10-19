# Modos operacionais — M8.4

O cadastro operacional em `partners/integration.py` complementa o registro de collectors públicos. Uma avaliação histórica de scraping reprovada não impede a importação autorizada de um parceiro.

| Parceiro | Modo padrão | Situação | Automação |
|---|---|---|---|
| WR Motos | PUBLIC_COLLECTION | Ativo automático | Coletor existente preservado |
| Thomas Motos | FILE_IMPORT | Ativo manual | Auth opcional, mediante configuração validada |
| Motonil | STAGED_COLLECTION | Ativo com triagem | Opcional até staging; decisão sempre humana |
| Moto Marques Multimarcas | FILE_IMPORT | Ativo manual | Não executa coleta direta |

`enabled` significa que existe um canal operacional. `automation_enabled` controla execução sem intervenção; não transforma importação manual em coleta. As capacidades declaram origem, autenticação, triagem, scheduler e importação. Nenhum segredo integra esses metadados. A data de validação refere-se à implementação; não comprova credencial ou estoque real do parceiro.

A migração 015 acrescenta histórico de importações, perfis de colunas, staging, eventos imutáveis e alertas deduplicados. A publicação usa PartnerVehicleAd, normalização, matching e revisão existentes. Identidades consolidadas mantêm múltiplas origens; não criam ScannerVehicle ou DevelopmentItem automaticamente. Priorização respeita a manutenção previamente habilitada.

`run-all` mantém WR e acrescenta somente fontes operacionais com automação explicitamente habilitada. FILE_IMPORT é ignorado. Motonil depende de `MOTONIL_AUTOMATION_ENABLED=true`; Thomas exige os controles descritos em [autenticação](THOMAS_AUTHENTICATED_SOURCE.md). O scheduler reutiliza frequência e locks existentes. Não há agendamento contínuo iniciado pela instalação.

```console
python -m app.partners status
python -m app.scheduler run-all --json
python -m app.scheduler run-now --partner motonil
```

Parceiros reúne importação, triagem e histórico. Alertas e Indicadores mostram pendências operacionais separadas da avaliação histórica de fontes. O Assistente de IA consulta esses dados somente em leitura. `MOTO_READ_ONLY=1` permite preview e bloqueia publicação/classificação.
