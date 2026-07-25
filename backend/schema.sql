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
