# Thomas: fonte autenticada e fallback manual

Sem credencial, Thomas opera por CSV/XLSX e a capacidade autenticada informa **Aguardando credencial autorizada**. A ausência de segredo não impede uso manual nem causa quebra do dashboard.

O transporte implementa GET `https://integracao.autocerto.com/api/Veiculo/ObterEstoque`, conforme [contrato oficial AutoCerto](https://integracao.autocerto.com/swagger/docs/V1), com token Bearer fornecido oficialmente. Não automatiza login. Usa timeout de 20 segundos, nenhum redirect, limite de 5 MB/5.000 registros e nenhum retry automático.

Configuração no ambiente, nunca no Git/banco:

- `THOMAS_API_TOKEN`: token autorizado da unidade correta.
- `THOMAS_AUTHORIZED=true`: confirmação da autorização de uso.
- `THOMAS_MOTORCYCLE_TYPE`: valor exato de TipoVeiculo confirmado pelo fornecedor. O contrato declara string, sem enum; não se presume que seja “Moto”.
- `THOMAS_AUTH_VALIDATED=true`: somente após auditoria humana da unidade, tipo e amostra de 10–20 registros, sem falsos positivos.
- `THOMAS_AUTOMATION_ENABLED=true`: habilita execução automática somente junto dos controles anteriores.

Token e campos de autorização/tipo selecionam a capacidade autenticada; importação manual permanece disponível. Os dois últimos controles impedem ativação automática apenas por haver token.

```console
python -m app.partners auth thomas_motos --dry-run
python -m app.partners auth thomas_motos --confirm --reviewer "Operador autorizado"
```

Dry-run consulta a fonte sem persistir. A confirmação reutiliza o importador genérico em modo incremental, com evento adicional AUTHENTICATED_COLLECTION. O histórico técnico recebe `autocerto.csv`; ausência de registros não esvazia estoque. São aceitos apenas registros com TipoVeiculo exatamente validado, Código, Marca, Modelo e AnoModelo. Outros tipos são excluídos. URLs de anúncios não são inventadas, pois não constam do contrato consultado.

Não se armazenam token, senha, cookie, placa, chassi ou Renavam. Erros de transporte são reduzidos a mensagens seguras. `FakeAuthenticatedSource` é injeção explícita de teste, nunca opção selecionável por variável de produção. Testes cobrem ausência, validade, 401/403, timeout, vazio, transporte e preservação de segredos. **Credencial e estoque reais não foram usados para validar esta implementação**; a disponibilidade efetiva da conta e o tipo oficial precisam ser verificados antes da automação.
