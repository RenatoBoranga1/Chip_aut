# Milestone 6.1.1 — Robustez e UX das miniaturas

Validação em 24/09/2026, no repositório `RenatoBoranga1/Chip_aut`, branch
`milestone-3-wr-motos-wip`. SHA inicial sincronizado:
`cbe04bee9c8ca6bb79e8059c06d166f662cbc282`.
A árvore estava limpa; fetch e pull fast-forward foram concluídos antes de editar.
O relatório `RESULTADOS_MILESTONE_6_1.md` não existia nessa referência.

## Baseline e testes

- Baseline: **559 testes aprovados**, em 135,62 s.
- Testes de imagens existentes e novos: **101 aprovados**, em 6,63 s.
- Suíte completa após implementação: **598 aprovados**, em 108,93 s.
- Validação final após ajustar o layout da fila: **598 aprovados**, em 116,19 s.
- Foram adicionados 39 casos, preservando todos os anteriores.

Os novos testes exercitam reutilização em memória/disco, faltas, TTL, falhas
temporárias, quota e remoção dos mais antigos, recuperação de corrupção e JPEG
truncado, escrita concorrente/atômica, preservação de arquivos alheios, rejeição de
links, falha de limpeza, limite de oito itens e concorrência configurada,
fallback, formatos reais versus HTML disfarçado, filtros, métricas e dashboard
somente leitura. Os testes existentes preservam histórico de troca de URL e
invariância de matching, cobertura, prioridade, decisões e alertas.

## Implementação

- Cache em `data/cache/images`, ignorado pelo Git, nomes SHA-256 compatíveis com
  a versão anterior, validade padrão de 72 horas e quota de 250 MiB.
- Limpeza automática dos expirados e depois dos mais antigos; temporários
  abandonados expiram em 60 segundos. Sem recursão, links ou exclusão fora da pasta.
- Escrita temporária exclusiva seguida de substituição atômica e bloqueio entre
  processos. Erros de disco/limpeza não interrompem o dashboard.
- Memória limitada a 256 resultados e cinco minutos; falhas aguardam 300 segundos
  para nova tentativa. Downloads simultâneos da mesma URL são deduplicados no
  processo. Até quatro downloads simultâneos, configuráveis para menos.
- Carregamento limitado aos casos relevantes nos oito itens da página de cada
  bloco. Não há carregamento antecipado de todo o catálogo.
- Fallback: miniatura, imagem principal conhecida, cópia válida anterior da mesma
  identidade, placeholder. O histórico já existente é consultado sem rematching.
- Ausência de URL e falha de carregamento têm mensagens distintas em português.
- Ampliação a 420 px opcional no detalhe; sem galeria ou coleta de página individual
  pela interface. Alertas relevantes oferecem a mesma ampliação e conservam severidade.
- Filtros Todas/Com foto/Sem foto na fila e nos grupos de possíveis novas motos.
- Listagens mais enxutas, fotos de 100–160 px; detalhes operacionais permanecem
  acessíveis na revisão. Possíveis novas motos mantém fabricante, modelo, ano,
  situação, prioridade, primeira aparição e link.
- Indicadores de URLs disponíveis/ausentes, falhas nos últimos 15 minutos e
  percentual de miniaturas efetivamente carregadas no bloco. Nenhum é cobertura.
- Duração dos lotes, downloads, reutilizações, faltas e falhas em log local com
  rotação, sem telemetria externa ou URLs. Contadores por processo.

## Segurança

Conteúdo exige magic bytes JPEG/PNG/WebP e decodificação válida. HTML, GIF e SVG
são rejeitados mesmo se anunciados como imagem. Permanecem validação HTTP/HTTPS,
origens observadas, IP público, até dois redirects, prazo padrão de três segundos,
até 5.000.000 bytes e 20 megapixels. Arquivos recebidos são convertidos em JPEG;
não são executados. O cache também é validado antes de exibir.

Não foram alterados identidade, matching, políticas de suporte/cobertura ou
prioridades. Não foram adicionadas migrations nem modificadas as anteriores.

## Validação real controlada

Não foi repetida a coleta de catálogo nem aberta página individual de anúncio.
As URLs foram recuperadas do HTML já preservado da coleta de 23/09/2026,
última observação `2026-09-23T16:09:48.721555+00:00`. Após backup SQLite, foi aplicada
a migration 010 já existente e persistidos apenas metadados/histórico de fotos,
com as datas originais, sem simular uma observação nova.

