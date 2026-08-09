# Carta Psicrométrica ASHRAE

Simulador psicrométrico com carta ASHRAE desenhada em Canvas, cálculos no backend via
psychrolib e leitura do monitor MAHU por OCR a partir de uma foto.

- **Backend:** Python 3.11 + FastAPI + SQLite (aiosqlite) + psychrolib + easyocr
- **Frontend:** React 19 + TypeScript + Vite + Zustand + Axios + Tailwind CSS

## Autenticação

A aplicação inteira exige login. O banco sobe com a conta de instalação **`admin` / `admin`**,
semeada pela migração 8, para que o primeiro acesso seja possível.

> **Essa senha é pública.** O hash está no código-fonte deste repositório. Ela existe para
> ser trocada na primeira subida, e enquanto não for a API grita um aviso no log a cada
> boot. Em produção, os dois comandos abaixo são o primeiro passo depois do deploy.

```bash
docker compose -f docker-compose.server.yml exec backend \
  python -m scripts.criar_usuario renomear admin roberto
docker compose -f docker-compose.server.yml exec backend \
  python -m scripts.criar_usuario senha roberto
```

`renomear` preserva o id, e com ele a senha, as sessões e a autoria já gravada em
`simulacoes` e `leituras_ocr` — a conta de instalação vira a conta real em vez de virar uma
segunda linha órfã.

Contas são administradas pela linha de comando. Não existe tela de cadastro nem de
recuperação de senha de propósito: são poucos operadores, e um fluxo de recuperação por
e-mail seria mais superfície de ataque do que conveniência.

```bash
python -m scripts.criar_usuario listar
python -m scripts.criar_usuario criar joana --papel operador
python -m scripts.criar_usuario senha joana
python -m scripts.criar_usuario desativar joana
```

A senha nunca vai por argumento — `ps` mostraria a linha de comando e o histórico do shell
a gravaria em disco. Ela é pedida no prompt.

### Como a sessão funciona

Três cookies, escritos pelo backend no login:

| Cookie | Conteúdo | Vida | HttpOnly |
|:--|:--|:--|:--|
| `mahu_access` | JWT HS256 com `sub` e `sid` | 5 min | sim |
| `mahu_refresh` | 32 bytes aleatórios, guardados no banco como sha256 | 30 dias | sim |
| `mahu_csrf` | token do double-submit | 30 dias | **não** (o JS precisa copiá-lo) |

Cookie, e não `Authorization: Bearer`, por duas razões concretas deste projeto: o histórico
usa `EventSource`, que não permite definir cabeçalho nenhum; e frontend e API compartilham
origem pelo proxy do nginx, então o cookie viaja sem CORS e sem ficar legível por
JavaScript — o que um token em `localStorage` não consegue oferecer contra XSS. O preço é
CSRF, pago com `SameSite=Strict` mais o double-submit de `mahu_csrf`.

**A sessão é uma linha em `sessoes`, não só um JWT.** Um JWT autoassinado não sabe ser
cancelado: sair da conta apagaria o cookie e uma cópia do token seguiria valendo até vencer.
Com a linha no banco, sair derruba o acesso na requisição seguinte — inclusive um SSE já
aberto, porque o stream reconfere a sessão a cada batimento de 25 s.

**O refresh rotaciona e a rotação é vigiada.** Cada renovação queima a anterior. Se um
refresh já queimado reaparecer, existem duas cópias do cookie em circulação e uma delas não
é do dono: a cadeia inteira cai e o legítimo precisa entrar de novo.

Uma sessão morre de quatro formas: revogada (logout, senha trocada, reúso detectado),
vencida pelo teto absoluto de 30 dias, parada por mais de 14 dias, ou com o usuário
desativado.

### O que foi feito contra enumeração de usuários

