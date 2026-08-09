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

# Por que a leitura saiu como saiu, e o que o usuário fez com ela.
#
# A migração 2 registra QUE o OCR errou (sugerido != aplicado) e não registra NADA sobre a
# foto. Com isso não dá para separar "foto ruim" de "OCR ruim", que pedem correções opostas:
# uma se resolve guiando a captura, a outra mexendo no reconhecimento. As colunas de
# alinhamento e qualidade abaixo são o vetor que descreve cada captura, e é sobre ele que os
# limiares do pré-voo e do guia de câmera passam a ser medidos em vez de chutados.
#
# `desfecho` fecha a outra metade: hoje a leitura descartada some no cliente
# (`useMahuStore.descartarLeitura` só limpa o estado) e fica com `pv_aplicado` NULL para
# sempre, indistinguível de quem fechou a aba. Descarte é o rótulo mais forte de foto ruim
# que este fluxo produz, e estava sendo jogado fora inteiro.
_V4_QUALIDADE_DA_CAPTURA = """
-- Como a foto chegou ao espaço canônico: 'homografia' | 'quadrilatero' | 'resize'.
-- Cair fora da homografia já é sinal de foto ruim, antes de olhar qualquer número lido.
ALTER TABLE leituras_ocr ADD COLUMN align_metodo TEXT;
ALTER TABLE leituras_ocr ADD COLUMN align_inliers INTEGER;
-- Erro de reprojeção em pixels do espaço canônico (1200x480), o mesmo das ROIs.
ALTER TABLE leituras_ocr ADD COLUMN align_erro_reproj REAL;
-- Pior erro LOCAL entre os campos. A #28 casou bem à direita e derivou à esquerda; a
-- mediana global esconde exatamente esse caso, este número não.
ALTER TABLE leituras_ocr ADD COLUMN align_erro_reproj_pior REAL;

ALTER TABLE leituras_ocr ADD COLUMN nitidez REAL;
ALTER TABLE leituras_ocr ADD COLUMN reflexo REAL;
ALTER TABLE leituras_ocr ADD COLUMN preenchimento REAL;
ALTER TABLE leituras_ocr ADD COLUMN inclinacao_graus REAL;
ALTER TABLE leituras_ocr ADD COLUMN px_por_digito REAL;

-- 'pendente'   = leitura devolvida e ainda sem resposta do usuário
-- 'aplicada'   = aceita como lida
-- 'corrigida'  = aceita com ao menos um campo alterado
-- 'descartada' = jogada fora; `motivo_descarte` diz o que estava errado
ALTER TABLE leituras_ocr ADD COLUMN desfecho TEXT NOT NULL DEFAULT 'pendente';
ALTER TABLE leituras_ocr ADD COLUMN motivo_descarte TEXT;
-- Quando o usuário refotografou: liga a tentativa ruim à boa, que é um par de treino
-- muito mais informativo que qualquer uma das duas isolada.
ALTER TABLE leituras_ocr ADD COLUMN substituida_por INTEGER REFERENCES leituras_ocr(id);
-- Tempo entre abrir a conferência e aplicar. Aplicar em 1,5 s é carimbo, não conferência:
-- foi assim que a #28 entrou no banco. Sem isso, "aplicada sem correção" seria tratada
-- como verdade forte mesmo quando ninguém olhou.
ALTER TABLE leituras_ocr ADD COLUMN ms_na_conferencia INTEGER;
-- Imune à purga por retenção. Ver `purgar_imagens_antigas`: sem esta coluna, a retenção
-- de 90 dias apagaria justamente as fotos rotuladas, que são o corpus.
ALTER TABLE leituras_ocr ADD COLUMN preservar INTEGER NOT NULL DEFAULT 0;

-- Erro de reprojeção na vizinhança DESTE campo. É o que permite dizer "tt01 estava 9 px
-- fora do lugar" em vez de só "a leitura tinha alinhamento ruim".
ALTER TABLE leituras_ocr_campos ADD COLUMN erro_reproj_local REAL;

-- As leituras que já existem têm desfecho conhecido: quem tem `pv_aplicado` foi aplicada,
-- e a procedência gravada em `simulacoes` diz quais foram corrigidas. Deixá-las em
-- 'pendente' descartaria o histórico que já está pago.
UPDATE leituras_ocr SET desfecho = 'aplicada'
 WHERE id IN (SELECT leitura_id FROM leituras_ocr_campos WHERE pv_aplicado IS NOT NULL);

UPDATE leituras_ocr SET desfecho = 'corrigida', preservar = 1
 WHERE id IN (
     SELECT leitura_id FROM simulacoes
      WHERE origem = 'ocr_corrigida' AND leitura_id IS NOT NULL
 );

CREATE INDEX IF NOT EXISTS idx_leituras_ocr_desfecho ON leituras_ocr (desfecho);
"""

