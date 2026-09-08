# bambu2centauri

Reaproveita um projeto `.3mf` da Bambu Lab (ou baixado do MakerWorld) na **Elegoo
Centauri Carbon** sem perder o que o autor do modelo ajustou.

## O problema

O Elegoo Slicer abre o `.3mf` da Bambu — os dois são forks do Orca —, mas ao abrir
ele aplica o preset dele por cima e sobrescreve, calado, ajustes de processo do
autor.

Medido num par real do mesmo modelo, salvo nas duas máquinas: das 149 diferenças
entre os dois arquivos, **67 eram só formato** (a Bambu multi-AMS guarda um valor
por extrusor, em lista de 4; a Centauri tem um só) e **82 eram mudança de valor de
verdade**. Parte dessas 82 é máquina, e está certo trocar — dialeto de G-code de
Marlin para Klipper, códigos de início e fim, área da mesa. A outra parte é o
trabalho do autor indo embora sem aviso:

| ajuste | autor | virou |
|---|---|---|
| `bottom_shell_thickness` | 0 | 0.6 |
| `elefant_foot_compensation` | 0.15 | 0.1 |
| `inner_wall_speed` | 300 | 200 |
| `internal_solid_infill_pattern` | zig-zag | monotonic |
| `ensure_vertical_shell_thickness` | enabled | ensure_all |

## Como resolve

O `project_settings.config` de saída é montado por escopo:

- **máquina** → sempre do *doador*, um `.3mf` que você mesmo salvou no Elegoo
  Slicer. É o que faz o arquivo imprimir na sua impressora.
- **filamento** → do doador por padrão, porque é o rolo que *você* vai usar
  (`--filamento-do-autor` inverte isso).
- **processo** → do autor. Paredes, preenchimento, costura, velocidades,
  suportes, altura de camada.

Por cima disso, o que o autor declarou ter mudado de propósito — o campo
`different_settings_to_system`, que o próprio arquivo carrega — é tratado como
intocável e nunca cede para o preset.

Duas correções que o formato exige: **aridade** (listas de 4 extrusores colapsam
para 1) e **forma** (o fork da Elegoo guarda algumas chaves como escalar onde a
Bambu usa lista de um). A saída copia a forma do doador, chave a chave.

**Não são tocados:** geometria, pintura de cor, pintura de suporte, modificadores
e ajustes por objeto. O arquivo de saída é o zip de origem inteiro com um único
membro reescrito.

## Uso

```
python bambu2centauri.py modelo_do_makerworld.3mf \
    --doador qualquer_projeto_meu_da_centauri.3mf \
    -o "modelo - centauri.3mf"
```

Opções: `--filamento-do-autor` para trazer também o perfil de filamento do autor,
`-v` para listar todos os ajustes preservados e não só os declarados.

O relatório sai na tela: o que foi preservado, o que foi trocado pela máquina, o
que era só formato, e um aviso quando um valor do autor passa do limite físico da
Centauri — nesse caso o valor é preservado mesmo assim e o aviso fica com você,
em vez de a ferramenta decidir escondido.

Só precisa de Python 3.8+ e da biblioteca padrão.

## Estado

Validado na estrutura: zip íntegro, todos os membros internos idênticos ao
original exceto o de configuração. Falta rodagem de verdade em mais modelos —
se algum abrir torto no Elegoo Slicer, o relatório com `-v` é o ponto de partida.