Usuário inexistente, senha errada e conta desativada devolvem **o mesmo 401 com o mesmo
texto**. E também no mesmo tempo: quando o username não existe, o bcrypt roda mesmo assim,
contra um hash descartável. Sem isso a negativa sairia em microssegundos num caso e em
~250 ms no outro, e o cronômetro entregaria a lista de contas que a mensagem única esconde.

A coluna `usuarios.username` é `UNIQUE COLLATE NOCASE`: `Roberto` e `roberto` não podem
coexistir. Os valores de entrada passam por um `pattern` do Pydantic (`[A-Za-z0-9._-]{1,32}`)
antes de chegar ao banco, e todo SQL do projeto é parametrizado com `?` — não há
concatenação de string em consulta nenhuma.

### Onde ficam os guards

No backend, em `main.py`, um por router:

```python
app.include_router(pontos_router, dependencies=[Depends(exigir_usuario)])
```

No router, e não em cada rota: assim rota nova nasce fechada. A CI confere isso listando as
rotas de `/api` e reprovando qualquer uma fora da lista pública que não exija sessão.

No frontend, `AuthGate` envolve o `App` inteiro em `main.tsx`. Sem sessão, nenhum painel é
montado — mas isso é conveniência, não segurança: a defesa está no backend, onde cada rota
recusa por conta própria.

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
| `CARTA_JWT_SECRET` | segredo fixo de dev | Assina os access tokens. **Obrigatório em produção** — sem ele a API não sobe |
| `CARTA_ENV` | vazio | `production` tira o Swagger do ar e exige `Secure` nos cookies |
| `CARTA_COOKIE_SECURE` | segue `CARTA_ENV` | Só para servir produção sem HTTPS |

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

As fotos lidas ficam em `/data/media`, no mesmo volume do banco. `CARTA_MEDIA_RETENCAO_DIAS`
(padrão 90) apaga as antigas no boot — **exceto** as rotuladas: leitura que o usuário
corrigiu à mão ou descartou fica guardada para sempre. Essas são o corpus com o qual o OCR
é medido, e são justamente as que a retenção apagaria primeiro. `CARTA_GUARDAR_IMAGENS=0`
desliga a guarda por completo, e `CARTA_MEDIA_RETENCAO_DIAS=0` mantém tudo.

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
├── routes/auth.py             # Login, refresh, logout, /me (único router público)
├── services/
│   ├── seguranca.py           # bcrypt, JWT e cookies (sem banco)
│   ├── autenticacao.py        # Abrir, validar, rotacionar e revogar sessão
│   ├── guardas.py             # Depends(exigir_usuario) e o double-submit de CSRF
│   ├── psicrometria.py        # Cálculos via psychrolib
│   ├── mahu.py                # Mapeamento campos do painel -> P1..P4
│   ├── mahu_campos.py         # Metadados dos campos: casas decimais e faixas
│   ├── mahu_parse.py          # Texto do OCR -> valor (puro, sem OpenCV)
│   ├── mahu_validacao.py      # Coerência entre campos da leitura
│   ├── mahu_ocr.py            # Alinhamento, recorte das ROIs e OCR
│   ├── mahu_metricas.py       # Tipos das métricas de captura (puro)
│   ├── mahu_qualidade.py      # Nitidez, reflexo, enquadramento, erro de reprojeção
│   ├── telemetria_ocr.py      # Sugerido vs aplicado, desfecho e a foto
│   ├── perfil_ocr.py          # ROIs, limiares e faixas como configuração versionada
│   ├── armazenamento_perfil.py # Semear, ler o vigente, gravar candidato, promover
│   ├── corpus_ocr.py          # Camadas de verdade e a regra de promoção (puro)
│   ├── vigilancia_ocr.py      # Desfaz a promoção que azedou em produção (puro)
│   ├── guia_captura.py        # Vetor de qualidade -> instrução na tela (puro)
│   ├── afinador_ocr.py        # Deriva os parâmetros do corpus, com as travas (puro)
│   ├── armazenamento_corpus.py # Carregar o corpus rotulado, gravar o placar
│   └── eventos.py             # Difusor em memória que alimenta o SSE
├── assets/
│   └── mahu_template.png      # Gabarito canônico do painel (1200x480)
└── Dockerfile