# Os parâmetros da leitura, versionados.
#
# Enquanto ROIs, limiares e faixas forem constantes de módulo, o corpus não serve para nada:
# ele cresce a cada foto e nenhum número muda por causa disso. Guardar a configuração como
# LINHA é o que permite (a) uma configuração nova entrar sem deploy e (b) medir duas
# configurações sobre o mesmo corpus — que é impossível com constante de módulo, porque só
# existe uma por processo.
#
# `leituras_ocr.perfil_id` é a outra metade: sem saber sob qual configuração cada leitura
# foi feita, não há como atribuir uma melhora ou uma piora a coisa alguma.
_V5_PERFIS_OCR = """
CREATE TABLE IF NOT EXISTS perfis_ocr (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    -- JSON: rois, limiares, faixas e casas decimais. Só o que difere do código.
    config TEXT NOT NULL,
    -- Exatamente uma linha com 1, garantido pelo índice único parcial abaixo.
    ativo INTEGER NOT NULL DEFAULT 0,
    -- 'codigo'   = semeado a partir das constantes do fonte
    -- 'afinador' = montado a partir do corpus
    -- 'rollback' = reativação de um perfil anterior após piora medida
    origem TEXT NOT NULL DEFAULT 'codigo',
    derivado_de INTEGER REFERENCES perfis_ocr(id),
    -- Placar que justificou a promoção. Fica gravado para a decisão ser auditável depois,
    -- inclusive quando o corpus já mudou e o número não puder mais ser reproduzido.
    acerto REAL,
    erros_silenciosos INTEGER,
    amostras INTEGER
);

-- Dois perfis ativos ao mesmo tempo significaria que metade das leituras usou uma
-- configuração e metade usou outra, sem nada no banco dizendo qual. O índice parcial faz o
-- banco recusar isso em vez de deixar acontecer em silêncio.
CREATE UNIQUE INDEX IF NOT EXISTS idx_perfis_ocr_ativo ON perfis_ocr (ativo) WHERE ativo = 1;

ALTER TABLE leituras_ocr ADD COLUMN perfil_id INTEGER REFERENCES perfis_ocr(id);
"""

# O placar de cada corrida do avaliador.
#
# `perfis_ocr.acerto` guarda o número que justificou uma promoção, mas só do vencedor e só
# agregado. Sem estas tabelas não existe série temporal: não dá para dizer se a acurácia
# está subindo ao longo dos meses, nem por que um candidato foi recusado, nem qual campo
# vinha piorando antes de alguém notar. É a diferença entre um sistema que melhora e um que
# se acha melhor.
_V6_AVALIACOES_OCR = """
CREATE TABLE IF NOT EXISTS avaliacoes_ocr (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    -- Junta as linhas do campeão e do candidato de uma mesma comparação.
    corrida TEXT NOT NULL,
    perfil_id INTEGER NOT NULL REFERENCES perfis_ocr(id),
    -- 'campeao' | 'candidato'
    papel TEXT NOT NULL,
    leituras INTEGER NOT NULL,
    acertos INTEGER NOT NULL,
    total INTEGER NOT NULL,
    erros_silenciosos INTEGER NOT NULL,
    -- Só na linha do candidato: 'promovido' | 'recusado' | 'simulado', e o motivo em
    -- texto. Guardar o motivo da RECUSA é o que evita repetir a mesma tentativa sem saber.
    -- 'simulado' é o candidato que venceu e não entrou porque a corrida era um ensaio.
    decisao TEXT,
    motivo TEXT
);

CREATE INDEX IF NOT EXISTS idx_avaliacoes_ocr_corrida ON avaliacoes_ocr (corrida);

-- O agregado esconde o campo que sempre erra, e é ele que precisa de ROI nova ou de outra
-- variante de pré-processamento.
CREATE TABLE IF NOT EXISTS avaliacoes_ocr_campos (
    avaliacao_id INTEGER NOT NULL,
    key TEXT NOT NULL,
    acertos INTEGER NOT NULL,
    total INTEGER NOT NULL,
    erros_silenciosos INTEGER NOT NULL,
    PRIMARY KEY (avaliacao_id, key),
    FOREIGN KEY (avaliacao_id) REFERENCES avaliacoes_ocr(id)
);
"""

