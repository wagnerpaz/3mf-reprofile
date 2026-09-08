#!/usr/bin/env python3
"""
bambu2centauri — reaproveita um projeto .3mf da Bambu (ou do MakerWorld) na
Elegoo Centauri Carbon SEM perder o que o autor ajustou.

O problema que isto resolve
---------------------------
O Elegoo Slicer abre o .3mf da Bambu (os dois são forks do Orca), mas ao abrir
ele aplica o preset dele por cima e sobrescreve, calado, ajustes de processo do
autor. Medido num par real do mesmo modelo (X1 Carbon -> Centauri):
casca inferior 0 -> 0.6, pé de elefante 0.15 -> 0.1, parede interna 300 -> 200
mm/s, preenchimento sólido zig-zag -> monotônico, tempos de ventoinha alterados.
Nada disso foi perguntado.

A ideia
-------
Montar o `project_settings.config` de saída assim:

  máquina   -> SEMPRE do doador (um .3mf que você mesmo salvou na Centauri).
               É o que faz o arquivo imprimir na sua impressora: dialeto de
               G-code, códigos de início/fim, área da mesa, limites de aceleração.
  filamento -> do doador por padrão (é o rolo que VOCÊ vai usar), salvo
               --filamento-do-autor.
  processo  -> do AUTOR. É o que você quer preservar: paredes, preenchimento,
               costura, velocidades, suportes, camada.

E, por cima de tudo, o que o autor declarou ter mudado de propósito — o campo
`different_settings_to_system` do arquivo de origem — é tratado como intocável.

Duas correções que o formato exige
----------------------------------
1. Aridade: a Bambu multi-AMS guarda valor por extrusor (lista de 4); a Centauri
   tem um só (lista de 1). Sem colapsar, 67 das 149 diferenças de um par real
   eram só isso — ruído, não mudança.
2. Forma: o fork da Elegoo guarda algumas chaves como escalar onde a Bambu usa
   lista de um. A saída copia a forma do doador, chave a chave.

O que NÃO é tocado: geometria, pintura de cor, pintura de suporte, modificadores
e ajustes por objeto. O arquivo de saída é o zip de origem inteiro com um único
membro reescrito.

Uso:
    python bambu2centauri.py origem.3mf --doador meu_centauri.3mf -o saida.3mf
"""

import argparse
import json
import shutil
import sys
import zipfile
from pathlib import Path

CONFIG = "Metadata/project_settings.config"

# ---------------------------------------------------------------------------
# Classificação de chaves.
#
# Não existe marcação de escopo dentro do arquivo, então a separação é por nome.
# Regra: o que casar com MAQUINA ou FILAMENTO vem do doador; TODO o resto é
# tratado como processo e vem do autor. Chaves de processo que eu não conheça
# entram nessa vala comum de propósito — preservar demais é o objetivo — mas o
# relatório lista todas elas para você conferir em vez de confiar.
# ---------------------------------------------------------------------------

MAQUINA_PREFIXOS = (
    "machine_", "printer_", "printable_", "printhost_", "extruder_",
    "print_host", "host_type", "bed_", "gcode_", "z_hop",
    "retraction_", "retract_", "wipe_distance", "wipe",
    "nozzle_diameter", "nozzle_type", "nozzle_volume", "nozzle_height",
    "nozzle_hrc", "auxiliary_fan", "support_air_filtration",
    "use_relative_e_distances", "use_firmware_retraction", "silent_mode",
    "single_extruder_multi_material", "purge_in_prime_tower",
    "best_object_pos", "head_wrap_detect_zone",
)

MAQUINA_EXATAS = {
    "before_layer_change_gcode", "layer_change_gcode", "change_filament_gcode",
    "machine_start_gcode", "machine_end_gcode", "machine_pause_gcode",
    "template_custom_gcode", "time_lapse_gcode", "printing_by_object_gcode",
    "bed_exclude_area", "curr_bed_type", "filename_format", "thumbnails",
    "default_print_profile", "default_filament_profile", "printer_technology",
    "inherits", "inherits_group", "from", "version", "name", "is_custom_defined",
    "upward_compatible_machine", "支持的打印机", "print_settings_id",
    "printer_settings_id", "printer_model", "printer_variant",
    "different_settings_to_system",
    # Listas de compatibilidade: se vierem do autor, o Elegoo Slicer passa a
    # considerar o perfil incompatível com a sua própria impressora e ignora o
    # arquivo. Sempre do doador.
    "print_compatible_printers", "filament_compatible_printers",
    "compatible_printers", "compatible_printers_condition",
    "compatible_prints", "compatible_prints_condition",
}

