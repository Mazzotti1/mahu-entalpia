Desenvolvimento de Sistemas Térmicos

**PLANEJAMENTO TÉCNICO: CARTA PSICROMÉTRICA ASHRAE COM BACKEND FASTAPI**

*Desenvolvimento de interface gráfica com dados fixos e cálculos psicrométricos*

22 de maio de 2024

1\. Stack Tecnológica

Para garantir o máximo desempenho gráfico e controle sobre os elementos normativos da **ASHRAE**, a stack definida foca em tecnologias nativas de web:

- **Frontend:HTML5** + **Canvas API** + **JavaScript (ES6+)**

- **Estilização:CSS3** (Layout responsivo para o painel de dados)

- **Cálculos:** Biblioteca interna de funções termodinâmicas (sem dependências externas)

**Decisão:** O uso da **Canvas API** é mandatório para permitir a renderização precisa das curvas de saturação e linhas de entalpia, que exigem alta densidade de pontos para suavização visual.

2\. Sistema de Coordenadas da Carta

A carta psicrométrica opera em um espaço bidimensional onde as propriedades do ar são mapeadas para coordenadas cartesianas.

- **Eixo X (horizontal):** Temperatura de Bulbo Seco (**TBS**) em **°C**

- **Eixo Y (vertical):** Umidade Absoluta / Razão de Umidade (**W**) em **g/kg** de ar seco

2.1. Limites e Configuração

const chartConfig = {
margin: { top: 60, right: 80, bottom: 80, left: 100 },
width: 1000,
height: 700,
tbsMin: 0,
tbsMax: 50,
wMin: 0,
wMax: 30, // g/kg
atmPressure: 101325 // Pa (Nível do mar)
};

// Conversão TBS → pixel X
function tbsToX(tbs) {
const plotW = chartConfig.width - chartConfig.margin.left - chartConfig.margin.right;
return chartConfig.margin.left + ((tbs - chartConfig.tbsMin) / (chartConfig.tbsMax - chartConfig.tbsMin)) \* plotW;
}

// Conversão W → pixel Y
function wToY(w) {
const plotH = chartConfig.height - chartConfig.margin.top - chartConfig.margin.bottom;
return chartConfig.margin.top + (1 - (w - chartConfig.wMin) / (chartConfig.wMax - chartConfig.wMin)) \* plotH;
}

3\. Fórmulas Psicrométricas

O motor de cálculo deve seguir as correlações termodinâmicas padrão para ar úmido:

const P_ATM = 101325; // Pa

// 3.1 --- Pressão de saturação de vapor (Magnus/Tetens)
function pressaoSaturacao(tbs) {
return 610.78 *Math.exp((17.27* tbs) / (237.3 + tbs));
}

// 3.2 --- Umidade absoluta (W) a partir de UR e TBS
function urParaW(ur, tbs) {
const pws = pressaoSaturacao(tbs);
const pw = (ur / 100) \* pws;
return 0.622 \* pw / (P_ATM - pw); // Retorna kg/kg
}

// 3.3 --- Entalpia a partir de TBS e W
function calcularEntalpia(tbs, w) {
return 1.006 *tbs + w* (2501 + 1.86 \* tbs); // kJ/kg
}

// 3.4 --- W a partir de entalpia e TBS
function entalpiaParaW(h, tbs) {
return (h - 1.006 *tbs) / (2501 + 1.86* tbs);
}

// 3.5 --- UR a partir de W e TBS
function wParaUr(w, tbs) {
const pws = pressaoSaturacao(tbs);
const pw = (w \* P_ATM) / (0.622 + w);
return (pw / pws) \* 100;
}

// 3.6 --- Temperatura de bulbo úmido (Iterativo)
function calcTbu(tbs, w) {
let tbu = tbs;
for (let i = 0; i \< 100; i++) {
const pwsTbu = pressaoSaturacao(tbu);
const wSat = 0.622 \* pwsTbu / (P_ATM - pwsTbu);
if (Math.abs(wSat - w) \< 0.00001) break;
if (wSat \> w) tbu -= 0.01; else tbu += 0.01;
}
return tbu;
}

// 3.7 --- Volume específico
function volumeEspecifico(tbs, w) {
return (287.05 *(tbs + 273.15)* (1 + 1.6078 \* w)) / P_ATM;
}

4\. Conversão dos Pontos de Teste

