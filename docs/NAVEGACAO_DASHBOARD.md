# Visibilidade da navegação

A configuração central é `NAVIGATION_ITEMS`, em `ui/navigation.py`. Cada item mantém seu identificador anterior (`key`), rótulo (`label`), visibilidade (`visible`) e posição (`order`). Para reativar uma página, altere somente `visible` para `True`; ajuste `order` se necessário. Isso não altera permissões nem rotas. O identificador Estoque mantém o nome dinâmico do parceiro, como antes. Visão geral é o destino de recuperação e deve permanecer visível.

## Menu padrão

1. Visão geral
2. Indicadores gerenciais
3. Possíveis novas motos
4. Fila de revisão
5. Sem suporte
6. Suporte parcial
7. Histórico
8. Atualização automática
9. Alertas
10. Parceiros
11. Atualização da base do scanner

Estoque, Base do scanner, Busca global, Priorização operacional e Motos para desenvolvimento estão ocultos apenas no menu. Todos os handlers e componentes dessas páginas permanecem no dashboard.

## Sessão e links internos

Uma seleção de sessão oculta ou desconhecida volta para Visão geral antes da criação do widget. Uma mudança na configuração também invalida uma página interna anteriormente aberta. Links explícitos usam `request_navigation`, incluindo alertas, desenvolvimento e retorno dos links de revisão. Podem abrir páginas ocultas sem inserir opções na barra lateral. A página interna permanece durante suas interações; o botão Voltar à Visão geral ou a seleção de uma opção visível encerra essa navegação. Os parâmetros review/partner continuam intactos.

## Validação

Os testes antigos que selecionam páginas ocultas continuam executando todas as suas asserções com a fixture optativa `all_navigation`, que reativa as páginas exclusivamente naquele teste. Os novos testes usam a configuração padrão: ordem completa, terceiro item, visibilidade, sessões antigas, mudança de configuração durante a sessão, páginas ocultas, links internos e ausência de escrita nos dados. Não há detecção de ambiente de teste no código de produção.

A validação Edge/Playwright percorreu as 11 páginas visíveis, conferiu a ordem exata e não encontrou erro JavaScript ou alteração no banco temporário. Capturas em reports/navigation são evidências locais ignoradas pelo Git. Cores e layout existentes foram preservados.

Validação final em 02/10/2026: **940 testes aprovados** (922 existentes e 18 novos), em 275,86 s. Ruff, verificação de formatação e `git diff --check` aprovados.
