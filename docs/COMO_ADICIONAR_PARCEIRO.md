# Como adicionar um parceiro futuramente

Este documento descreve uma extensão futura. **Nenhum novo parceiro foi integrado
neste milestone.** A produção contém apenas WR Motos; não registre fixtures nela.

## 1. Contrato e modelo

Crie uma classe derivada de `partners.base_partner.PartnerAdapter`. Declare
`partner_key`, `display_name`, `enabled` e as capacidades `supports_images`,
`supports_price`, `supports_mileage`, `supports_zero_km`. Declare somente capacidades
realmente verificadas. `max_concurrency` deve refletir o que foi implementado.

Implemente `collect_motorcycles()`: `collect()` fornece a entrada comum e mantém
compatibilidade com os coletores anteriores. Retorne `CollectionResult` com a
origem correta. Cada `PartnerMotorcycle` deve carregar a mesma origem, ID estável,
URL de origem, nome/texto original, data de observação e metadados. Campos opcionais
podem ser `None`. Use `normalize_ad()` para normalização comum, com aliases próprios
quando necessários. Nunca deduza identidade, suporte ou zero km de fotografias.
Datas de primeira/última aparição pertencem à persistência comum, não ao transporte.

Implemente `for_pipeline(settings, config, folder)` para configurar transporte,
timeout, intervalo e evidências. O padrão apenas instancia adapters sem argumentos.
Não faça requisições em construtores, no registry ou ao consultar status.

## 2. Registro e configuração

Inclua a classe na allowlist explícita de `PartnerRegistry` e adicione uma entrada
em `config/partners.json`. Comece desabilitado, sem remover a WR. Chaves aceitam
letras minúsculas, números e underscore, começando por letra (máximo 64 caracteres).
As chaves da configuração JSON não podem se repetir. O nome do coletor aponta para
uma fábrica conhecida no código; caminhos de módulos não são aceitos.

Defina nome, habilitação, limites (`timeout_seconds`, `retries`, `delay_seconds`,
`concurrency`, `max_pages`) e `image_hosts`. Intervalo mínimo atual é 2 s; se um
site exigir mais, use o maior intervalo. A concorrência não pode superar
`max_concurrency` do adapter. O scheduler comum controla retries transitórios;
não duplique retries ilimitados no transporte.

## 3. Coleta segura e completa

Antes de uma integração real futura, valide escopo autorizado, robots, termos,
paginação, IDs e condições de completude. Não contorne bloqueios, login ou CAPTCHA.
Uma resposta vazia ou parcial não comprova estoque vazio. Use `complete=True`
apenas quando todas as páginas e categorias pertinentes estiverem verificadas.
Registre erros e evidências. HTTP 401/403/429 e bloqueios não são motivo para retry.
Nunca transforme falha em desaparecimento de anúncios.

## 4. Pipeline e persistência

Execute `run_pipeline(database, config, partner_key=..., registry=...)`.
Não crie outro pipeline nem copie regras de matching. A persistência valida a
origem, IDs presentes e duplicações. Identidade de anúncio é `(partner, external_id)`.
Não execute SQL de anúncio com `external_id` isolado.

Publicação, matching e fila são transacionais. A recuperação de execução, a chave
idempotente, o fingerprint, o histórico e os alertas têm escopo de parceiro. Uma
falha de um parceiro não deve limpar alertas ou estoque de outro. O lock de
execução e o lock de scheduler incluem a chave do parceiro. O lock de migration
permanece global. Pare processos antigos antes de trocar versões do aplicativo.

Não altere regras de decisão humana nem consolide revisões de parceiros distintos.
Novo anúncio não significa nova moto. Ausência automática não é ausência confirmada.
Desenvolvimento já permite origens múltiplas conforme suas regras de identidade;
não force consolidação de identidades ambíguas.

## 5. Imagens

Liste somente hosts efetivamente autorizados/observados em `image_hosts`.
Transporte de fotos mantém validação de URL, DNS público, redirects limitados,
assinatura raster, timeout e limites de tamanho. Preserve `partner` nas linhas
passadas a `thumbnail`, `resolve_photo` e `visible_photos`. O cache é separado por
parceiro/URL/tamanho, com quota global. Não remova o namespace legado da WR.
No desenvolvimento compartilhado, a listagem resolve a origem da foto pelas
observações armazenadas. Preserve essa associação ao estender a seleção de imagens;
não deduza origem apenas do ID ou do filtro selecionado.

## 6. Scheduler, dashboard e métricas

Use `python -m app.scheduler run-now --partner CHAVE` e `start/status/history` com
a mesma chave. O calendário é comum, o estado é separado. A enumeração dos
habilitados está em `registry.list(enabled_only=True)`; um orquestrador de vários
parceiros não está implementado. A página Parceiros e a CLI usam o registry.
`partner_status()` lê métricas sem migrar ou escrever no banco.
O comando legado `app.collect` ainda fornece opções específicas dos transportes
WR; para um adapter futuro use o pipeline comum ou estenda sua fábrica de transporte
explicitamente, sem assumir que opções WR são universais.

## 7. Testes e validação antes de habilitar

Use HTML/JSON sanitizados e bancos temporários. Veja `FakePartnerAdapter` em
`tests/test_partner_architecture.py` como exemplo local sem rede. Teste:

- duas origens com o mesmo ID; coleta completa, parcial, vazia e falha;
- config inválida, duplicada, desconhecida e desabilitada;
- retry/timeout, locks distintos e recuperação isolada;
- histórico, alertas, revisão e decisão humana sem vazamento entre origens;
- desenvolvimento com múltiplas origens e identidade incerta;
- cache/falha de imagem independente para a mesma URL;
- migrations preservando dados anteriores, dashboard e CLI em somente leitura.

Execute pytest, ruff, compileall, imports e integrity/foreign_key_check em cópia
do banco; depois confira o fluxo completo no navegador. Não escreva dados fictícios
no banco real. Uma nova integração deve ter validação e aprovação em tarefa própria.
