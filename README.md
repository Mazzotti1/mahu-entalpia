# Carta Psicrométrica ASHRAE

Simulador psicrométrico com carta ASHRAE desenhada em Canvas, cálculos no backend via
psychrolib e leitura do monitor MAHU por OCR a partir de uma foto.

- **Backend:** Python 3.11 + FastAPI + SQLite (aiosqlite) + psychrolib + easyocr
- **Frontend:** React 19 + TypeScript + Vite + Zustand + Axios + Tailwind CSS

## Rodando com Docker (recomendado)

Requer Docker com Compose v2.

```bash
docker compose up --build
```

- Aplicação: <http://localhost:8080>
- Swagger da API: <http://localhost:8000/docs>

O nginx serve o build do frontend e faz proxy de `/api` para o backend, então tudo roda na
mesma origem e não há CORS envolvido.

### Variáveis e portas

| Variável | Padrão | Para quê |
|:--|:--|:--|
| `CARTA_PORT` | `8080` | Porta do host para a aplicação |
| `CARTA_API_PORT` | `8000` | Porta do host para a API (Swagger) |
| `CARTA_CORS_ORIGINS` | vazio | Origens extras de CORS, separadas por vírgula, para quem chamar a API direto |
| `TORCH_INDEX_URL` | índice CPU-only da PyTorch | Índice do pip para o torch (veja abaixo) |

### Tamanho da imagem do backend

O `easyocr` depende do `torch`, e o wheel padrão do PyPI para linux/amd64 embute o runtime
CUDA inteiro (cuDNN, cuBLAS, NCCL, Triton…). O build sai assim:

| Wheel do torch | Imagem do backend |
|:--|--:|
| índice CPU-only (padrão daqui) | 2,05 GB |
| padrão do PyPI, com CUDA | 8,62 GB |

Os 6,5 GB extras nunca são usados: `backend/services/mahu_ocr.py` instancia o leitor com
`gpu=False`. Por isso o build aponta o torch para o índice CPU-only por padrão. Para voltar
às wheels com CUDA (só faz sentido junto com uma mudança para `gpu=True`):

```bash
TORCH_INDEX_URL= docker compose build
```

### Dados persistidos

Dois volumes nomeados, então `docker compose down` não perde nada:

- `carta-db` → `/data/simulador.db`, o banco SQLite das simulações
- `easyocr-models` → `/models/easyocr`, os ~80 MB de modelos que o easyocr baixa na
  primeira leitura

Para zerar tudo: `docker compose down -v`.

## Rodando sem Docker

Requer Python 3.11+ e Node 20.19+.

1. Backend:

```bash
python -m pip install -r backend/requirements.txt
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

2. Frontend, em outro terminal:

```bash
cd frontend
npm install
npm run dev
```

A aplicação abre em <http://localhost:5173>. O dev server do Vite faz proxy de `/api` para
`http://127.0.0.1:8000` — aponte para outro backend com `VITE_API_PROXY_TARGET`.

## Estrutura

```
backend/
├── main.py                    # FastAPI + CORS
├── database.py                # SQLite (CARTA_DB_PATH define o caminho)
├── migrations.py              # Schema versionado por PRAGMA user_version
├── models.py                  # Schemas Pydantic
├── routes/pontos.py           # Endpoints
├── services/
│   ├── psicrometria.py        # Cálculos via psychrolib
│   ├── mahu.py                # Mapeamento campos do painel -> P1..P4
│   ├── mahu_campos.py         # Metadados dos campos: casas decimais e faixas
│   ├── mahu_parse.py          # Texto do OCR -> valor (puro, sem OpenCV)
│   ├── mahu_validacao.py      # Coerência entre campos da leitura
│   ├── mahu_ocr.py            # Alinhamento, recorte das ROIs e OCR
│   ├── telemetria_ocr.py      # Sugerido vs aplicado, e a foto
│   └── eventos.py             # Difusor em memória que alimenta o SSE
├── tests/                     # pytest (pip install -r requirements-dev.txt)
├── assets/
│   └── mahu_template.png      # Gabarito canônico do painel (1200x480)
└── Dockerfile

docs/fotosMahu/                # Conjunto de teste do OCR + ground_truth.json
```

