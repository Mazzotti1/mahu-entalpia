"""Migrações de schema, versionadas por `PRAGMA user_version`.

Substitui o `schema.sql` que era reexecutado a cada boot. Ele só continha
`CREATE TABLE IF NOT EXISTS`, então **coluna nova em tabela existente nunca era criada**:
o banco de produção já tem dados e teria ficado para trás em silêncio.

Cada migração roda uma vez, na ordem, e o número gravado no banco diz onde parou. Bancos
que já existem estão em `user_version = 0` com as tabelas da migração 1 criadas — por isso
a migração 1 continua sendo `IF NOT EXISTS` e é inofensiva reaplicar.

Para adicionar uma migração: acrescente `(n, "...")` ao fim da lista. Nunca edite uma
migração já publicada — quem já rodou não a executa de novo.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Só para anotação: assim o SQL das migrações fica testável sem instalar o driver.
    import aiosqlite

_V1_ESTRUTURA_INICIAL = """
CREATE TABLE IF NOT EXISTS pontos_psicrometricos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    label TEXT NOT NULL,
    tbs REAL NOT NULL,
    ur REAL,
    entalpia REAL,
    w_abs REAL,
    pressao_atm REAL NOT NULL DEFAULT 101325,
    w_calculado REAL NOT NULL,
    h_calculado REAL NOT NULL,
    ur_calculado REAL NOT NULL,
    tbu_calculado REAL NOT NULL,
    volume_especifico REAL NOT NULL,
    ponto_orvalho REAL NOT NULL,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS simulacoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL,
    descricao TEXT,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS simulacao_pontos (
    simulacao_id INTEGER NOT NULL,
    ponto_id INTEGER NOT NULL,
    ordem INTEGER NOT NULL,
    FOREIGN KEY (simulacao_id) REFERENCES simulacoes(id),
    FOREIGN KEY (ponto_id) REFERENCES pontos_psicrometricos(id),
    PRIMARY KEY (simulacao_id, ponto_id)
);
"""

# Telemetria do OCR. Antes disso o banco guardava só o resultado aceito: raw_text,
# confiança e status eram calculados, devolvidos ao navegador e descartados, e não havia
# como saber quais leituras o usuário tinha corrigido. Sem esse par sugerido/aplicado não
# existe forma de medir se uma mudança no OCR melhorou ou piorou nada.
_V2_TELEMETRIA_OCR = """
CREATE TABLE IF NOT EXISTS leituras_ocr (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    -- Nome do arquivo sob CARTA_MEDIA_DIR; NULL quando a guarda de imagens está desligada.
    imagem_arquivo TEXT,
    imagem_sha256 TEXT,
    imagem_bytes INTEGER,
    requires_review INTEGER NOT NULL DEFAULT 0,
    -- Avisos da validação cruzada, como JSON. O que o OCR não pega sozinho.
    avisos TEXT
);

CREATE INDEX IF NOT EXISTS idx_leituras_ocr_criado_em ON leituras_ocr (criado_em);

-- Um registro por campo. `pv_aplicado` só é preenchido quando o usuário aplica a leitura:
-- divergir de `pv_sugerido` é um erro de OCR rotulado, que é o insumo do avaliador.
CREATE TABLE IF NOT EXISTS leituras_ocr_campos (
    leitura_id INTEGER NOT NULL,
    key TEXT NOT NULL,
    raw_text TEXT,
    pv_sugerido REAL,
    pv_aplicado REAL,
    confidence REAL,
    status TEXT NOT NULL,
    motivo TEXT,
    PRIMARY KEY (leitura_id, key),
    FOREIGN KEY (leitura_id) REFERENCES leituras_ocr(id)
);

