# Modelos de Base de Conhecimento (KB)

Esta pasta contém **arquivos modelo** para você estruturar a Base de Conhecimento da sua
empresa. A plataforma **não vem com nenhum conteúdo padrão**: cada organização carrega os
próprios dados.

Pense nestes arquivos como o equivalente do `.env.example` para o conteúdo do atendimento —
eles mostram a *estrutura esperada*, sem dados reais de ninguém.

## Para que serve a Base de Conhecimento

O agente de IA responde com precisão sobre horários, produtos, preços e políticas **apenas
com o que estiver na Base de Conhecimento** (e na identidade configurada em Configurações).
Quando a informação não está no KB, o agente diz que não sabe — ele não inventa preço,
prazo ou política. Por isso, quanto mais completo e bem estruturado o seu KB, melhor o
atendimento.

> **Identidade ≠ Base de Conhecimento.** O *nome da empresa*, o *tom de voz* e o *contexto
> do negócio* são configurados em **Configurações → Identidade da empresa** (e, opcionalmente,
> por agente). A Base de Conhecimento guarda os **fatos**: preços, horários, políticas, FAQ.

## Como usar

1. **Copie** os arquivos desta pasta para um local de trabalho seu (fora do repositório).
2. **Preencha** cada arquivo substituindo os placeholders entre colchetes — por exemplo
   `[NOME DA EMPRESA]`, `[HORÁRIO]`, `[VALOR]` — pelos dados reais da sua empresa. Apague as
   linhas que começam com `#` (são comentários de orientação) e qualquer bloco que não se
   aplique ao seu negócio.
3. **Carregue** cada arquivo pelo painel: **Dashboard → Conhecimento → Upload** (ou
   **Texto manual**, colando o conteúdo). Dê um **título descritivo** a cada documento
   (ex.: "Preços e planos", "Política de trocas").
4. O sistema processa o arquivo, divide em trechos e indexa para busca. Quando o status
   ficar **READY**, o conteúdo já alimenta as respostas do agente.

## Formatos aceitos

- `.txt` (UTF-8) — **recomendado**, é o que melhor casa com o processamento.
- `.pdf`
- `.docx`

Não são aceitos `.md`, `.csv` ou `.doc`. Se você editar em Markdown, **salve/renomeie como
`.txt`** antes de carregar (o sistema trata o conteúdo como texto puro, sem formatação).

## Como escrever para um bom resultado

O sistema divide o texto em **trechos** usando a **linha em branco** como separador
principal. Para que cada fato seja encontrável de forma precisa:

- **Separe cada assunto por uma linha em branco.** Cada bloco vira uma unidade de busca.
- **Um fato por bloco**, escrito de forma autoexplicativa (quem lê o bloco isolado entende).
- **Prefira blocos com algumas frases** (≈ 200 caracteres ou mais). Blocos muito curtos
  podem ser descartados no processamento.
- **Comece o bloco com o assunto em destaque** (ex.: `HORÁRIO DE ATENDIMENTO`) seguido das
  informações — isso ajuda tanto a busca quanto a leitura.
- **Não cole o texto inteiro num parágrafo só**, sem quebras: o sistema teria dificuldade
  para separar os fatos.

## Um arquivo por tema

Recomendamos manter um arquivo (e um documento no painel) por tema, para organização e para
facilitar atualizações. Os modelos sugeridos:

| Arquivo | Conteúdo |
| --- | --- |
| `01-identidade-e-contato.txt` | Quem é a empresa, horários, canais e formas de contato |
| `02-produtos-e-servicos.txt` | O que a empresa oferece, descrições e diferenciais |
| `03-precos-e-planos.txt` | Valores, planos, condições e descontos |
| `04-politicas-comerciais.txt` | Troca, cancelamento, reembolso, garantia, privacidade |
| `05-frete-e-entrega.txt` | Regiões, custos, prazos de entrega ou de implantação |
| `06-suporte-e-escalonamento.txt` | Canais de suporte, SLA e quando falar com um humano |
| `07-faq-atendimento.txt` | Perguntas frequentes e respostas curtas |

Use só os que fizerem sentido para o seu negócio. Uma loja física dá ênfase a frete e
endereço; um SaaS, a planos e implantação. Adapte à vontade.

## Importante

- **Não comite dados reais da sua empresa** neste repositório. Estes modelos são genéricos
  de propósito; o conteúdo preenchido é seu e privado.
- O conteúdo que você carrega pelo painel fica **restrito à sua conta** (não é compartilhado
  com outros usuários da plataforma).
- Evite colocar **preços ou políticas na identidade** (Configurações) — esses fatos devem
  morar na Base de Conhecimento, que é a fonte oficial para o agente.