Os três módulos `mahu_campos` <- `mahu_parse` <- `mahu_ocr` são separados de propósito:
os dois primeiros não dependem de OpenCV nem do easyocr, e é o que permite rodar a suíte
sem instalar o ambiente completo (~2 GB por causa do torch).

```
scripts/
├── avaliar_ocr.py             # Acerto contra as fotos com ground truth
└── relatorio_telemetria.py    # Acerto contra as correções feitas em produção
scripts/avaliar_ocr.py         # Mede a acurácia contra o ground truth

frontend/
├── src/
│   ├── chart/                 # Motor de desenho da carta (sem React)
│   │   ├── config.ts          # Escalas e limites
│   │   ├── draw.ts            # Camadas e ordem de renderização
│   │   ├── interaction.ts     # Ponteiro -> estado psicrométrico
│   │   └── layers.ts          # Camadas que o painel liga/desliga
│   ├── components/            # Componentes de UI
│   ├── hooks/useCamera.ts     # Ciclo de vida do getUserMedia
│   ├── lib/
│   │   ├── http.ts            # Instância do axios + tradução de erro do FastAPI
│   │   ├── psicrometria.ts    # Fórmulas locais (desenho e indicador)
│   │   └── format.ts
│   ├── services/              # Chamadas à API
│   ├── store/                 # Zustand: useChartStore, useMahuStore, useHistoricoStore
│   └── types/                 # Espelho dos schemas da API
├── nginx.conf
└── Dockerfile
```

### Onde cada cálculo acontece

As propriedades dos pontos do processo (tabela e posição na carta) vêm sempre do backend,
que usa psychrolib. As fórmulas em `frontend/src/lib/psicrometria.ts` servem só para
desenhar as isolinhas e alimentar o indicador que segue o cursor — as duas coisas fazem
milhares de avaliações por quadro e não podem ir à rede.

## Lendo no celular, vendo no PC

Toda leitura é persistida, então os dispositivos já compartilham os dados — não há
pareamento, sessão nem QR envolvido. O PC simplesmente acompanha a leitura mais recente:

1. `GET /api/simulacoes` devolve o histórico, da mais recente para a mais antiga
2. `GET /api/simulacoes/stream` (SSE) empurra cada leitura nova assim que ela é gravada
3. Chegando uma leitura nova — de qualquer dispositivo — a carta troca sozinha, na hora

### Como o tempo real funciona

O aviso nasce em `backend/services/eventos.py`: um difusor em memória que
`_persistir_simulacao` aciona **depois do commit** — antes disso quem recebesse o aviso
consultaria uma linha que ainda não existe. Cada conexão SSE tem sua própria fila limitada,
então um cliente que parou de consumir não segura memória sem teto.

Três detalhes sustentam a conexão na prática:

- **`Last-Event-ID`**: o `id:` de cada evento é o id da simulação. Ao reconectar, o
  navegador devolve o último que recebeu e o servidor reenvia o que ficou para trás (até
  `MAX_CATCH_UP`). É o que cobre o celular trocando de Wi-Fi para 4G.
- **Keepalive a cada 25 s**: um comentário SSE mantém a conexão viva através de proxies que
  derrubam conexões ociosas. Precisa ser menor que o `proxy_read_timeout` do nginx.
- **Sem buffer**: a rota manda `X-Accel-Buffering: no` e o `location /api/` tem
  `proxy_buffering off`. Sem isso o nginx segura os eventos e entrega em blocos, o que
  anula o ganho.

A aba escondida fecha a conexão e reabre ao voltar, para não gastar bateria no celular. Se
o `EventSource` desistir (`readyState === CLOSED`), o front cai sozinho para uma sondagem de
4 s — o ponto colorido ao lado de "Acompanhando a leitura mais recente" mostra qual dos dois
está em uso: verde para SSE, âmbar para a sondagem de reserva.

**Isso vale enquanto o uvicorn rodar com um worker só.** O difusor é local ao processo, então
com `--workers 2` cada worker só saberia das próprias escritas e um cliente perderia metade
dos eventos. Nesse dia, a troca é o difusor por um pub/sub externo (Redis) — a interface de
`DifusorSimulacoes` já é a que um adaptador desses precisaria.