FILAMENTO_PREFIXOS = (
    "filament_", "nozzle_temperature", "chamber_temp", "cool_plate_temp",
    "eng_plate_temp", "hot_plate_temp", "textured_plate_temp",
    "supertack_plate_temp", "fan_", "overhang_fan_", "close_fan_",
    "additional_cooling_fan_speed", "slow_down_", "reduce_fan_stop_start_freq",
    "enable_overhang_bridge_fan", "complete_print_exhaust_fan_speed",
    "during_print_exhaust_fan_speed", "activate_air_filtration",
    "support_material_interface_fan_speed", "enable_pressure_advance",
    "pressure_advance", "temperature_vitrification", "required_nozzle_HRC",
    "impact_strength_z", "activate_chamber_temp_control",
)

FILAMENTO_EXATAS = {"filament_settings_id", "filament_ids", "filament_colour",
                    "default_filament_colour", "flush_volumes_matrix",
                    "flush_volumes_vector", "flush_multiplier"}


def escopo(chave: str) -> str:
    if chave in MAQUINA_EXATAS or chave.startswith(MAQUINA_PREFIXOS):
        return "maquina"
    if chave in FILAMENTO_EXATAS or chave.startswith(FILAMENTO_PREFIXOS):
        return "filamento"
    return "processo"


def ler_config(caminho: Path) -> dict:
    with zipfile.ZipFile(caminho) as z:
        if CONFIG not in z.namelist():
            raise SystemExit(
                f"{caminho.name}: não tem {CONFIG} — é um .3mf só de malha, "
                "sem ajustes do autor para preservar."
            )
        return json.loads(z.read(CONFIG).decode("utf-8"))


def ajustar_forma(valor, molde):
    """Devolve `valor` na forma de `molde` (escalar x lista, e aridade)."""
    if isinstance(molde, list):
        itens = valor if isinstance(valor, list) else [valor]
        if not itens:
            return list(molde)
        # Multi-extrusor -> extrusor único: se o autor tinha o mesmo valor em
        # todos, é um valor só; se tinha valores diferentes, o primeiro é o do
        # extrusor primário, que é o que a Centauri usa.
        if len(molde) == 1:
            return [itens[0]]
        return (itens + [itens[-1]] * len(molde))[: len(molde)]
    if isinstance(valor, list):
        return valor[0] if valor else molde
    return valor


def declaradas_pelo_autor(origem: dict) -> set:
    """As chaves que o autor mudou de propósito, segundo o próprio arquivo."""
    campo = origem.get("different_settings_to_system", [])
    if isinstance(campo, str):
        campo = [campo]
    chaves = set()
    for bloco in campo:
        for parte in str(bloco).split(";"):
            parte = parte.strip()
            if parte:
                chaves.add(parte)
    return chaves


def converter(origem_p: Path, doador_p: Path, saida_p: Path,
              filamento_do_autor: bool) -> dict:
    origem = ler_config(origem_p)
    doador = ler_config(doador_p)

    intocaveis = declaradas_pelo_autor(origem)
    saida = dict(doador)

    relatorio = {
        "origem": origem.get("printer_model", "?"),
        "doador": doador.get("printer_model", "?"),
        "intocaveis": sorted(intocaveis),
        "preservadas": [],
        "so_forma": [],
        "da_maquina": [],
        "do_doador_filamento": [],
        "ignoradas_nao_existem_no_doador": [],
        "avisos": [],
    }

    for chave, valor_autor in origem.items():
        if chave not in doador:
            relatorio["ignoradas_nao_existem_no_doador"].append(chave)
            continue

        esc = escopo(chave)
        forcado = chave in intocaveis

        if esc == "maquina" and not forcado:
            relatorio["da_maquina"].append(chave)
            continue
        if esc == "filamento" and not (forcado or filamento_do_autor):
            relatorio["do_doador_filamento"].append(chave)
            continue

        novo = ajustar_forma(valor_autor, doador[chave])
        if novo == doador[chave]:
            relatorio["so_forma"].append(chave)
        else:
            relatorio["preservadas"].append(
                {"chave": chave, "de": doador[chave], "para": novo,
                 "declarada_pelo_autor": forcado}
            )
        saida[chave] = novo

    # Alerta de limite físico: velocidade do autor acima do que a máquina aceita.
    teto = doador.get("machine_max_speed_x") or doador.get("machine_max_speed_e")
    try:
        teto = float(teto[0] if isinstance(teto, list) else teto)
    except (TypeError, ValueError, IndexError):
        teto = None
    if teto:
        for item in relatorio["preservadas"]:
            if not item["chave"].endswith("_speed"):
                continue
            try:
                v = float(str(item["para"][0] if isinstance(item["para"], list)
                              else item["para"]).rstrip("%"))
            except ValueError:
                continue
            if v > teto:
                relatorio["avisos"].append(
                    f"{item['chave']} = {v} está acima do limite da máquina "
                    f"({teto}). Preservei o valor do autor, mas confira."
                )

    # O arquivo de saída é o zip de origem inteiro — geometria, pintura de cor,
    # pintura de suporte e ajustes por objeto passam intactos — com um único
    # membro reescrito.
    shutil.copyfile(origem_p, saida_p)
    _reescrever_membro(saida_p, CONFIG, json.dumps(saida, ensure_ascii=False,
                                                   indent=4).encode("utf-8"))
    return relatorio