- Estoque preservado: **171 anúncios**, todos com URL de foto.
- Casos relevantes: **63 com foto informada, zero sem foto informada**.
- Fila histórica: 154 registros, dos quais 153 têm foto informada; o restante
  corresponde a anúncio fora do estoque atual, sem alterar sua pendência.
- Oito anúncios relevantes da primeira página foram usados para a medição.

| Etapa | Tempo do lote | Downloads | Reutilizações | Faltas | Falhas | Placeholders |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Primeiro carregamento | 0,9394 s | 8 | 0 | 8 | 0 | 0 |
| Repetição em memória | 0,0200 s | 0 | 8 | 0 | 0 | 0 |
| Leitura em disco após limpar só a memória | 0,0312 s | 0 | 8 | 0 | 0 | 0 |

Disponibilidade efetiva no bloco: **8/8 (100%)**. Esses tempos medem o serviço de
imagens, não a página inteira. São uma observação local, não um SLA nem uma prova
de disponibilidade de todas as 171 URLs.

Auditoria por quantidade e SHA-256 de todas as tabelas operacionais confirmou
igualdade antes/depois. Planilha original com SHA-256
`32aac84eedec3e8b34e48920bc4bf03c17ccc773886cd84490d2e6f64f57cfdc` preservado.
SQLite: `integrity_check = ok`. Evidências locais ignoradas pelo Git em
`reports/milestone-6-1-1/`: backup, auditorias, medições JSON e capturas do navegador.

## Verificação final e navegador

`ruff check .`, `ruff format --check .`, `compileall`, imports principais,
`PRAGMA integrity_check` e `git diff --check` passaram. A auditoria final após
navegação confirmou novamente todas as tabelas operacionais e a planilha intactas.

Smoke test com Playwright/Edge, servidor novo na porta 8506 em modo somente leitura:
fila com oito fotos válidas, filtros com/sem foto, ampliação real a 420 px,
três grupos de oportunidades e detalhe de alerta de alta prioridade com foto.
Ações de resolver/arquivar permaneceram desabilitadas; nenhum erro de console
ou exceção do dashboard. Foram inspecionadas capturas de fila, oportunidades,
foto ampliada e alerta. O executável agent-browser não estava disponível neste
ambiente, por isso foi usado o Playwright já instalado.

Medição complementar da navegação até imagens completas, com cache aquecido:
fila **1,170 s**, oportunidades **1,817 s**. O smoke test percorreu apenas os
primeiros blocos visíveis e um detalhe de alerta, além de uma ampliação. Ao fim
havia 18 miniaturas gerenciadas locais (incluindo a versão ampliada), sem nova
coleta do catálogo. A matriz anterior de oito fotos é a medição controlada de
downloads/reutilização; a navegação complementar não é uma segunda coleta.

Os ensaios iniciais de automação precisaram ajustar seletores e aguardar o rerender
do Streamlit; não revelaram falha do aplicativo. A inspeção visual levou à redução
das colunas da fila e à largura mínima das imagens antes da suíte final.

## Limitações

URL informada não equivale a imagem acessível; os filtros não consultam todas as
URLs. Ausência e falha foram exercitadas com fixtures, pois as oito fotos reais
carregaram. Fotos com URL inalterada dependem do TTL para atualização. O arquivo
original pode ser maior que a miniatura gerada, respeitando o teto de bytes.
O cache anterior só vale para a mesma identidade e dentro da validade; não se
buscam imagens externas. A ampliação não inventa uma variante de alta resolução.
Concorrência/memória e indicadores são por processo. Arquivos alheios à política
de nomes são preservados e não entram na quota. As proteções de links/junctions
foram testadas por simulação, sem exigir privilégio de criação no Windows.

O comportamento observado anteriormente dos filtros 0 km permanece documentado
e não é reinterpretado por imagens. Dados, HTML, planilhas, logs e fotos não são
enviados ao Git. Não há merge em `main` nesta entrega.

## Arquivos principais

`services/vehicle_image_cache.py`, `services/vehicle_image_metrics.py`,
`services/vehicle_images.py`, `services/vehicle_image_config.py`,
`config/vehicle_images.json`, `database/vehicle_images.py`,
`services/dashboard_service.py`, `ui/vehicle_images.py`, `ui/alert_panel.py`,
`app/dashboard.py`, `tests/test_vehicle_image_robustness.py` e `README.md`.