Escolher uma leitura antiga na lista desliga o acompanhamento automático, e o botão
**Voltar para a mais recente** religa. É o mesmo comportamento de um visualizador de log
que segue o fim do arquivo até você rolar para cima.

Isso funciona para uma pessoa lendo por vez. Se dois técnicos passarem a ler painéis
diferentes ao mesmo tempo, o PC mostrará a leitura que chegou por último, seja de quem for —
aí sim seria preciso pareamento por sessão.

Uma consequência de o histórico ficar visível: a página **não** grava mais uma simulação a
cada carregamento. No boot ela adota a leitura mais recente que já existir, e só cria a
simulação de exemplo se o banco estiver vazio.

### Câmera no celular exige HTTPS

`getUserMedia` só funciona em contexto seguro. Acessando o app pelo IP da rede local
(`http://192.168.x.x:8080`) o modal de câmera **não abre** — o fluxo cai no seletor de
arquivos, que no celular abre a câmera nativa e ainda funciona, mas sem a moldura-guia.
Para a câmera dentro do app é preciso HTTPS num domínio de verdade.

## Leitura do monitor MAHU pela câmera

O botão **Capturar monitor MAHU** abre a câmera no navegador, captura o quadro e envia a
imagem para `POST /api/mahu/ler`. O backend recorta os campos do painel, roda OCR e devolve
cada valor com sua confiança. A carta só é redesenhada depois que os valores são confirmados
no formulário de conferência, via `POST /api/mahu/simulacao`.

Observações práticas:

- A primeira leitura baixa os modelos do easyocr (~94 MB) e a primeira depois de cada
  restart os carrega na RAM (~6 s). Medido em CPU: **2,1 s** por leitura com 6 núcleos,
  **6,8 s** com 2 vCPU, **15 s** com 1 vCPU.
- A interface mostra barra de progresso real durante o upload e o tempo decorrido durante a
  leitura. No celular em 4G o upload costuma ser a parte mais demorada, não o OCR.
- `getUserMedia` exige contexto seguro: `http://localhost` e HTTPS funcionam. Se a câmera
  não estiver disponível, o fluxo cai no seletor de arquivos, que no celular abre a câmera
  nativa.
- Para testar pelo celular na rede local, sirva o frontend pelo IP da máquina. Chamando a
  API direto (sem o nginx), acrescente a origem em `CARTA_CORS_ORIGINS`.

### Mapeamento dos campos do painel para os pontos

Definido em `backend/services/mahu.py`:

| Ponto | Estado | Campos do MAHU |
|:--|:--|:--|
| P1 | ar de retorno | TT01 (°C) + MT_01 (%) |
| P2 | saída da serpentina, saturada | TT_04 (°C) + UR fixada em 100% |
| P3 | ar resfriado saturado | TT_06 (°C) + UR fixada em 100% |
| P4 | ar de insuflamento | TT07 (°C) + MT07 (%) |

`PID UMD ABS PV` e `PID TT04 ENTALPIA PV` são lidos apenas como conferência e não entram
no cálculo.

Dois pontos merecem atenção de quem for mexer nisso:

- **P2 não usa a entalpia.** A entrada do planejamento (`docs/planejamento tecnico.md` §4 e
  §6: TBS 12,20 com h = 36,20 kJ/kg) é termodinamicamente impossível: exigiria W = 9,48 g/kg
  contra W_sat(12,20 °C) = 8,85 g/kg, ou seja UR de 107%. A API rejeita essa combinação com
  HTTP 400. A tabela do §6 é inconsistente consigo mesma, pois declara W = 9,48 g/kg **e**
  UR = 87,03%, que não coexistem. Como o ar de P1 tem ponto de orvalho de 13,2 °C, ao ser
  resfriado até 12,20 °C ele já condensa e sai sobre a curva de saturação — daí P2 = TT_04
  com UR de 100%.