scripts/criar_usuario.py       # Contas: criar, trocar senha, desativar, listar
docs/fotosMahu/                # Fotos de referência do OCR + ground_truth.json
```

Os três módulos `mahu_campos` <- `mahu_parse` <- `mahu_ocr` são separados de propósito:
os dois primeiros não dependem de OpenCV nem do easyocr, e é o que permite importá-los
sem instalar o ambiente completo (~2 GB por causa do torch). `mahu_metricas`, `perfil_ocr`
e `corpus_ocr` seguem a mesma regra.

### Como a leitura melhora sozinha

Cada leitura aplicada deixa no banco o par (sugerido, aplicado) e a foto no disco. Cada
descarte deixa o motivo. Isso é ground truth que se acumula sem ninguém montar conjunto de
teste — e é a diferença entre rodar um script nas mesmas 9 fotos e medir contra o que a
planta de fato produz.

O que a leitura usa — ROIs, limiares, faixas — não é constante de código: é uma linha em
`perfis_ocr`. `avaliar_corpus.py` reprocessa a fatia mais recente do corpus sob o perfil
vigente e sob um candidato, e troca um pelo outro **só quando o candidato ganha de forma
que não se explica por acaso**:

- nunca com mais erro silencioso que o vigente (leitura errada com status `ok`);
- nunca com regressão em qualquer campo;
- e a vantagem precisa passar num teste de McNemar exato (p ≤ 0,05) sobre os campos em que
  os dois discordam.

Aplicar em menos de 2 s sem corrigir nada não conta como conferência e fica fora do corpus:
é carimbo, e foi assim que a leitura #28 entrou no banco com quatro campos corrompidos.

A partição entre treino e teste é **temporal**, não aleatória. Duas fotos do mesmo painel
com minutos de diferença são quase a mesma imagem; separadas ao acaso, uma treinaria e a
outra julgaria o que o candidato praticamente decorou.

Quem propõe é `afinar_ocr.py`, e ele só enxerga o treino. Cinco parâmetros, cada um com um
mínimo de amostras abaixo do qual o afinador se cala:

| Parâmetro | Vem de | Mínimo |
|:--|:--|--:|
| Faixa de operação por campo | quantis dos valores aplicados | 100 |
| Casas decimais por campo | última casa ser sempre zero | 60 |
| Confiança mínima | curva de erro silencioso × conferências | 120 |
| Inliers mínimos da homografia | percentil 5 das leituras corretas | 80 |
| ROIs | onde o texto apareceu, e onde ele encosta na borda | 40 |
| Limiares do guia de câmera | percentil 5 das fotos que deram certo | 50 |

As travas importam mais que os afinadores. Uma faixa nunca exclui valor já observado; as
casas decimais só diminuem; o piso de inliers só sobe; e uma ROI anda no máximo 4 px por
ciclo e nunca cresce sobre a região vizinha nem sobre uma âncora — essas últimas são
geométricas porque os dados não denunciam esse caso: ler o setpoint da linha de cima dá um
número plausível e dentro da faixa.

### Âncoras: a deriva que a homografia esconde

O erro de reprojeção diz que o alinhamento está ruim; não diz **onde**. Foi assim que a
leitura #28 passou: a homografia casou o suficiente para o corte global e mesmo assim
deslocou o bloco esquerdo do painel, e as ROIs daquele lado recortaram o lugar errado com
confiança alta em todos os campos.

Cada campo tem uma **âncora** — um trecho do desenho do painel (rótulo, moldura) que é
idêntico em toda foto, escolhido automaticamente do gabarito por energia de borda, sem
encostar em nenhuma ROI. Casando esse trecho na imagem retificada sai a deriva **local**, em
pixels canônicos:

- deriva ≤ 10 px com correlação ≥ 0,70 → a ROI é **deslocada** por ela. A deriva vem do
  desenho, que é fixo: se o rótulo apareceu 6 px à direita, o número ao lado também apareceu;
- fora disso → o campo vai para conferência, com o motivo em texto.

Nas 9 fotos de referência a deriva máxima é 2 px e nenhum campo é mandado para conferência;
numa deriva forjada de 7 px, as 8 ROIs a acompanham. Custo: ~5 ms por leitura.

Promover é uma aposta sobre 20% do corpus; a produção é a prova real e continua depois. Toda
corrida do juiz começa conferindo se a promoção anterior azedou — comparando as leituras que
chegaram sob o perfil novo com as que chegaram sob o anterior (Fisher exato, amostras
independentes) — e **reverte sozinha** se azedou. O perfil revertido fica marcado, senão o
afinador reproporia a mesma configuração, ela venceria o mesmo teste, e o sistema entraria
em ciclo.

### O guia de câmera

`POST /api/mahu/enquadramento` recebe um quadro pequeno e devolve **uma** instrução:
"aproxime", "mude o ângulo", "firme o celular", "fique de frente", "centralize". Sem OCR —
só o casamento com o gabarito, ~180 ms — então a câmera pode chamá-lo a cada 1,2 s enquanto
o usuário mira. A moldura fica verde quando serve, e o botão vira "Tirar mesmo assim" quando
não serve, porque quem está olhando o painel é o usuário.

É a alavanca de precisão mais barata do fluxo: corrigir o ângulo custa dois segundos,
enquanto a foto ruim custa 5 MB de upload, ~20 s de OCR e uma conferência inteira para
terminar em descarte. Os limiares saem do percentil 5 das fotos que deram certo em produção
— e ficam FORA do perfil de propósito, porque o juiz mede acerto sobre fotos já tiradas e
mudar o guia não altera nenhuma delas.

O laço completo é um comando:

```bash
docker compose run --rm -v "$PWD/scripts:/scripts" backend python /scripts/afinar_ocr.py
```

Vale rodá-lo periodicamente (um cron semanal na VPS), e não a cada deploy: o corpus cresce
na velocidade das fotos tiradas à mão. `--so-propor` mostra o que sairia sem gravar nada.

```
scripts/
├── avaliar_ocr.py             # Acerto contra as 9 fotos com ground truth escrito à mão
├── avaliar_corpus.py          # Acerto contra o corpus de produção; promove o que for melhor
├── afinar_ocr.py              # Deriva um candidato do corpus e manda o juiz decidir
├── criar_usuario.py           # Contas: criar, trocar senha, desativar, listar
└── relatorio_telemetria.py    # Estado do corpus, dos perfis e das avaliações

frontend/
├── src/
│   ├── chart/                 # Motor de desenho da carta (sem React)
│   │   ├── config.ts          # Escalas e limites
│   │   ├── draw.ts            # Camadas e ordem de renderização
│   │   ├── interaction.ts     # Ponteiro -> estado psicrométrico
│   │   └── layers.ts          # Camadas que o painel liga/desliga
│   ├── components/            # Componentes de UI
│   │   ├── AuthGate.tsx       # Portão: sem sessão, o App nem chega a ser montado
│   │   └── LoginScreen.tsx    # Usuário e senha; sem cadastro nem recuperação
│   ├── hooks/useCamera.ts     # Ciclo de vida do getUserMedia
│   ├── lib/
│   │   ├── http.ts            # axios + CSRF + renovação automática no 401
│   │   ├── psicrometria.ts    # Fórmulas locais (desenho e indicador)
│   │   └── format.ts
│   ├── services/              # Chamadas à API
│   ├── store/                 # Zustand: useAuthStore, useChartStore, useMahuStore, useHistoricoStore
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
