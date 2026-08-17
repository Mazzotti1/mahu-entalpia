"""Os parâmetros ajustáveis da leitura, reunidos num objeto que pode ser versionado.

Até aqui ROIs, limiares e faixas eram constantes de módulo. Isso tem duas consequências que
esta camada existe para desfazer:

1. **Nada pode melhorar sem deploy.** O corpus cresce a cada foto, mas nenhum número muda
   por causa dele. Mil leituras guardadas leem exatamente igual à primeira.
2. **Não dá para comparar duas configurações.** Constante de módulo é uma só por processo,
   então avaliar "candidato contra vigente" exigiria mutar o módulo no meio da execução —
   o que torna o resultado dependente da ordem em que as coisas rodaram.

Com o perfil como PARÂMETRO, `ler_mahu(bytes, perfil)` é uma função pura da dupla, e rodar
o corpus inteiro sob dois perfis diferentes vira um laço trivial. É esse requisito, e não a
elegância, que decide o desenho: sem ele o juiz da fase seguinte não existe.

O módulo é puro — nem OpenCV, nem sqlite. A persistência fica em `armazenamento_perfil`.

    perfil_ocr (puro) <- mahu_ocr (OpenCV + easyocr)
    perfil_ocr (puro) <- armazenamento_perfil (sqlite)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace

from backend.services.mahu_campos import CAMPOS, Campo

# Regiões de cada valor no espaço canônico (x1, y1, x2, y2).
#
# Medidas como a união das caixas de texto detectadas em 9 fotos já alinhadas ao gabarito,
# mais 3 px de margem. Antes do alinhamento elas precisavam de folga generosa para tolerar
# a variação de enquadramento, e essa folga fazia o recorte engolir a unidade da linha de
# baixo ("12,20" + "°C" vira lixo no OCR). Com a homografia a folga deixou de ser
# necessária. Ao remexer nisso, meça de novo sobre imagens alinhadas — não sobre fotos cruas.
#
# Mora aqui, e não em `mahu_ocr`, porque este módulo é o único que pode ser importado tanto
# por quem tem OpenCV quanto por quem só fala com o banco.
ROIS_PADRAO: dict[str, tuple[int, int, int, int]] = {
    "mt_01": (18, 124, 61, 145),
    "tt01": (79, 124, 120, 145),
    "tt04": (358, 129, 393, 146),
    "tt06": (605, 143, 635, 160),
    "mt07": (960, 120, 996, 139),
    "tt07": (1024, 120, 1059, 140),
    "umd_abs_pv": (919, 50, 942, 62),
    "tt04_entalpia_pv": (360, 59, 387, 72),
    # --- ESTIMADAS, ainda não medidas sobre o corpus alinhado ---------------------------
    # As cinco acima saíram da união das caixas detectadas em 9 fotos; estas três foram
    # DERIVADAS da geometria do painel, e não medidas. Rode `scripts/afinar_ocr.py` assim
    # que houver leituras com elas para trocar a estimativa por medição.
    #
    # Por isso os três campos correspondentes nascem `obrigatorio=False`: uma ROI errada
    # aqui vira campo duvidoso na conferência, e nunca uma leitura bloqueada.
    #
    # `tt02` está na coluna do PID TT02, na mesma faixa vertical de `tt04` (ambos são o par
    # rótulo/valor/unidade sob o bloco do PID). Um pouco mais larga que a de `tt04` porque a
    # posição horizontal veio de proporção, não de medida.
    "tt02": (236, 126, 284, 147),
    # Uma linha ACIMA do PV, no mesmo bloco: SP, PV e MV ficam a 17 px um do outro.
    "tt04_entalpia_sp": (360, 42, 387, 55),
    # Caixa isolada do rodapé ("9,50 / g/Kg"). Folgada de propósito: não há texto vizinho
    # que o recorte possa engolir, e a posição é a menos confiável das três.
    "mt_tt_mahu_21": (525, 412, 600, 438),
}

# Trechos FIXOS do painel usados para medir a deriva local do alinhamento, um por campo.
#
# Escolhidos automaticamente do gabarito: para cada ROI, o recorte vizinho com maior energia
# de borda que não encosta em nenhuma outra ROI. Energia de borda acha o rótulo ("TT_04",
# "MT07"); a exclusão das ROIs garante que a âncora não contenha número, que é a única coisa
# que muda entre fotos. Todas ficam a 41-75 px do campo que descrevem — perto o bastante
# para compartilhar a mesma deriva local.
#
# Ao mudar as ROIs, reescolha estas: uma âncora que passou a sobrepor uma ROI mede a
# posição de um número, e um número que mudou parece deriva.
ANCORAS_PADRAO: dict[str, tuple[int, int, int, int]] = {
    "mt_01": (60, 177, 103, 198),
    "tt01": (74, 177, 115, 198),
    "tt04": (417, 176, 452, 193),
    "tt06": (604, 98, 634, 115),
    "mt07": (959, 185, 995, 204),
    "tt07": (999, 87, 1034, 107),
    "umd_abs_pv": (916, 94, 939, 106),
    "tt04_entalpia_pv": (361, 100, 388, 113),
    # Estimadas junto com as ROIs acima, pelo mesmo critério: texto fixo, perto do campo, sem
    # encostar em ROI nenhuma.
    # O rótulo "TT_02" impresso logo acima do valor.
    "tt02": (236, 108, 284, 125),
    # Mesmo bloco do PV, então a mesma deriva local: a âncora pode ser a mesma caixa.
    "tt04_entalpia_sp": (361, 100, 388, 113),
    # A unidade "g/Kg", impressa dentro da própria caixa do sensor, abaixo do número.
    "mt_tt_mahu_21": (525, 440, 600, 458),
}

# Correlação mínima para a âncora contar como encontrada. Nas 9 fotos de referência a pior
# foi 0,84, e uma deriva forjada de 7 px ainda casou a 0,85 — abaixo de 0,70 o trecho não
# foi achado, e a deriva medida não descreve nada.
MIN_CORRELACAO_ANCORA = 0.70
# Deriva que ainda vale a pena corrigir deslocando a ROI. Acima disso o campo vai para
# conferência em vez de ser deslocado.
#
# Dois números mandam aqui. O de cima é o raio de busca (12 px, em `mahu_qualidade`): uma
# deriva medida no limite da janela pode ser qualquer coisa maior que isso, então o corte
# precisa ficar abaixo dele com folga. O de baixo é o viés sistemático: mesmo nas 9 fotos
# de referência, `mt_01` e `tt01` medem +2 px — resíduo real da homografia naquele canto.
# Com o corte em 8, uma deriva verdadeira de 7 px nesses dois campos mediria 9 e seria
# recusada; com 10, ela é corrigida e ainda sobram 2 px até a borda da janela.
DERIVA_MAX_ANCORA = 10.0

# Abaixo disso a homografia não é confiável e o código cai na retificação por quadrilátero.
# 25 foi escolhido sem medição e foi suficiente para deixar a leitura #28 passar — é
# candidato explícito a ser aprendido do corpus.
MIN_HOMOGRAPHY_INLIERS_PADRAO = 25
# Concordância e confiança mínimas entre as variantes para a leitura valer como "ok".
MIN_VARIANTES_CONCORDANDO_PADRAO = 2
MIN_CONFIANCA_PADRAO = 0.5


@dataclass(frozen=True)
class PerfilOCR:
    """Uma configuração completa da leitura, identificável e comparável com outra.

    `id` é `None` enquanto o perfil não foi gravado — o do código, e os candidatos que o
    afinador monta e descarta sem nunca persistir.

    Os overrides são parciais de propósito: um perfil que muda só a ROI do `tt06` guarda
    uma chave, e não uma cópia de tudo. Assim o diff entre duas versões é legível, e um
    campo que ninguém tocou continua seguindo o código mesmo que o código mude depois.
    """

    id: int | None = None
    rois: dict[str, tuple[int, int, int, int]] = field(default_factory=lambda: dict(ROIS_PADRAO))
    ancoras: dict[str, tuple[int, int, int, int]] = field(
        default_factory=lambda: dict(ANCORAS_PADRAO)
    )
    min_homography_inliers: int = MIN_HOMOGRAPHY_INLIERS_PADRAO
    min_variantes_concordando: int = MIN_VARIANTES_CONCORDANDO_PADRAO
    min_confianca: float = MIN_CONFIANCA_PADRAO
    # key -> (min, max) da faixa de operação. Ausente = a faixa do código.
    faixas_esperadas: dict[str, tuple[float, float]] = field(default_factory=dict)
    # key -> casas do display. Ausente = as do código.
    casas_decimais: dict[str, int] = field(default_factory=dict)

    def campos(self) -> list[Campo]:
        """`CAMPOS` com os overrides deste perfil aplicados.

        `CAMPOS` já vem com o override de `MAHU_FAIXAS_ESPERADAS` aplicado no import, e essa
        precedência é intencional: a variável de ambiente é alguém dizendo "a estação virou,
        use esta faixa", e uma configuração aprendida de dados do mês passado não pode
        sobrescrever essa decisão. Ver `mahu_campos.aplicar_faixas_do_ambiente`.
        """
        return [
            replace(
                campo,
                esperada=self.faixas_esperadas.get(campo.key, campo.esperada),
                casas_decimais=self.casas_decimais.get(campo.key, campo.casas_decimais),
            )
            for campo in CAMPOS
        ]

    def para_json(self) -> str:
        """Só o que difere do código. O `id` fica de fora: é da linha, não da configuração."""
        return json.dumps(
            {
                "rois": {key: list(roi) for key, roi in self.rois.items()},
                "ancoras": {key: list(caixa) for key, caixa in self.ancoras.items()},
                "min_homography_inliers": self.min_homography_inliers,
                "min_variantes_concordando": self.min_variantes_concordando,
                "min_confianca": self.min_confianca,
                "faixas_esperadas": {
                    key: list(faixa) for key, faixa in self.faixas_esperadas.items()
                },
                "casas_decimais": dict(self.casas_decimais),
            },
            ensure_ascii=False,
            sort_keys=True,
        )


PERFIL_DO_CODIGO = PerfilOCR()


def de_json(bruto: str, *, id: int | None = None) -> PerfilOCR:
    """Reconstrói o perfil gravado, caindo no padrão do código no que faltar.

    Tolerar chave ausente é o que permite acrescentar um parâmetro ajustável depois sem
    migrar as linhas antigas: um perfil gravado hoje continua carregando amanhã, com o
    valor do código no campo que ele não conhecia.
    """
    config = json.loads(bruto)
    if not isinstance(config, dict):
        raise ValueError("Configuração de perfil precisa ser um objeto JSON.")

    def caixas(chave: str, padrao: dict) -> dict[str, tuple[int, int, int, int]]:
        """As caixas gravadas SOBRE as do código, campo a campo.

        O merge é por CHAVE, e não pelo dicionário inteiro. A diferença só aparece no dia em
        que um campo novo entra em `CAMPOS`: o perfil gravado antes dele não o conhece, e
        substituir o dicionário inteiro devolveria uma configuração sem a ROI do campo novo.
        `mahu_ocr` indexa `perfil.rois[campo.key]` para todo campo, então isso vira KeyError —
        e a API responde 500 a toda foto até alguém regravar o perfil à mão.

        Foi exatamente o que aconteceu ao acrescentar `tt02`, `mt_tt_mahu_21` e
        `tt04_entalpia_sp`: o perfil semeado antes deles continuou ativo e derrubou a leitura.
        Com o merge por chave, um campo novo nasce com a ROI do código e o perfil gravado
        segue mandando em tudo que ele de fato configurou.
        """
        lidas = {
            key: tuple(int(coordenada) for coordenada in valor)
            for key, valor in config.get(chave, {}).items()
        }
        invalidas = [key for key, caixa in lidas.items() if len(caixa) != 4]
        if invalidas:
            raise ValueError(f"{chave} com formato inválido: {', '.join(sorted(invalidas))}.")
        return {**padrao, **lidas}  # type: ignore[return-value]

    rois = caixas("rois", ROIS_PADRAO)

    return PerfilOCR(
        id=id,
        rois=rois,
        ancoras=caixas("ancoras", ANCORAS_PADRAO),
        min_homography_inliers=int(
            config.get("min_homography_inliers", MIN_HOMOGRAPHY_INLIERS_PADRAO)
        ),
        min_variantes_concordando=int(
            config.get("min_variantes_concordando", MIN_VARIANTES_CONCORDANDO_PADRAO)
        ),
        min_confianca=float(config.get("min_confianca", MIN_CONFIANCA_PADRAO)),
        faixas_esperadas={
            key: (float(valor[0]), float(valor[1]))
            for key, valor in config.get("faixas_esperadas", {}).items()
        },
        casas_decimais={
            key: int(valor) for key, valor in config.get("casas_decimais", {}).items()
        },
    )


# --- Perfil ativo do processo -----------------------------------------------------------
# Carregado uma vez no boot. É um valor de processo e não um parâmetro implícito: quem lê
# uma foto de produção usa este; o avaliador passa o candidato explicitamente e não toca
# aqui. Sem essa separação, medir um candidato mudaria o que a API está servindo.
_ativo: PerfilOCR = PERFIL_DO_CODIGO


def perfil_ativo() -> PerfilOCR:
    return _ativo


def definir_perfil_ativo(perfil: PerfilOCR) -> None:
    global _ativo
    _ativo = perfil