- **P4 usa MT07 e não `PID UMD ABS PV`.** Os dois descrevem o mesmo estado (7,30 g/kg
  equivale a ~46,5% a 21,2 °C), mas `PID UMD ABS PV` fica num bloco de três linhas
  (SP/PV/MV) com 17 px entre elas no espaço canônico. A folga necessária para tolerar o
  erro da retificação invade a linha vizinha, e o OCR poderia passar a ler o setpoint como
  se fosse o valor de processo. MT07 é fonte grande e isolada.

### Como a imagem é normalizada

`backend/services/mahu_ocr.py` mede as ROIs num espaço canônico de 1200 × 480 (a proporção
2,5:1 da tela). Para que essas coordenadas fixas signifiquem alguma coisa, a foto precisa
antes cair exatamente nesse espaço — é o que o alinhamento faz, em três níveis de fallback:

1. **Homografia contra o gabarito** (`backend/assets/mahu_template.png`). O painel é uma
   tela de software fixa: o desenho — dutos, ventiladores, válvulas, rótulos — é idêntico em
   qualquer foto e só os números mudam. Casando ~1000 pontos SIFT entre a foto e o gabarito,
   enquadramento, escala e perspectiva são resolvidos de uma vez.
2. **Quadrilátero da tela**, se a homografia não convergir: procura a tela no quadro,
   inclusive o quadrilátero *aninhado* quando existe (a tela dentro da moldura do monitor).
3. **Redimensionamento cru**, assumindo que a foto já é a tela.

O nível 1 é o que faz a coisa funcionar na prática. Os níveis 2 e 3 assumem que a foto
enquadra a tela inteira, e essa premissa quebra assim que o enquadramento varia — foto
cortada de um lado, ou incluindo a barra de abas acima da tela. Medido sobre
`docs/fotosMahu/`, o pipeline sem alinhamento acertava **9 de 47** campos obrigatórios;
com alinhamento, **39 de 47**.

Cada campo é lido em 5 variantes de pré-processamento e o valor vence por votação. Como o
painel sempre mostra duas casas decimais, uma leitura sem separador é reconstruída
("870" → 8,70), mas nunca recebe status `ok`: `220` e `2120` reconstroem para 2,20 e 21,20,
ambos plausíveis para uma temperatura, e só quem olha a foto sabe qual é. Por isso a
conferência manual existe.

**A métrica que importa não é a acurácia, é o número de erros silenciosos** — leituras
erradas marcadas como `ok`, que entrariam no cálculo sem passar pela conferência. Sobre o
conjunto atual esse número é **zero**: todos os 8 campos errados saíram como
`low_confidence` ou `unreadable`.

### Medindo o OCR

```bash
docker compose run --rm \
    -v "$PWD/docs:/docs" -v "$PWD/scripts:/scripts" \
    backend python /scripts/avaliar_ocr.py /docs/fotosMahu
```

Os valores reais de cada foto ficam em `docs/fotosMahu/ground_truth.json`, transcritos à
mão. Ao acrescentar fotos, acrescente a entrada correspondente — sem ground truth correto a
medição não vale nada. O script sai com código 1 se aparecer qualquer erro silencioso.

### Limite de resolução

A acurácia cai abaixo de ~1200 px de largura na foto original. No conjunto atual, todas as
fotos de 1260 px ou mais acertaram os 6 campos; `6.jpg` (1144 px) errou 2 e `8.jpg` (884 px)
não leu nenhum. Foto de celular moderna tem 3000–4000 px, então na prática isso só é um
problema se a imagem for reduzida antes do envio — o que o frontend não faz.

### Ao mexer nas ROIs

Meça sobre imagens **já alinhadas**, nunca sobre fotos cruas. As ROIs atuais são a união das
caixas de texto detectadas em 9 imagens alinhadas, mais 3 px de margem. Antes do alinhamento
elas precisavam de folga generosa para absorver a variação de enquadramento, e essa folga
fazia o recorte engolir a unidade da linha de baixo — `12,20` mais `°C` vira lixo no OCR.

Vale saber que pular a detecção de texto (`readtext` → `recognize`, já que a ROI é
conhecida) deixa a leitura 5× mais rápida e **quebra a acurácia**: a rede de detecção acha
os limites exatos do texto dentro do recorte, e sem ela o reconhecedor lê as bordas junto.
Medido: `MT07` passou a ler 74,48 em vez de 46,48.
