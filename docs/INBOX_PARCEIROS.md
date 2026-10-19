# Inbox dos parceiros

Configure `THOMAS_INBOX_PATH` e `MOTO_MARQUES_INBOX_PATH` no ambiente do processo. Caminhos relativos são resolvidos a partir da pasta de execução; recomenda-se iniciar na raiz do projeto. Não há diretório absoluto embutido. Sem configuração, a inbox informa configuração pendente e não lê outras pastas.

Copie CSV/XLSX autorizado para a pasta correspondente. O sistema não move, exclui ou arquiva o original. `partner_inbox/`, relatórios e bancos são ignorados pelo Git; pastas externas continuam sob responsabilidade do operador.

## Fluxo

**Detectado → Validando → Arquivo aguardando confirmação → Importado ou Rejeitado.** Arquivos inválidos e duplicados ficam identificados separadamente. Um scan nunca publica estoque. A revisão apresenta arquivo, hash, data, abrangência, contagens, comparação e anomalias.

O hash SHA256 é calculado sobre o conteúdo lido, com limite de 10 MB. A identidade é parceiro + nome + hash; cópias do mesmo conteúdo dentro de um parceiro são duplicadas. Conteúdo já publicado pelo importador M8.4 também é reconhecido. Repetir o scan não cria prévias nem eventos novos para o mesmo arquivo inalterado. Arquivo alterado gera outra entrada; a antiga permanece no histórico.

CSV usa UTF-8 e parsing estrito. XLSX é aberto sem executar macros, fórmulas são rejeitadas e o volume descompactado é limitado. Arquivo vazio, malformado, sem identidade mínima ou com encoding inválido não interrompe os demais arquivos. Arquivos grandes/indisponíveis têm erro de metadados separado, sem hash de conteúdo inventado. São tentados novamente quando os metadados mudam.

A pasta é plana: subpastas e links simbólicos são ignorados. Nomes não podem atravessar diretórios. A confirmação resolve novamente o caminho dentro da inbox configurada e relê bytes/hash. Um arquivo mudando durante a leitura é rejeitado até estabilizar.

## Comparação e anomalias

O estoque ativo consolidado é a referência válida anterior, incluindo importações incrementais já confirmadas. A prévia classifica IDs em novos, alterados, mantidos e ausentes; inválidos são contados à parte. Preço, versão, ano, fabricante, modelo, km e URLs participam da comparação. Sem código nativo/URL estável, IDs de linha só são estáveis no mesmo arquivo; a prévia alerta essa limitação.

Configuração em `config/partner_operations.json`, substituível com `MOTO_PARTNER_OPERATIONS_CONFIG`:

- redução superior a 50% da quantidade anterior: Atenção;
- 90% ou mais dos IDs entrantes são novos: Atenção;
- 20% ou mais das linhas inválidas: Atenção;
- ausência de linhas válidas ou FULL_SNAPSHOT com inválidas: Bloqueio;
- ausência em arquivo incremental: Informação, sem retirar anúncio.

Os limiares são configuráveis. Atenção exige reconhecimento explícito das anomalias, não aprovação automática. FULL_SNAPSHOT preserva a regra M8.4: somente retrato completo válido e confirmado retira ausentes. INCREMENTAL preserva ausentes.

## Revisão e confirmação

Em **Parceiros → Caixa de entrada — operação assistida**, verifique pastas, abra a inbox do parceiro e escolha o arquivo. Ajuste nomes de colunas e abrangência se necessário e valide novamente. Trocar modo ou mapeamento desabilita a confirmação da prévia anterior.

Informe responsável, confira origem/unidade, motocicletas e anomalias. **Confirmar importação da inbox** usa o importador e matching existentes. A revisão e a publicação são transacionais: falha no matching mantém a inbox pronta e o estoque anterior. Hash alterado, revisão antiga ou estoque atualizado desde a prévia bloqueiam confirmação. Rejeitar exige confirmação, responsável e motivo; preserva o arquivo.

```console
python -m app.partners inbox scan
python -m app.partners inbox scan --partner thomas_motos
python -m app.partners inbox list
python -m app.partners inbox show 1
python -m app.partners inbox validate 1 --revision 2 --mode FULL_SNAPSHOT
python -m app.partners inbox confirm 1 --revision 3 --preview-hash HASH_EXIBIDO --reviewer "Operador" --confirm --authorized --motorcycles --accept-anomalies
python -m app.partners inbox reject 2 --revision 2 --reviewer "Operador" --reason "Exportação errada" --confirm
```

Use `--db` para uma cópia de validação. Validação pode receber `--mapping perfil.json`, no formato campo interno → coluna. List/show são somente leitura. `MOTO_READ_ONLY=1` bloqueia scan, validação persistida, confirmação e rejeição.

## Polling, recuperação e limites

O scheduler existente chama a preparação, respeitando `scan_interval_minutes` por parceiro (padrão 30). `run-now --partner thomas_motos`/`moto_marques` prepara a inbox configurada; isso não liga coleta autenticada nem publicação. `run-all` inclui uma operação `partner_inbox` se houver inbox configurada. O processo contínuo só existe quando o operador inicia o scheduler.

Locks da inbox são separados por parceiro; confirmação também usa o lock do pipeline e a transação SQLite. Estados Detectado/Validando são retomados no próximo scan. Metadados tamanho/mtime/ctime evitam reabrir arquivos conhecidos; confirmação sempre relê o hash. Limite de 100 arquivos novos/alterados por passagem; o próximo polling continua o trabalho. A tela e CLI listam os 200 registros mais recentes; IDs conhecidos continuam consultáveis individualmente. Pastas com muitos arquivos devem ser mantidas sob controle do operador, sem exclusão automática.