-- 'manual'        = não veio de foto (semeadura, POST /api/simulacao)
-- 'ocr_conferida' = veio do OCR e o usuário aceitou os valores como lidos
-- 'ocr_corrigida' = veio do OCR e o usuário mudou ao menos um campo
ALTER TABLE simulacoes ADD COLUMN origem TEXT NOT NULL DEFAULT 'manual';
ALTER TABLE simulacoes ADD COLUMN leitura_id INTEGER REFERENCES leituras_ocr(id);
"""

# O processo completo: 5 pontos, as etapas entre eles e o gasto térmico. Os pontos
# continuam em `pontos_psicrometricos` (é o mesmo tipo de dado), mas as ETAPAS são novas —
# duas leituras de estado não dizem se a serpentina condensou no meio do caminho, e é
# disso que dependem tanto o kW quanto a trajetória desenhada na carta.
_V3_PROCESSO = """
CREATE TABLE IF NOT EXISTS setpoints (
    -- Linha única: a planta tem uma configuração, compartilhada por quem abrir o app.
    id INTEGER PRIMARY KEY CHECK (id = 1),
    w_saida REAL NOT NULL,
    tbs_final REAL NOT NULL,
    entalpia_alvo REAL NOT NULL,
    vazao_m3h REAL NOT NULL,
    pressao_atm REAL NOT NULL,
    atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

INSERT OR IGNORE INTO setpoints (id, w_saida, tbs_final, entalpia_alvo, vazao_m3h, pressao_atm)
VALUES (1, 7.30, 20.0, 36.20, 36575.0, 101325.0);

CREATE TABLE IF NOT EXISTS processos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    simulacao_id INTEGER NOT NULL,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    -- Cópia dos setpoints vigentes na hora. Sem ela, mudar a configuração reescreveria
    -- o significado de todo o histórico.
    w_saida REAL NOT NULL,
    tbs_final REAL NOT NULL,
    entalpia_alvo REAL NOT NULL,
    vazao_m3h REAL NOT NULL,
    pressao_atm REAL NOT NULL,
    vazao_massica_kg_s REAL NOT NULL,
    q_aquecimento_kw REAL NOT NULL,
    q_refrigeracao_kw REAL NOT NULL,
    agua_umidificacao_kg_h REAL NOT NULL,
    condensado_kg_h REAL NOT NULL,
    avisos TEXT,
    FOREIGN KEY (simulacao_id) REFERENCES simulacoes(id)
);

CREATE INDEX IF NOT EXISTS idx_processos_simulacao ON processos (simulacao_id);

CREATE TABLE IF NOT EXISTS etapas_processo (
    processo_id INTEGER NOT NULL,
    ordem INTEGER NOT NULL,
    tipo TEXT NOT NULL,
    de TEXT NOT NULL,
    para TEXT NOT NULL,
    delta_h REAL NOT NULL,
    delta_w REAL NOT NULL,
    q_kw REAL NOT NULL,
    q_sensivel_kw REAL NOT NULL,
    q_latente_kw REAL NOT NULL,
    agua_kg_h REAL NOT NULL,
    condensado_kg_h REAL NOT NULL,
    -- Onde a trajetória dobrou sobre a curva de saturação; NULL quando é uma reta só.
    joelho_tbs REAL,
    joelho_w REAL,
    PRIMARY KEY (processo_id, ordem),
    FOREIGN KEY (processo_id) REFERENCES processos(id)
);
"""

MIGRACOES: list[tuple[int, str]] = [
    (1, _V1_ESTRUTURA_INICIAL),
    (2, _V2_TELEMETRIA_OCR),
    (3, _V3_PROCESSO),
]


async def aplicar_migracoes(db: aiosqlite.Connection) -> int:
    """Aplica o que falta e devolve a versão final do schema."""
    cursor = await db.execute("PRAGMA user_version")
    linha = await cursor.fetchone()
    versao = int(linha[0])

    for numero, script in MIGRACOES:
        if numero <= versao:
            continue
        await db.executescript(script)
        # PRAGMA não aceita parâmetro vinculado; `numero` é int literal desta lista.
        await db.execute(f"PRAGMA user_version = {int(numero)}")
        await db.commit()
        versao = numero

    return versao
