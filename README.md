# 3mf-reprofile

Troca o perfil de máquina de um projeto `.3mf` **sem perder o que o autor do
modelo ajustou**.

Funciona com qualquer fatiador da família Orca — OrcaSlicer, Bambu Studio, Elegoo
Slicer, Creality Print, Anycubic, Qidi, Snapmaker —, porque todos guardam os
ajustes no mesmo lugar dentro do 3MF. **Não** funciona com PrusaSlicer nem Cura,
que usam outra estrutura.

## O problema

Seu fatiador abre o `.3mf` que veio do MakerWorld, mas ao abrir aplica o preset
dele por cima e sobrescreve, calado, ajustes de processo do autor.

Medido num par real do mesmo modelo, salvo em duas máquinas (Bambu X1 Carbon e
Elegoo Centauri Carbon): das 149 diferenças entre os dois arquivos, **67 eram só
formato** (a máquina multi-extrusor guarda um valor por extrusor, em lista de 4;
a de bico único guarda lista de 1) e **82 eram mudança de valor de verdade**.
Parte dessas 82 é máquina, e está certo trocar — dialeto de G-code de Marlin para
Klipper, códigos de início e fim, área da mesa. A outra parte é o trabalho do
autor indo embora sem aviso:

| ajuste | autor | virou |
|---|---|---|
| `bottom_shell_thickness` | 0 | 0.6 |
| `elefant_foot_compensation` | 0.15 | 0.1 |
| `inner_wall_speed` | 300 | 200 |
| `internal_solid_infill_pattern` | zig-zag | monotonic |
| `ensure_vertical_shell_thickness` | enabled | ensure_all |

## Como resolve

O `project_settings.config` de saída é montado por escopo:

- **máquina** → sempre do *doador*, um `.3mf` que você mesmo salvou no seu
  fatiador. É o que faz o arquivo imprimir na sua impressora.
- **filamento** → do doador por padrão, porque é o rolo que *você* vai usar
  (`--filamento-do-autor` inverte isso).
- **processo** → do autor. Paredes, preenchimento, costura, velocidades,
  suportes, altura de camada.

Por cima disso, o que o autor declarou ter mudado de propósito — o campo
`different_settings_to_system`, que o próprio arquivo carrega — é tratado como
intocável e nunca cede para o preset.

Duas correções que o formato exige: **aridade** (listas por extrusor colapsam
para o número de extrusores da máquina de destino) e **forma** (alguns forks
guardam certas chaves como escalar onde outros usam lista de um). A saída copia a
forma do doador, chave a chave.

**Não são tocados:** geometria, pintura de cor, pintura de suporte, modificadores
e ajustes por objeto. O arquivo de saída é o zip de origem inteiro com um único
membro reescrito.

## Uso

```
python reprofile_3mf.py modelo_do_makerworld.3mf \
    --doador qualquer_projeto_meu.3mf \
    -o "modelo - minha impressora.3mf"
```

Opções: `--filamento-do-autor` para trazer também o perfil de filamento do autor,
`-v` para listar todos os ajustes preservados e não só os declarados.

O relatório sai na tela: o que foi preservado, o que foi trocado pela máquina, o
que era só formato, e um aviso quando um valor do autor passa do limite físico da
sua máquina — nesse caso o valor é preservado mesmo assim e o aviso fica com
você, em vez de a ferramenta decidir escondido.

Só precisa de Python 3.8+ e da biblioteca padrão.

## Estado

Testado no caminho Bambu Lab → Elegoo Centauri Carbon: zip íntegro, todos os
membros internos idênticos ao original exceto o de configuração, 27 ajustes do
autor preservados. Os outros fatiadores da família devem funcionar pelo mesmo
mecanismo, mas ainda não foram rodados — se algum abrir torto, o relatório com
`-v` é o ponto de partida.
