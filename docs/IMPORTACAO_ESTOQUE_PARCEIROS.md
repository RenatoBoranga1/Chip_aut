# Importação de estoque

Em **Parceiros**, abra Thomas Motos ou Moto Marques, baixe o modelo CSV, selecione CSV/XLSX e confira o mapeamento. Marca, modelo e ano são obrigatórios. Código de estoque, versão, preço, quilometragem, URL do anúncio e URL de imagem completam o modelo.

O upload não publica dados. **Validar e pré-visualizar** mostra contagens e até 20 linhas. Informe responsável, confirme origem/unidade e que as linhas válidas são motocicletas; então use **Confirmar importação**. O perfil de colunas é salvo por parceiro após confirmação. Alterar arquivo, mapeamento ou abrangência exige nova prévia.

- **Incremental**: atualiza linhas válidas e preserva anúncios ausentes; linhas inválidas ficam fora da publicação e geram alerta.
- **Retrato completo (FULL_SNAPSHOT)**: exige todas as linhas válidas, pelo menos uma linha e IDs estáveis. Ausentes ficam inativos; histórico é preservado. A confirmação abrange essa retirada.

Prefira sempre código nativo de estoque. Sem código, usa-se URL informada; sem ambos, hash do arquivo e número da linha. Esse último recurso é estável somente ao repetir o mesmo arquivo. Alterar o arquivo sem códigos/URLs pode criar outra ocorrência; por isso FULL_SNAPSHOT recusa IDs derivados de linha.

A repetição do mesmo conteúdo, mapeamento e modo para o mesmo parceiro reutiliza a importação. CSV e XLSX equivalentes podem ter hashes diferentes, mas códigos de estoque iguais atualizam o anúncio existente. Histórico guarda nome simples, hash, contagens, responsável, ação e status; nunca o caminho local. Falhas de matching revertem a publicação. Alertas de falha/linhas inválidas são deduplicados. A pendência do primeiro arquivo é derivada em leitura, sem gravar eventos ao abrir a tela.

Limites: 10 MB por arquivo, 5.000 linhas, 100 colunas; XLSX descompactado até 50 MB. Fórmulas são rejeitadas. CSV usa UTF-8, com vírgula, ponto e vírgula ou tabulação. Preço aceita ponto ou vírgula decimal, sem separador de milhares; quilometragem deve ser inteira não negativa. URLs são opcionais e devem ser HTTPS públicas, sem credenciais. Imagens não são baixadas pelo importador.

```console
python -m app.partners import thomas_motos estoque.csv --dry-run
python -m app.partners import moto_marques estoque.xlsx --dry-run
python -m app.partners import thomas_motos estoque.csv --confirm --authorized --motorcycles --reviewer "Operador"
```

Use `--db` para escolher uma cópia de validação; o padrão é `MOTO_DB` ou `data/coverage.sqlite3`. `--mapping perfil.json` recebe objeto campo interno → nome da coluna. `--mode FULL_SNAPSHOT` seleciona retrato completo. Dry-run não cria banco nem altera dados. Testes geram fixtures sintéticas CSV/XLSX e verificam publicação, matching, revisão, dedupe e rollback.

## Inbox — M15

Arquivos disponibilizados em pasta configurada podem ser detectados e preparados automaticamente. A revisão acrescenta comparação e anomalias, e bloqueia confirmação se hash, revisão ou estoque mudou. A importação confirmada reutiliza este mesmo serviço transacional. [Configuração e uso](INBOX_PARCEIROS.md).