# O que o juiz não pega, e o que ele nem deveria julgar.
#
# `revertido_em` existe porque a promoção é uma aposta sobre 20% do corpus, e a produção é a
# única prova real. Um candidato pode ganhar no conjunto de teste e piorar na planta — foto
# de outra hora do dia, outra pessoa segurando o celular. Sem marcar o perfil revertido, o
# afinador reproporia a mesma configuração no ciclo seguinte, ela venceria o mesmo teste
# outra vez, e o sistema entraria em ciclo.
#
# `limiares_captura` fica FORA do perfil de propósito. O juiz mede acerto do OCR sobre fotos
# já tiradas, e mudar o limiar do guia de câmera não altera nenhuma dessas leituras — todo
# candidato sairia "idêntico ao vigente" e nada jamais entraria. São coisas que melhoram por
# caminhos diferentes: uma muda como se lê, a outra muda que foto chega.
_V7_VIGILANCIA_E_CAPTURA = """
ALTER TABLE perfis_ocr ADD COLUMN revertido_em TIMESTAMP;
ALTER TABLE perfis_ocr ADD COLUMN motivo_reversao TEXT;

CREATE TABLE IF NOT EXISTS limiares_captura (
    -- Linha única: é a configuração do guia, e ela é uma só.
    id INTEGER PRIMARY KEY CHECK (id = 1),
    atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    -- Derivados do corpus quando há amostra; até lá, os valores medidos à mão sobre as
    -- 9 fotos de docs/fotosMahu.
    px_por_digito_min REAL NOT NULL,
    nitidez_min REAL NOT NULL,
    reflexo_max REAL NOT NULL,
    inclinacao_max REAL NOT NULL,
    erro_reproj_max REAL NOT NULL,
    -- Quantas leituras sustentaram estes números. 0 = ainda são os do código.
    amostras INTEGER NOT NULL DEFAULT 0
);
"""