|  |  |  |  |  |
|:--:|:--:|:--:|:--:|:--:|
| **Ponto** | **Entrada** | **Cálculo** | **TBS (°C)** | **W (g/kg)** |
| P1 | UR=64,09%, TBS=20,27 | urParaW(64.09, 20.27) | 20,27 | 9,50 |
| P2 | h=36,20, TBS=12,20 | entalpiaParaW(36.20, 12.20) | 12,20 | 9,48 |
| P3 | UR=100%, TBS=8,70 | urParaW(100, 8.70) | 8,70 | 6,98 |
| P4 | W=7,3, TBS=21,2 | Direto | 21,20 | 7,30 |

5\. Ordem de Renderização Gráfica

Para garantir a legibilidade, o agente deve seguir a ordem de camadas (Z-index):

1.  **Grade Base:** Eixos **TBS** e **W** com subdivisões.

2.  **Curva de Saturação:** Linha de **UR=100%** calculada ponto a ponto.

3.  **Isolinhas de UR:** Curvas de **10%** a **90%** (cor: \#D1D5DB).

4.  **Isolinhas de Entalpia:** Linhas diagonais tracejadas (cor: \#A7F3D0).

5.  **Isolinhas de Bulbo Úmido:** Linhas contínuas finas (cor: \#BAE6FD).

6.  **Vetor de Processo:** Conexão dos pontos **P1→P2→P3→P4** (cor: \#2563EB).

7.  **Pontos de Dados:** Marcadores circulares com labels (cor: \#E11D48).

6\. Tabela de Propriedades Calculadas

|  |  |  |  |  |  |  |
|:--:|:--:|:--:|:--:|:--:|:--:|:--:|
| **Ponto** | **TBS (°C)** | **W (g/kg)** | **UR (%)** | **h (kJ/kg)** | **TBU (°C)** | **Vol. (m³/kg)** |
| P1 | 20,27 | 9,50 | **64,09** | 44,45 | 13,87 | 0,842 |
| P2 | 12,20 | 9,48 | 87,03 | **36,20** | 10,92 | 0,815 |
| P3 | 8,70 | 6,98 | **100,00** | 26,31 | 8,70 | 0,804 |
| P4 | 21,20 | **7,30** | 47,02 | 39,90 | 12,83 | 0,846 |

7\. Checklist de Validação Técnica

- **Consistência de Unidades:** Garantir que **W** seja convertido de **kg/kg** para **g/kg** apenas no momento da plotagem.

- **Clipping de Curvas:** As linhas de **UR** e **Entalpia** devem ser cortadas exatamente na interseção com a curva de saturação.

- **Precisão de Saturação:** O ponto **P3** deve estar exatamente sobre a linha de borda da carta.

- **Legibilidade:** Labels dos pontos não devem sobrepor as linhas de grade principais.

8\. Backend: Python + FastAPI + SQLite

Para separar a regra de negócio do frontend, o backend em **Python** será responsável por todos os cálculos psicrométricos, persistência dos dados e exposição de uma **API REST** consumida pelo frontend **Canvas API**.

8.1. Stack do Backend

- **Framework:FastAPI** (**Python 3.11+**)

- **Biblioteca de cálculo:** psychrolib (padrão **ASHRAE**, mantido pela comunidade)

- **Banco de dados:SQLite** (via sqlite3 nativo ou aiosqlite para operações assíncronas)

- **Servidor:Uvicorn** (**ASGI**)

- **Validação de dados:Pydantic** (integrado ao **FastAPI**)

- **CORS:** fastapi.middleware.cors (liberar requisições do frontend)

**Decisão:** A biblioteca psychrolib implementa as correlações psicrométricas padrão **ASHRAE** com precisão validada, eliminando a necessidade de reimplementar fórmulas manualmente no backend. O frontend apenas consome os resultados.

8.2. Estrutura de Arquivos do Backend

backend/
├── main.py \# Entry point do FastAPI + configuração CORS
├── database.py \# Conexão SQLite e criação de tabelas
├── models.py \# Modelos Pydantic (request/response)
├── services/
│ └── psicrometria.py \# Regra de negócio: cálculos via psychrolib
├── routes/
│ └── pontos.py \# Endpoints CRUD para pontos psicrométricos
├── requirements.txt \# Dependências
└── simulador.db \# Banco SQLite (gerado automaticamente)

8.3. Dependências (requirements.txt)

fastapi==0.115.0
uvicorn\[standard\]==0.30.0
psychrolib==2.5.0
aiosqlite==0.20.0
pydantic==2.9.0

8.4. Criação da Tabela SQLite

O agente deve executar este script na inicialização do backend (em database.py):

CREATE TABLE IF NOT EXISTS pontos_psicrometricos (
id INTEGER PRIMARY KEY AUTOINCREMENT,
label TEXT NOT NULL, \-- Ex: \"P1\", \"P2\"
tbs REAL NOT NULL, \-- Temperatura de Bulbo Seco (°C)
ur REAL, \-- Umidade Relativa (%) --- pode ser NULL
entalpia REAL, \-- Entalpia (kJ/kg) --- pode ser NULL
w_abs REAL, \-- Umidade Absoluta (g/kg) --- pode ser NULL
pressao_atm REAL DEFAULT 101325, \-- Pressão atmosférica (Pa)
\-- Propriedades calculadas (preenchidas pelo backend):
w_calculado REAL, \-- Umidade absoluta calculada (g/kg)
h_calculado REAL, \-- Entalpia calculada (kJ/kg)
ur_calculado REAL, \-- UR calculada (%)
tbu_calculado REAL, \-- Temperatura de bulbo úmido (°C)
volume_especifico REAL, \-- Volume específico (m³/kg)
ponto_orvalho REAL, \-- Temperatura de ponto de orvalho (°C)
criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS simulacoes (
id INTEGER PRIMARY KEY AUTOINCREMENT,
nome TEXT NOT NULL, \-- Nome da simulação
descricao TEXT,
criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS simulacao_pontos (
simulacao_id INTEGER NOT NULL,
ponto_id INTEGER NOT NULL,
ordem INTEGER NOT NULL, \-- Ordem do ponto na sequência (1, 2, 3, 4)
FOREIGN KEY (simulacao_id) REFERENCES simulacoes(id),
FOREIGN KEY (ponto_id) REFERENCES pontos_psicrometricos(id),
PRIMARY KEY (simulacao_id, ponto_id)
);

**Observação:** A tabela pontos_psicrometricos aceita qualquer combinação de entrada (**UR+TBS**, **Entalpia+TBS**, **W+TBS**) e armazena todos os parâmetros calculados pelo backend. A tabela simulacao_pontos define a sequência de conexão dos pontos (**P1→P2→P3→P4**).

8.5. Modelos Pydantic (models.py)

from pydantic import BaseModel
from typing import Optional

class PontoInput(BaseModel):
label: str
tbs: float
ur: Optional\[float\] = None \# % --- se informado, calcula W a partir da UR
entalpia: Optional\[float\] = None \# kJ/kg --- se informado, calcula W a partir de h
w_abs: Optional\[float\] = None \# g/kg --- se informado, usa diretamente
pressao_atm: float = 101325.0 \# Pa

class PontoResponse(BaseModel):
id: Optional\[int\] = None
label: str
tbs: float
w: float \# g/kg
ur: float \# %
entalpia: float \# kJ/kg
tbu: float \# °C
volume_especifico: float \# m³/kg
ponto_orvalho: float \# °C
fonte_calculo: str \# \"ur\", \"entalpia\" ou \"w_abs\"

class SimulacaoInput(BaseModel):
nome: str
descricao: Optional\[str\] = None
pontos: list\[PontoInput\] \# Lista ordenada de pontos

class SimulacaoResponse(BaseModel):
id: int
nome: str
pontos: list\[PontoResponse\]

8.6. Regra de Negócio: Cálculos Psicrométricos (services/psicrometria.py)

import psychrolib

Define a unidade do sistema: SI (Métrico)

psychrolib.SetUnitSystem(psychrolib.SI)

def calcular_ponto(tbs: float, ur=None, entalpia=None, w_abs=None,
pressao_atm=101325.0) -\> dict:
\"\"\"
Calcula todas as propriedades psicrométricas de um ponto.
Aceita diferentes combinações de entrada:
- UR + TBS → calcula W
- Entalpia + TBS → calcula W (inversão)
- W_abs + TBS → usa W diretamente
Retorna dict com todas as propriedades.
\"\"\"
\# 1. Determinar W (umidade absoluta) a partir da entrada disponível
if w_abs is not None:
w_kgkg = w_abs / 1000.0 \# converte g/kg → kg/kg
fonte = \"w_abs\"
elif ur is not None:
\# psychrolib: GetHumRatioFromRelHum(tdb, rh, pressure)
w_kgkg = psychrolib.GetHumRatioFromRelHum(tbs, ur / 100.0, pressao_atm)
fonte = \"ur\"
elif entalpia is not None:
\# Inversão: \$\$h = 1.006 \cdot TBS + W \cdot (2501 + 1.86 \cdot TBS)\$\$
\# → \$\$W = \frac{entalpia - 1.006 \cdot TBS}{2501 + 1.86 \cdot TBS}\$\$
w_kgkg = (entalpia - 1.006 *tbs) / (2501 + 1.86* tbs)
fonte = \"entalpia\"
else:
raise ValueError(\"Informar UR, entalpia ou w_abs\")

\# 2. Calcular todas as propriedades via psychrolib
w_gkg = w_kgkg \* 1000.0 \# para exibição
\# Umidade relativa calculada
ur_calc = psychrolib.GetRelHumFromHumRatio(tbs, w_kgkg, pressao_atm) \* 100.0
\# Entalpia calculada
h_calc = psychrolib.GetMoistAirEnthalpy(tbs, w_kgkg)
\# Temperatura de bulbo úmido
tbu_calc = psychrolib.GetTwetBulbFromHumRatio(tbs, w_kgkg, pressao_atm)
\# Volume específico
vol_calc = psychrolib.GetMoistAirVolume(tbs, w_kgkg, pressao_atm)
\# Temperatura de ponto de orvalho
torv_calc = psychrolib.GetTDewPointFromHumRatio(tbs, w_kgkg, pressao_atm)
return {
\&quot;tbs\&quot;: round(tbs, 2),
\&quot;w\&quot;: round(w_gkg, 2),
\&quot;ur\&quot;: round(ur_calc, 2),
\&quot;entalpia\&quot;: round(h_calc / 1000.0, 2), \# psychrolib retorna J/kg → converter para kJ/kg
\&quot;tbu\&quot;: round(tbu_calc, 2),
\&quot;volume_especifico\&quot;: round(vol_calc, 4),
\&quot;ponto_orvalho\&quot;: round(torv_calc, 2),
\&quot;fonte_calculo\&quot;: fonte
}

**Atenção do agente:** O psychrolib retorna entalpia em **J/kg** --- dividir por **1000** para obter **kJ/kg**. Verificar sempre as unidades de cada função na documentação da biblioteca.

8.7. Endpoints da API (routes/pontos.py)

from fastapi import APIRouter, HTTPException
from models import PontoInput, PontoResponse, SimulacaoInput, SimulacaoResponse
from services.psicrometria import calcular_ponto
from database import get_db

router = APIRouter(prefix=\"/api\", tags=\[\"psicrometria\"\])

@router.post(\"/calcular\", response_model=PontoResponse)
async def calcular_ponto_endpoint(ponto: PontoInput):
\"\"\"Calcula propriedades psicrométricas de um ponto sem persistir.\"\"\"
try:
resultado = calcular_ponto(
tbs=ponto.tbs,
ur=ponto.ur,
entalpia=ponto.entalpia,
w_abs=ponto.w_abs,
pressao_atm=ponto.pressao_atm
)
return PontoResponse(label=ponto.label, \*\*resultado)
except ValueError as e:
raise HTTPException(status_code=400, detail=str(e))

@router.post(\"/simulacao\", response_model=SimulacaoResponse)
async def criar_simulacao(simulacao: SimulacaoInput):
\"\"\"Cria uma simulação completa com múltiplos pontos e persiste no banco.\"\"\"
db = await get_db()
\# 1. Inserir simulação
cursor = await db.execute(
\"INSERT INTO simulacoes (nome, descricao) VALUES (?, ?)\",
(simulacao.nome, simulacao.descricao)
)
simulacao_id = cursor.lastrowid

pontos_response = \[\]
for ordem, ponto in enumerate(simulacao.pontos, start=1):
\# 2. Calcular propriedades
calc = calcular_ponto(
tbs=ponto.tbs,
ur=ponto.ur,
entalpia=ponto.entalpia,
w_abs=ponto.w_abs,
pressao_atm=ponto.pressao_atm
)
\# 3. Persistir ponto
cursor = await db.execute(
\&quot;\&quot;\&quot;INSERT INTO pontos_psicrometricos
(label, tbs, ur, entalpia, w_abs, pressao_atm,
w_calculado, h_calculado, ur_calculado, tbu_calculado,
volume_especifico, ponto_orvalho)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)\&quot;\&quot;\&quot;,
(ponto.label, ponto.tbs, ponto.ur, ponto.entalpia, ponto.w_abs,
ponto.pressao_atm, calc\[\&quot;w\&quot;\], calc\[\&quot;entalpia\&quot;\], calc\[\&quot;ur\&quot;\],
calc\[\&quot;tbu\&quot;\], calc\[\&quot;volume_especifico\&quot;\], calc\[\&quot;ponto_orvalho\&quot;\])
)
ponto_id = cursor.lastrowid
\# 4. Vincular à simulação
await db.execute(
\&quot;INSERT INTO simulacao_pontos (simulacao_id, ponto_id, ordem) VALUES (?, ?, ?)\&quot;,
(simulacao_id, ponto_id, ordem)
)
pontos_response.append(PontoResponse(id=ponto_id, label=ponto.label, \*\*calc))
await db.commit()
return SimulacaoResponse(id=simulacao_id, nome=simulacao.nome, pontos=pontos_response)

@router.get(\"/simulacao/{simulacao_id}\", response_model=SimulacaoResponse)
async def get_simulacao(simulacao_id: int):
\"\"\"Recupera uma simulação completa com todos os pontos calculados.\"\"\"
db = await get_db()
\# Buscar simulação
sim = await db.execute(\"SELECT \* FROM simulacoes WHERE id = ?\", (simulacao_id,))
sim_row = await sim.fetchone()
if not sim_row:
raise HTTPException(status_code=404, detail=\"Simulação não encontrada\")
\# Buscar pontos ordenados
pontos_q = await db.execute(
\"\"\"SELECT p.\* FROM pontos_psicrometricos p
JOIN simulacao_pontos sp ON sp.ponto_id = p.id
WHERE sp.simulacao_id = ?
ORDER BY sp.ordem\"\"\",
(simulacao_id,)
)
pontos_rows = await pontos_q.fetchall()
pontos = \[PontoResponse(
id=r\[\"id\"\], label=r\[\"label\"\], tbs=r\[\"tbs\"\],
w=r\[\"w_calculado\"\], ur=r\[\"ur_calculado\"\],
entalpia=r\[\"h_calculado\"\], tbu=r\[\"tbu_calculado\"\],
volume_especifico=r\[\"volume_especifico\"\],
ponto_orvalho=r\[\"ponto_orvalho\"\],
fonte_calculo=\"banco\"
) for r in pontos_rows\]
return SimulacaoResponse(id=sim_row\[\"id\"\], nome=sim_row\[\"nome\"\], pontos=pontos)

8.8. Configuração do FastAPI + CORS (main.py)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routes.pontos import router as pontos_router
from database import init_db

app = FastAPI(title=\"Simulador Psicrométrico API\", version=\"1.0.0\")

Liberar CORS para o frontend

app.add_middleware(
CORSMiddleware,
allow_origins=\[\"http://localhost:8080\", \"http://127.0.0.1:8080\"\],
allow_credentials=True,
allow_methods=\[\"*\"\],
allow_headers=\[\"*\"\],
)

app.include_router(pontos_router)

@app.on_event(\"startup\")
async def startup():
await init_db() \# Cria tabelas SQLite se não existirem

@app.get(\"/\")
async def root():
return {\"status\": \"API Simulador Psicrométrico ativa\"}

8.9. Conexão SQLite Assíncrona (database.py)

import aiosqlite
import os

DB_PATH = os.path.join(os.path.dirname(**file**), \"simulador.db\")

async def init_db():
\"\"\"Cria as tabelas na inicialização do servidor.\"\"\"
db = await aiosqlite.connect(DB_PATH)
db.row_factory = aiosqlite.Row
with open(os.path.join(os.path.dirname(**file**), \"schema.sql\"), \"r\") as f:
await db.executescript(f.read())
await db.commit()
await db.close()

async def get_db():
\"\"\"Retorna conexão ativa para uso nos endpoints.\"\"\"
db = await aiosqlite.connect(DB_PATH)
db.row_factory = aiosqlite.Row
return db

8.10. Integração Frontend ↔ Backend

O frontend em **Canvas API** deve ser modificado para **não calcular localmente** --- em vez disso, consome a **API** do backend.

|  |  |  |  |
|:--:|:--:|:--:|:--:|
| **Função no Frontend** | **Método HTTP** | **Endpoint** | **Descrição** |
| Carregar pontos fixos | POST | /api/simulacao | Envia os 4 pontos e recebe todos calculados |
| Calcular ponto individual | POST | /api/calcular | Envia 1 ponto e recebe propriedades calculadas |
| Recuperar simulação salva | GET | /api/simulacao/{id} | Busca simulação persistida no SQLite |

**Código de integração no frontend (js/api.js):**

const API_BASE = \"http://localhost:8000/api\";

// Envia os 4 pontos para o backend e recebe todos calculados
async function enviarSimulacao(pontos) {
const response = await fetch(\${API_BASE}/simulacao, {
method: \"POST\",
headers: { \"Content-Type\": \"application/json\" },
body: JSON.stringify({
nome: \"Simulação Padrão ASHRAE\",
descricao: \"4 pontos de teste\",
pontos: pontos.map(p =\> ({
label: p.label,
tbs: p.tbs,
ur: p.ur \|\| null,
entalpia: p.entalpia \|\| null,
w_abs: p.w_abs \|\| null,
pressao_atm: 101325
}))
})
});
if (!response.ok) throw new Error(\"Erro ao enviar simulação\");
return await response.json();
}

// Busca simulação salva no banco
async function buscarSimulacao(id) {
const response = await fetch(\${API_BASE}/simulacao/\${id});
if (!response.ok) throw new Error(\"Simulação não encontrada\");
return await response.json();
}

**Modificação no main.js --- substituir cálculo local por chamada de API:**

// ANTES (cálculo local no frontend):
// const pontos = \[ { label: \"P1\", tbs: 20.27, w: urParaW(64.09, 20.27) \* 1000 }, \... \];

// DEPOIS (cálculo no backend):
const pontosInput = \[
{ label: \"P1\", tbs: 20.27, ur: 64.09 },
{ label: \"P2\", tbs: 12.20, entalpia: 36.20 },
{ label: \"P3\", tbs: 8.70, ur: 100.0 },
{ label: \"P4\", tbs: 21.20, w_abs: 7.30 }
\];

async function init() {
// 1. Enviar para o backend calcular e persistir
const simulacao = await enviarSimulacao(pontosInput);

// 2. Usar os pontos retornados para desenhar a carta
const pontos = simulacao.pontos.map(p =\> ({
label: p.label,
tbs: p.tbs,
w: p.w, // já calculado pelo backend (g/kg)
dadosOriginais: UR=\${p.ur}%, h=\${p.entalpia} kJ/kg, W=\${p.w} g/kg
}));

// 3. Desenhar a carta ASHRAE no Canvas
desenharCarta();
desenharPontos(pontos);
conectarPontos(pontos);

// 4. Exibir tabela de propriedades
exibirTabela(simulacao.pontos);
}

init();

8.11. Estrutura Atualizada do Projeto (Frontend + Backend)

simulador-psicrometrico/
├── backend/
│ ├── main.py
│ ├── database.py
│ ├── models.py
│ ├── schema.sql
│ ├── services/
│ │ └── psicrometria.py
│ ├── routes/
│ │ └── pontos.py
│ ├── requirements.txt
│ └── simulador.db \# Gerado automaticamente
├── frontend/
│ ├── index.html
│ ├── css/
│ │ └── style.css
│ ├── js/
│ │ ├── api.js \# Comunicação com o backend
│ │ ├── carta.js \# Desenho da carta ASHRAE (Canvas API)
│ │ ├── pontos.js \# Plotagem e conexão dos pontos
│ │ └── main.js \# Inicialização e orquestração
└── README.md

8.12. Checklist do Backend

- Criar ambiente virtual **Python** (python -m venv venv)

- Instalar dependências (pip install -r requirements.txt)

- Implementar database.py com init_db() e get_db()

- Criar schema.sql com as 3 tabelas (pontos_psicrometricos, simulacoes, simulacao_pontos)

- Implementar services/psicrometria.py usando psychrolib com sistema de unidades **SI**

- Implementar models.py com os schemas **Pydantic** (PontoInput, PontoResponse, SimulacaoInput, SimulacaoResponse)

- Implementar routes/pontos.py com os 3 endpoints (POST /calcular, POST /simulacao, GET /simulacao/{id})

- Configurar main.py com **CORS** liberado para localhost:8080

- Testar endpoints com /docs (**Swagger UI** automático do **FastAPI**)

- Modificar main.js do frontend para consumir a **API** ao invés de calcular localmente

- Criar js/api.js com as funções enviarSimulacao() e buscarSimulacao()

- Validar que os 4 pontos fixos retornam os mesmos valores da tabela da seção 6

Local e data: São Paulo, 22 de maio de 2024

*Documento elaborado em 22 de maio de 2024. As informações contidas são de responsabilidade do solicitante.*
