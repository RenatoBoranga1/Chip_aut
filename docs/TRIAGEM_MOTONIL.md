# Triagem Motonil

A categoria 65 mistura motos, kart e serviço. A coleta pública limitada existente alimenta staging e não comprova catálogo completo. Falha, bloqueio ou resposta vazia preserva dados anteriores. Não se conclui desaparecimento a partir dessa amostragem.

Em **Parceiros → Triagem Motonil**, colete para staging, selecione o item e confira título, categoria, URL e datas. Escolha Moto, Kart, Serviço, Outro ou Indefinido. Informe responsável e justificativa; para Moto, confirme marca, modelo e ano. Não há classificação por IA.

Somente `MOTORCYCLE` publica no pipeline existente. `PENDING_CLASSIFICATION`, `UNKNOWN`, `KART`, `SERVICE` e `OTHER` não entram no matching. Uma decisão é reutilizada enquanto ID e identidade observada permanecem iguais. Mudança de título, URL ou categoria invalida a decisão, retira a ocorrência ativa e exige nova revisão. A versão da linha impede que uma tela desatualizada sobrescreva outra classificação.

Reclassificar Moto para Serviço/Kart/Outro/Indefinido inativa o anúncio e invalida sua revisão ativa, mantendo histórico e decisões anteriores. Kart pode virar Moto após confirmação dos campos. Desenvolvimento não é apagado automaticamente; a manutenção de prioridades segue sua configuração existente.

```console
python -m app.partners stage motonil --dry-run
python -m app.partners stage motonil
python -m app.partners triage motonil
```

A classificação CLI aceita `--id`, `--classification`, `--revision`, `--identity` (JSON com manufacturer/model/year/version), `--reviewer`, `--note` e `--confirm`. Prefira a tela para reduzir erros de escape do shell.

`MOTONIL_AUTOMATION_ENABLED=true` permite scheduler até staging. Isso nunca autoriza classificação automática. O padrão é desligado. Fixtures de teste são explicitamente sintéticas e não representam anúncios reais; não devem ser publicadas no banco operacional.
