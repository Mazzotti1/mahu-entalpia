# Carta Psicrométrica ASHRAE

## Requisitos

- Python 3.11+ instalado

## Como iniciar

1. Instale as dependências do backend:
   Abrir terminal CTRL + J

```bash
python -m pip install -r backend/requirements.txt
```

2. Inicie a API:

```bash
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

3. Abra o frontend no navegador:

- Abra o arquivo `index.html` na raiz do projeto.

## Pronto

Com a API rodando, a página carrega os pontos automaticamente e desenha a carta.

## Leitura do monitor MAHU pela câmera

O botão **Capturar monitor MAHU** abre a câmera no navegador, captura o quadro e envia a
imagem para `POST /api/mahu/ler`. O backend recorta os campos do painel, roda OCR e
devolve cada valor com sua confiança. A carta só é redesenhada depois que os valores são
confirmados no formulário de conferência, via `POST /api/mahu/simulacao`.

Observações práticas:

- A primeira leitura baixa os modelos do easyocr (~80 MB). Cada leitura roda em CPU e leva
  cerca de 20 s.
- `getUserMedia` exige contexto seguro. `file://`, `http://localhost` e HTTPS funcionam; se
  a câmera não estiver disponível, o botão cai no seletor de arquivos.
- Servindo a página por HTTP, use uma das portas liberadas no CORS de `backend/main.py`
  (8080 ou 5500) ou acrescente a sua.

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

- **P2 não usa a entalpia.** A entrada do planejamento (`docs/backend.md` §4 e §6: TBS 12,20
  com h = 36,20 kJ/kg) é termodinamicamente impossível: exigiria W = 9,48 g/kg contra
  W_sat(12,20 °C) = 8,85 g/kg, ou seja UR de 107%. A API rejeita essa combinação com
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
2,5:1 da tela). Antes de recortar, procura o quadrilátero da tela no quadro e aplica
correção de perspectiva — inclusive escolhendo o quadrilátero *aninhado* quando existe, que
é a tela dentro da moldura do monitor. Sem tela identificada, assume que a foto já é um
recorte dela e apenas redimensiona.

Cada campo é lido em 5 variantes de pré-processamento e o valor vence por votação. Como o
painel sempre mostra duas casas decimais, uma leitura sem separador é reconstruída
("870" → 8,70), mas nunca recebe status `ok`: `220` e `2120` reconstroem para 2,20 e 21,20,
ambos plausíveis para uma temperatura, e só quem olha a foto sabe qual é. Por isso a
conferência manual existe — a acurácia medida sobre `docs/foto do mahu.png` e três versões
com perspectiva sintética é de 23 acertos em 24 campos obrigatórios.

Ao ajustar ROIs, valide contra imagens com perspectiva e não só contra a foto de
referência: a retificação deixa um desvio residual de alguns pixels no espaço canônico, e
uma ROI ajustada com folga zero na referência erra o campo nas demais.