# Autenticação: quem entra, e sob qual sessão.
#
# A sessão é uma LINHA e não só um JWT porque JWT puro não sabe ser revogado: sair da conta
# apenas apagaria o cookie do navegador, e uma cópia do token continuaria válida até expirar.
# Com a linha, `revogada_em` derruba a sessão no instante seguinte, inclusive um SSE aberto.
#
# O refresh é guardado como sha256 e nunca em claro: vazar a tabela não pode entregar sessões
# ativas. Não é bcrypt de propósito — são 32 bytes aleatórios, não há dicionário que os ataque,
# e um bcrypt por renovação custaria centenas de milissegundos para não proteger nada a mais.
#
# `usuario_id` em `simulacoes` e `leituras_ocr` é nulo nas linhas antigas: elas foram gravadas
# antes de existir login e não têm dono conhecido. Inventar um seria pior que admitir a lacuna.
_V8_AUTENTICACAO = """
CREATE TABLE IF NOT EXISTS usuarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    -- COLLATE NOCASE: o UNIQUE do SQLite é sensível a maiúsculas, então sem isto "Roberto"
    -- e "roberto" seriam duas contas. NOCASE só dobra ASCII, o que basta porque o regex de
    -- username em models.py já recusa qualquer coisa fora de [A-Za-z0-9._-].
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    senha_hash TEXT NOT NULL,
    papel TEXT NOT NULL DEFAULT 'operador',
    ativo INTEGER NOT NULL DEFAULT 1,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    senha_atualizada_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ultimo_login_em TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sessoes (
    -- uuid4. Viaja no claim `sid` do access token; é por ele que cada requisição confere
    -- se a sessão ainda vale.
    id TEXT PRIMARY KEY,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    refresh_hash TEXT NOT NULL,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    -- Teto absoluto: mesmo renovando sem parar, a sessão morre aqui. Sem ele a rotação
    -- eterna produz sessão imortal.
    expira_em TIMESTAMP NOT NULL,
    -- Alimenta o corte por ociosidade, que é outra coisa: mede tempo desde o último uso.
    ultimo_uso_em TIMESTAMP,
    revogada_em TIMESTAMP,
    -- 'logout' | 'logout_global' | 'rotacao' | 'reuso_detectado' | 'senha_alterada'
    motivo_revogacao TEXT,
    -- Na rotação, aponta para a sessão que substituiu esta. É o que permite, ao ver um
    -- refresh já rotacionado voltar, derrubar a cadeia inteira e não só o elo apresentado.
    substituida_por TEXT REFERENCES sessoes(id),
    user_agent TEXT,
    ip TEXT
);

CREATE INDEX IF NOT EXISTS idx_sessoes_usuario ON sessoes (usuario_id);
CREATE INDEX IF NOT EXISTS idx_sessoes_expira ON sessoes (expira_em);

ALTER TABLE simulacoes ADD COLUMN usuario_id INTEGER REFERENCES usuarios(id);
ALTER TABLE leituras_ocr ADD COLUMN usuario_id INTEGER REFERENCES usuarios(id);

-- Conta de instalação: admin / admin. Existe para o primeiro login ser possível num banco
-- recém-criado, e para ser TROCADA logo em seguida:
--
--     python -m scripts.criar_usuario renomear admin <nome real>
--     python -m scripts.criar_usuario senha <nome real>
--
-- Enquanto a senha continuar sendo 'admin', a API grita um aviso a cada subida
-- (`avisar_credenciais_padrao`) — credencial padrão esquecida é como a maioria dos sistemas
-- pequenos é invadida, e o aviso é o que impede o esquecimento de passar despercebido.
--
-- O hash é literal, e não gerado na subida, para que o valor seja o mesmo em qualquer
-- máquina e a senha em claro não exista no código-fonte. bcrypt custo 12.
INSERT OR IGNORE INTO usuarios (username, senha_hash, papel)
VALUES ('admin', '$2b$12$E.t/OVpIQ1mPFD6eNzFPDet3QMx1uSrK8rhSqV3wuFDTyyktNo712', 'admin');
"""

# Os desvios do painel contra o processo, e o Delta H que fecha o par com o gasto térmico.
#
# `calcular_desvios` já existia, mas o resultado só viajava na resposta HTTP e morria com
# ela: reabrir uma leitura do histórico (`ler_processo_por_simulacao`) não trazia de volta
# TT_04, TT_06, TT07, MT07 nem o PID lido — a comparação com o setpoint ficava impossível
# de auditar depois. `desvios_processo` grava o que `calcular_desvios` já calculava.
#
# `delta_h_entalpia` é a diferença pedida para o gráfico gasto térmico × Delta H: entalpia
# do setpoint de P2 menos a entalpia lida/digitada no PID TT04 ENTALPIA (PV). Fica em
# `processos` e não só em `desvios_processo` porque o histórico de gasto térmico lê essa
# coluna direto, uma linha por leitura, sem precisar de JOIN para um único número.
_V9_DESVIOS_E_DELTA_H = """
ALTER TABLE processos ADD COLUMN delta_h_entalpia REAL;

CREATE TABLE IF NOT EXISTS desvios_processo (
    processo_id INTEGER NOT NULL,
    campo TEXT NOT NULL,
    ponto TEXT NOT NULL,
    propriedade TEXT NOT NULL,
    unidade TEXT NOT NULL,
    medido REAL NOT NULL,
    calculado REAL NOT NULL,
    diferenca REAL NOT NULL,
    PRIMARY KEY (processo_id, campo),
    FOREIGN KEY (processo_id) REFERENCES processos(id)
);

CREATE INDEX IF NOT EXISTS idx_desvios_processo ON desvios_processo (processo_id);
"""

MIGRACOES: list[tuple[int, str]] = [
    (1, _V1_ESTRUTURA_INICIAL),
    (2, _V2_TELEMETRIA_OCR),
    (3, _V3_PROCESSO),
    (4, _V4_QUALIDADE_DA_CAPTURA),
    (5, _V5_PERFIS_OCR),
    (6, _V6_AVALIACOES_OCR),
    (7, _V7_VIGILANCIA_E_CAPTURA),
    (8, _V8_AUTENTICACAO),
    (9, _V9_DESVIOS_E_DELTA_H),
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