def _reescrever_membro(zip_path: Path, membro: str, conteudo: bytes) -> None:
    tmp = zip_path.with_suffix(".tmp3mf")
    with zipfile.ZipFile(zip_path) as origem, \
            zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as destino:
        for info in origem.infolist():
            dados = conteudo if info.filename == membro else origem.read(info.filename)
            destino.writestr(info, dados)
    tmp.replace(zip_path)


def imprimir_relatorio(r: dict, verboso: bool) -> None:
    print(f"\n  origem : {r['origem']}")
    print(f"  doador : {r['doador']}")
    print(f"\n  o autor declarou ter mudado de propósito ({len(r['intocaveis'])}):")
    for c in r["intocaveis"]:
        print(f"      {c}")
    print(f"\n  ajustes do autor preservados : {len(r['preservadas'])}")
    print(f"  já eram iguais / só forma    : {len(r['so_forma'])}")
    print(f"  trocados pela sua máquina    : {len(r['da_maquina'])}")
    print(f"  filamento vindo do doador    : {len(r['do_doador_filamento'])}")
    if r["ignoradas_nao_existem_no_doador"]:
        print(f"  chaves da origem sem par no doador (ignoradas): "
              f"{len(r['ignoradas_nao_existem_no_doador'])}")

    destaques = [p for p in r["preservadas"] if p["declarada_pelo_autor"]]
    if destaques:
        print("\n  os intocáveis, valor a valor:")
        for p in destaques:
            print(f"      {p['chave']}: {p['de']} -> {p['para']}")

    if verboso and r["preservadas"]:
        print("\n  todos os ajustes preservados:")
        for p in r["preservadas"]:
            print(f"      {p['chave']}: {p['de']} -> {p['para']}")

    for aviso in r["avisos"]:
        print(f"\n  [AVISO] {aviso}")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Reaproveita um .3mf da Bambu/MakerWorld na Elegoo Centauri "
                    "Carbon preservando os ajustes do autor.")
    ap.add_argument("origem", type=Path, help="o .3mf da Bambu / MakerWorld")
    ap.add_argument("--doador", type=Path, required=True,
                    help="um .3mf que VOCÊ salvou no Elegoo Slicer; é dele que "
                         "sai o perfil da máquina")
    ap.add_argument("-o", "--saida", type=Path,
                    help="arquivo de saída (padrão: <origem> - centauri.3mf)")
    ap.add_argument("--filamento-do-autor", action="store_true",
                    help="também copia o perfil de filamento do autor (por "
                         "padrão vem do doador, que é o rolo que você vai usar)")
    ap.add_argument("-v", "--verboso", action="store_true",
                    help="lista todos os ajustes preservados, não só os "
                         "declarados pelo autor")
    args = ap.parse_args()

    if not args.origem.exists():
        print(f"não achei {args.origem}", file=sys.stderr)
        return 1
    if not args.doador.exists():
        print(f"não achei o doador {args.doador}", file=sys.stderr)
        return 1

    saida = args.saida or args.origem.with_name(
        f"{args.origem.stem} - centauri.3mf")
    r = converter(args.origem, args.doador, saida, args.filamento_do_autor)
    imprimir_relatorio(r, args.verboso)
    print(f"\n  escrito: {saida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
