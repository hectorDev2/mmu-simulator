#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════╗
║   SIMULADOR MMU - ALGORITMO OPTIMO - MEMORIA RAM REAL           ║
║   Usa ctypes para asignar marcos reales en tu RAM fisica        ║
║   Usa archivos temporales reales como almacenamiento en disco   ║
╚══════════════════════════════════════════════════════════════════╝

Requisitos: Python 3.8+  (sin dependencias externas)
Uso: python3 mmu_simulador.py [--frames N] [--auto]
  --frames N   numero de marcos fisicos (default: 1024 = 4 MB de RAM real)
  --auto       no espera ENTER entre pasos
"""

import ctypes
import os
import sys
import struct
import tempfile
import shutil
import argparse
import time
from typing import Optional, List, Dict, Tuple

# ─────────────────────────── COLORES ANSI ────────────────────────────────────
class C:
    RST   = "\033[0m";  BOLD  = "\033[1m";  DIM   = "\033[2m"
    RED   = "\033[91m"; GRN   = "\033[92m"; YEL   = "\033[93m"
    BLU   = "\033[94m"; MAG   = "\033[95m"; CYN   = "\033[96m"
    WHT   = "\033[97m"
    BGRED = "\033[41m"; BGGRN = "\033[42m"; BGYEL = "\033[43m"
    BGBLU = "\033[44m"; BGMAG = "\033[45m"; BGCYN = "\033[46m"

# ─────────────────────────── CONSTANTES ──────────────────────────────────────
PAGE_SIZE   = 4096          # 4 KB  (igual que x86/x86-64)
TLB_CAP     = 8             # entradas en el TLB
DISK_DIR    = ""            # se asigna al iniciar (tempdir real)

# ─────────────────────────── UTILIDADES ──────────────────────────────────────
def kb(n: int) -> str:
    if n >= 1024*1024: return f"{n//(1024*1024)} MB"
    if n >= 1024:      return f"{n//1024} KB"
    return f"{n} B"

def _fmt_addr(addr: int) -> str:
    return f"0x{addr:016X}"

# ─────────────────────────── MARCO FISICO REAL ───────────────────────────────

class MarcoFisico:
    """
    Marco de memoria fisica REAL.
    Usa ctypes.create_string_buffer() que asigna memoria real en el proceso.
    base_addr es la direccion REAL del sistema operativo (no simulada).
    """
    def __init__(self, num: int):
        self.num        = num
        # ── asignacion real de 4 KB en la RAM del proceso ──
        self._buffer    = ctypes.create_string_buffer(PAGE_SIZE)
        self.base_addr  = ctypes.addressof(self._buffer)   # direccion real del SO
        self.pagina     : Optional[int] = None
        self.libre      : bool = True

    # ── operaciones de lectura/escritura reales ───────────────────────────────
    def escribir(self, offset: int, datos: bytes):
        """Escribe bytes reales en la memoria fisica del marco."""
        n = min(len(datos), PAGE_SIZE - offset)
        ctypes.memmove(self.base_addr + offset, datos, n)

    def leer(self, offset: int, n: int = 8) -> bytes:
        """Lee bytes reales desde la memoria fisica del marco."""
        n = min(n, PAGE_SIZE - offset)
        return bytes((ctypes.c_uint8 * n).from_address(self.base_addr + offset))

    def volcar(self) -> bytes:
        """Retorna el contenido completo (4 KB) del marco."""
        return bytes((ctypes.c_uint8 * PAGE_SIZE).from_address(self.base_addr))

    def cargar_datos(self, datos: bytes):
        """Carga 4 KB desde bytes al marco."""
        ctypes.memmove(self.base_addr, datos[:PAGE_SIZE].ljust(PAGE_SIZE, b'\x00'), PAGE_SIZE)

    def limpiar(self):
        ctypes.memset(self.base_addr, 0, PAGE_SIZE)


# ─────────────────────────── DISCO (archivos reales) ─────────────────────────

class Disco:
    """
    Almacenamiento en disco simulado con archivos temporales REALES.
    Cada pagina virtual se guarda como un archivo .bin de 4 KB.
    """
    def __init__(self):
        global DISK_DIR
        DISK_DIR    = tempfile.mkdtemp(prefix="mmu_sim_disco_")
        self._pages : Dict[int, str] = {}   # pagina -> ruta de archivo
        self.lecturas   = 0
        self.escrituras = 0

    def _ruta(self, pagina: int) -> str:
        return os.path.join(DISK_DIR, f"pag_{pagina:06d}.bin")

    def _inicializar_pagina(self, pagina: int) -> bytes:
        """Genera contenido inicial de una pagina (patron reconocible)."""
        header = struct.pack(">I", pagina)          # numero de pagina
        body   = bytes([pagina % 256] * (PAGE_SIZE - 4))
        return header + body

    def guardar(self, pagina: int, datos: bytes):
        """Escribe 4 KB al archivo de disco real."""
        ruta = self._ruta(pagina)
        with open(ruta, 'wb') as f:
            f.write(datos[:PAGE_SIZE].ljust(PAGE_SIZE, b'\x00'))
        self._pages[pagina] = ruta
        self.escrituras += 1

    def cargar(self, pagina: int) -> bytes:
        """Lee 4 KB desde el archivo de disco real."""
        self.lecturas += 1
        ruta = self._ruta(pagina)
        if not os.path.exists(ruta):
            datos = self._inicializar_pagina(pagina)
            self.guardar(pagina, datos)
            self.escrituras -= 1   # no contar la inicializacion
            return datos
        with open(ruta, 'rb') as f:
            return f.read(PAGE_SIZE)

    def tamano_total(self) -> int:
        total = 0
        for ruta in self._pages.values():
            try: total += os.path.getsize(ruta)
            except: pass
        return total

    def limpiar(self):
        shutil.rmtree(DISK_DIR, ignore_errors=True)


# ─────────────────────────── RAM FISICA ──────────────────────────────────────

class RAM:
    """
    Memoria fisica compuesta de marcos REALES (ctypes).
    Al crear esta clase se reservan num_marcos * 4096 bytes de RAM real.
    """
    def __init__(self, num_marcos: int):
        self.num_marcos  = num_marcos
        print(f"  {C.CYN}[RAM] Asignando {num_marcos} marcos x {PAGE_SIZE} B "
              f"= {kb(num_marcos * PAGE_SIZE)} de RAM real...{C.RST}", flush=True)
        self.marcos = [MarcoFisico(i) for i in range(num_marcos)]
        # mostrar rango de direcciones reales asignadas
        addrs = [m.base_addr for m in self.marcos]
        print(f"  {C.GRN}[RAM] Asignado. Rango aprox: "
              f"{_fmt_addr(min(addrs))} - {_fmt_addr(max(addrs) + PAGE_SIZE)}{C.RST}")

    def marco_libre(self) -> Optional[int]:
        for m in self.marcos:
            if m.libre: return m.num
        return None

    def llena(self) -> bool:
        return self.marco_libre() is None

    def cargar(self, pagina: int, num_marco: int, datos: bytes):
        m = self.marcos[num_marco]
        m.cargar_datos(datos)
        m.pagina = pagina
        m.libre  = False

    def liberar(self, num_marco: int):
        m = self.marcos[num_marco]
        m.limpiar()
        m.pagina = None
        m.libre  = True

    def leer_marco(self, num_marco: int, offset: int = 0, n: int = 8) -> bytes:
        return self.marcos[num_marco].leer(offset, n)

    def escribir_marco(self, num_marco: int, offset: int, datos: bytes):
        self.marcos[num_marco].escribir(offset, datos)

    def volcar_marco(self, num_marco: int) -> bytes:
        return self.marcos[num_marco].volcar()

    def paginas_en_ram(self, tabla: Dict) -> List[int]:
        return [p for p, e in tabla.items() if e.presente]


# ─────────────────────────── TABLA DE PAGINAS ────────────────────────────────

class EntradaTabla:
    """
    PTE (Page Table Entry) - una fila de la tabla de paginas del SO.
    Bits de control tal como los maneja el hardware x86:
      P = presente (valid)   D = dirty (sucio)   R = referenciado
    """
    def __init__(self, pag: int):
        self.pag          = pag
        self.marco        : Optional[int] = None
        self.presente     : bool = False   # bit P
        self.sucio        : bool = False   # bit D
        self.referenciado : bool = False   # bit R


# ─────────────────────────── TLB ─────────────────────────────────────────────

class EntradaTLB:
    def __init__(self, pag: int, marco: int):
        self.pag   = pag
        self.marco = marco
        self.valida = True

class TLB:
    """
    Translation Lookaside Buffer - cache de hardware dentro de la MMU.
    Guarda las traducciones mas recientes (pag virtual -> marco fisico).
    Cuando una pagina es desalojada, su entrada se INVALIDA (TLB shootdown).
    Politica: FIFO simple.
    """
    def __init__(self, capacidad: int = TLB_CAP):
        self.capacidad = capacidad
        self.entradas  : List[EntradaTLB] = []
        self.aciertos  = 0
        self.fallos    = 0

    def buscar(self, pag: int) -> Optional[int]:
        for e in self.entradas:
            if e.valida and e.pag == pag:
                self.aciertos += 1
                return e.marco
        self.fallos += 1
        return None

    def agregar(self, pag: int, marco: int):
        for e in self.entradas:
            if e.pag == pag:
                e.marco = marco; e.valida = True; return
        if len(self.entradas) >= self.capacidad:
            out = self.entradas.pop(0)
            _ev(f"[TLB] FIFO: desalojando pag {out.pag} del TLB", C.YEL)
        self.entradas.append(EntradaTLB(pag, marco))

    def invalidar(self, pag: int):
        for e in self.entradas:
            if e.pag == pag:
                e.valida = False
                _ev(f"[TLB] TLB-shootdown: pag {pag} invalidada", C.YEL)
                return


# ─────────────────────────── ALGORITMO OPTIMO ────────────────────────────────

class Optimo:
    """
    Algoritmo de Belady (Optimo).
    Desaloja la pagina cuyo proximo acceso es el MAS LEJANO en el futuro.
    Si una pagina nunca se usa de nuevo -> candidata inmediata.
    Minimiza page faults (optimo teorico, irrealizable en produccion).
    """
    def __init__(self, cadena: List[int]):
        self.cadena = cadena

    def victima(self, en_ram: List[int], idx: int) -> Tuple[int, dict]:
        analisis = {}
        mas_lejano = -1
        vic = en_ram[0]
        for pag in en_ram:
            prox = float('inf')
            for i in range(idx + 1, len(self.cadena)):
                if self.cadena[i] == pag:
                    prox = i; break
            analisis[pag] = prox
            if prox > mas_lejano:
                mas_lejano = prox; vic = pag
        return vic, analisis


# ─────────────────────────── MMU ─────────────────────────────────────────────

_eventos : List[str] = []

def _ev(msg: str, color: str = ""):
    print(f"  {color}{msg}{C.RST}")
    _eventos.append(msg)


class MMU:
    """
    Memory Management Unit (hardware).
    Recibe una direccion virtual, la divide en (pagina, offset),
    busca en TLB, si falla consulta la tabla de paginas del SO,
    si la pagina no esta en RAM lanza un Page Fault.
    Devuelve la direccion fisica REAL (ctypes).
    """
    def __init__(self, ram: RAM, disco: Disco, tlb: TLB):
        self.ram    = ram
        self.disco  = disco
        self.tlb    = tlb
        self.tabla  : Dict[int, EntradaTabla] = {}
        # estadisticas
        self.accesos      = 0
        self.faults       = 0
        self.escr_disco   = 0

    def _pte(self, pag: int) -> EntradaTabla:
        if pag not in self.tabla:
            self.tabla[pag] = EntradaTabla(pag)
        return self.tabla[pag]

    def traducir(self, va: int, escritura: bool,
                 cadena: List[int], idx: int) -> int:
        """
        Traduce VA (virtual address) -> PA (physical address) real.
        Retorna la direccion real en el proceso (ctypes address).
        """
        self.accesos += 1
        pag    = va // PAGE_SIZE
        offset = va  % PAGE_SIZE

        _ev(f"[MMU] VA={_fmt_addr(va)}  =>  pag={pag}  offset=0x{offset:03X}", C.CYN)

        # ── 1. Buscar en TLB (cache de hardware) ─────────────────────────────
        marco = self.tlb.buscar(pag)

        if marco is not None:
            _ev(f"[TLB] HIT  pag {pag} -> marco {marco}  "
                f"(addr={_fmt_addr(self.ram.marcos[marco].base_addr)})", C.GRN)
            pte = self._pte(pag)
        else:
            _ev(f"[TLB] MISS -> consultando tabla de paginas en RAM...", C.RED)
            pte = self._pte(pag)

            # ── 2. Revisar bit de presencia ───────────────────────────────────
            if not pte.presente:
                self.faults += 1
                _ev(f"[PAGE FAULT]  pag {pag} ausente en RAM  (bit P=0)",
                    C.BGRED + C.WHT)
                marco = self._page_fault(pag, pte, cadena, idx, escritura)
            else:
                marco = pte.marco
                _ev(f"[Tabla de Paginas] pag {pag} -> marco {marco}  (P=1)", C.GRN)

            self.tlb.agregar(pag, marco)
            _ev(f"[TLB] cacheado: pag {pag} -> marco {marco}", C.CYN)

        # ── 3. Actualizar bits de control ─────────────────────────────────────
        pte.referenciado = True
        if escritura:
            pte.sucio = True
            # escribe un patron real a la memoria fisica
            payload = struct.pack(">IIQ", pag, offset, int(time.time_ns()))
            self.ram.escribir_marco(marco, offset, payload)
            _ev(f"[MMU] D=1 activado para pag {pag}  "
                f"(escritura real a addr={_fmt_addr(self.ram.marcos[marco].base_addr + offset)})",
                C.MAG)

        pa = self.ram.marcos[marco].base_addr + offset
        _ev(f"[MMU] PA real = {_fmt_addr(pa)}  "
            f"(base marco {marco} + offset 0x{offset:03X})", C.GRN)
        return pa

    def _page_fault(self, pag: int, pte: EntradaTabla,
                    cadena: List[int], idx: int, escritura: bool) -> int:
        """Rutina del SO para atender un page fault."""

        if not self.ram.llena():
            marco = self.ram.marco_libre()
            _ev(f"[RAM] marco libre: {marco}  "
                f"addr={_fmt_addr(self.ram.marcos[marco].base_addr)}", C.GRN)
        else:
            _ev(f"[RAM] MEMORIA LLENA ({self.ram.num_marcos} marcos)  "
                f"-> ejecutando Algoritmo Optimo...", C.BGRED + C.WHT)

            en_ram = self.ram.paginas_en_ram(self.tabla)
            opt    = Optimo(cadena)
            vic, analisis = opt.victima(en_ram, idx)

            _ev(f"[OPT] Analisis uso futuro (indice actual={idx}):", C.YEL)
            for p_an in sorted(analisis, key=lambda x: analisis[x], reverse=True):
                uso = analisis[p_an]
                tag = f" {C.BGMAG}{C.WHT}<-- VICTIMA{C.RST}" if p_an == vic else ""
                uso_s = f"idx {uso}" if uso != float('inf') else f"{C.RED}NUNCA{C.RST}"
                _ev(f"       pag {p_an:3d}: proximo uso en {uso_s}{tag}", C.YEL)

            vic_pte = self._pte(vic)
            marco   = vic_pte.marco

            if vic_pte.sucio:
                self.escr_disco += 1
                datos = self.ram.volcar_marco(marco)
                self.disco.guardar(vic, datos)
                _ev(f"[DISCO] pag {vic} SUCIA (D=1) -> "
                    f"escrita a disco ({kb(PAGE_SIZE)}) "
                    f"archivo={os.path.basename(self.disco._ruta(vic))}", C.RED)
            else:
                _ev(f"[DISCO] pag {vic} LIMPIA (D=0) -> descartada sin I/O", C.GRN)

            vic_pte.presente     = False
            vic_pte.marco        = None
            vic_pte.referenciado = False
            vic_pte.sucio        = False
            self.ram.liberar(marco)
            self.tlb.invalidar(vic)
            _ev(f"[RAM] pag {vic} desalojada del marco {marco}", C.YEL)

        # cargar pagina desde disco a marco real
        datos = self.disco.cargar(pag)
        self.ram.cargar(pag, marco, datos)
        pte.marco        = marco
        pte.presente     = True
        pte.referenciado = False
        pte.sucio        = escritura
        _ev(f"[DISCO->RAM] pag {pag} cargada "
            f"({kb(PAGE_SIZE)}) -> marco {marco}  "
            f"addr={_fmt_addr(self.ram.marcos[marco].base_addr)}", C.GRN)
        return marco


# ─────────────────────────── VISUALIZACION ───────────────────────────────────

def imprimir_estado(mmu: MMU, cadena: List[int], idx: int, paso: int):
    ancho = 68
    print(f"\n{C.BOLD}{C.BGBLU}{C.WHT} {'ESTADO DEL SISTEMA':^{ancho}} {C.RST}")

    # cadena de referencias
    print(f"\n{C.BOLD}Cadena de referencias:{C.RST}")
    trozos = []
    for i, p in enumerate(cadena):
        if   i == idx:          trozos.append(f"{C.BGMAG}{C.WHT}[{p}]{C.RST}")
        elif i < idx:           trozos.append(f"{C.DIM} {p} {C.RST}")
        else:                   trozos.append(f"{C.CYN} {p} {C.RST}")
    print("  " + " ".join(trozos))

    # RAM
    n_libre = sum(1 for m in mmu.ram.marcos if m.libre)
    n_ocup  = mmu.ram.num_marcos - n_libre
    print(f"\n{C.BOLD}RAM  ({mmu.ram.num_marcos} marcos reales x {kb(PAGE_SIZE)}):"
          f"  {C.GRN}{n_ocup} ocupados{C.RST}  {C.DIM}{n_libre} libres{C.RST}{C.BOLD}:{C.RST}")
    print(f"  {'Marco':<7} {'Pag':<6} {'Dir. fisica real':<20} "
          f"{'P':^3} {'D':^3} {'R':^3}  Primeros bytes (hex)")
    print(f"  {'─'*70}")
    for m in mmu.ram.marcos:
        if m.libre:
            print(f"  [{m.num:3d}]   {'─LIBRE─':<6} {_fmt_addr(m.base_addr):<20}")
        else:
            pte = mmu.tabla.get(m.pagina)
            P   = f"{C.GRN}1{C.RST}" if pte and pte.presente     else f"{C.RED}0{C.RST}"
            D   = f"{C.RED}1{C.RST}" if pte and pte.sucio         else f"{C.GRN}0{C.RST}"
            R   = f"{C.YEL}1{C.RST}" if pte and pte.referenciado  else "0"
            raw = m.leer(0, 8).hex(' ')
            tag = ""
            if pte and pte.sucio:        tag += f" {C.RED}[SUCIA]{C.RST}"
            if pte and pte.referenciado: tag += f" {C.YEL}[REF]{C.RST}"
            print(f"  [{m.num:3d}]   pag{m.pagina:<3} {_fmt_addr(m.base_addr):<20} "
                  f" {P}  {D}  {R}  {raw}{tag}")

    # TLB
    print(f"\n{C.BOLD}TLB  ({mmu.tlb.capacidad} entradas):{C.RST}")
    if not mmu.tlb.entradas:
        print(f"  {C.DIM}(vacio){C.RST}")
    for e in mmu.tlb.entradas:
        v = f"{C.GRN}VALIDA{C.RST}" if e.valida else f"{C.RED}INVAL {C.RST}"
        print(f"  [{v}]  pag {e.pag:3d} -> marco {e.marco:3d}  "
              f"addr={_fmt_addr(mmu.ram.marcos[e.marco].base_addr)}")

    # Tabla de paginas
    print(f"\n{C.BOLD}Tabla de Paginas (entradas activas):{C.RST}")
    print(f"  {'Pag':<5} {'Marco':<7} {'P':^3} {'D':^3} {'R':^3}  "
          f"{'Dir. fisica real':<20}  Archivo disco")
    print(f"  {'─'*65}")
    for pag in sorted(mmu.tabla):
        pte = mmu.tabla[pag]
        P   = f"{C.GRN}1{C.RST}" if pte.presente     else f"{C.RED}0{C.RST}"
        D   = f"{C.RED}1{C.RST}" if pte.sucio         else f"{C.GRN}0{C.RST}"
        R   = f"{C.YEL}1{C.RST}" if pte.referenciado  else "0"
        mar = str(pte.marco) if pte.marco is not None else "─"
        if pte.presente and pte.marco is not None:
            addr = _fmt_addr(mmu.ram.marcos[pte.marco].base_addr)
        else:
            addr = f"{C.DIM}en disco{C.RST}              "
        disco_f = os.path.basename(mmu.disco._ruta(pag)) if pag in mmu.disco._pages else "─"
        print(f"  {pag:<5} {mar:<7}  {P}  {D}  {R}  {addr}  {C.DIM}{disco_f}{C.RST}")

    # Estadisticas
    tot     = mmu.accesos
    tlb_tot = mmu.tlb.aciertos + mmu.tlb.fallos
    fp_pct  = mmu.faults / tot * 100 if tot else 0
    ht_pct  = mmu.tlb.aciertos / tlb_tot * 100 if tlb_tot else 0
    print(f"\n{C.BOLD}Estadisticas:{C.RST}")
    print(f"  Accesos totales   : {tot}")
    print(f"  Page Faults       : {C.RED}{mmu.faults}{C.RST}  ({fp_pct:.1f}%)")
    print(f"  TLB Hit Rate      : {C.GRN}{ht_pct:.1f}%{C.RST}  "
          f"({mmu.tlb.aciertos} hits / {tlb_tot} consultas)")
    print(f"  Lecturas disco    : {mmu.disco.lecturas}")
    print(f"  Escrituras disco  : {C.RED}{mmu.escr_disco}{C.RST}  "
          f"(paginas sucias desalojadas, {kb(mmu.escr_disco * PAGE_SIZE)} escritos)")
    print(f"  Disco usado       : {kb(mmu.disco.tamano_total())}  "
          f"en {DISK_DIR}")


def imprimir_cabecera(num_marcos: int):
    ram_real = num_marcos * PAGE_SIZE
    print(f"""
{C.BOLD}{C.CYN}╔══════════════════════════════════════════════════════════════════╗
║   SIMULADOR MMU - ALGORITMO OPTIMO - RAM REAL                   ║
╚══════════════════════════════════════════════════════════════════╝{C.RST}

{C.BOLD}Arquitectura simulada:{C.RST}
  Tamano de pagina    : {PAGE_SIZE} B  (4 KB, igual que x86/x86-64)
  Marcos fisicos      : {num_marcos}  ({kb(ram_real)} de RAM real asignada via ctypes)
  Capacidad TLB       : {TLB_CAP} entradas  (cache de hardware)
  Almacenamiento disco: archivos .bin reales en /tmp/

{C.BOLD}Glosario:{C.RST}
  {C.GRN}P=1{C.RST}  bit presencia  : pagina en RAM    |  {C.RED}P=0{C.RST}  pagina en disco
  {C.RED}D=1{C.RST}  bit sucio      : modificada       |  {C.GRN}D=0{C.RST}  limpia (sin I/O)
  {C.YEL}R=1{C.RST}  bit referencia : accedida         |  R=0   no accedida
  {C.GRN}TLB HIT{C.RST}   traduccion en cache (rapido)
  {C.RED}TLB MISS{C.RST}  consulta tabla en RAM (lento)
  {C.BGRED}{C.WHT}PAGE FAULT{C.RST} pagina ausente, SO carga desde disco (muy lento)
  {C.MAG}OPT{C.RST}       desaloja la pagina mas lejana en el futuro (Belady)
""")


# ─────────────────────────── SECUENCIA DE ACCESOS ────────────────────────────

def generar_accesos(num_marcos: int) -> List[Tuple[int, bool, str]]:
    """
    Genera una secuencia de accesos que demuestra:
    - Llenado gradual de la RAM
    - TLB hits y misses
    - Page faults con y sin reemplazo
    - Paginas sucias (D=1) que fuerzan escritura al disco
    - Decision del algoritmo optimo con analisis visible
    """
    # Las paginas van de 0 a (num_marcos + 4) para asegurar reemplazos
    M = num_marcos
    accesos = [
        # ── Fase 1: llenar la RAM ─────────────────────────────────────────────
        (0, False, "Cargar codigo del proceso (pag 0)"),
        (1, False, "Cargar segmento de datos  (pag 1)"),
        (2, True,  "Inicializar pila          (pag 2) -> D=1"),
        (3, False, "Cargar libreria dinamica  (pag 3)"),
        # ── Fase 2: TLB hits ──────────────────────────────────────────────────
        (0, False, "Releer codigo pag 0       -> TLB HIT"),
        (2, True,  "Modificar pila de nuevo   -> D=1, TLB HIT"),
        # ── Fase 3: RAM se llena, primer reemplazo ────────────────────────────
        (M, False, f"Nueva pag {M}  -> si RAM llena, OPT elige victima"),
        (1, True,  "Modificar datos pag 1     -> D=1"),
        # ── Fase 4: mas reemplazos, paginas sucias van al disco ───────────────
        (M+1, False, f"Nueva pag {M+1}  -> OPT puede elegir pag SUCIA (escritura disco)"),
        (3, True,   "Modificar libreria pag 3  -> D=1"),
        (M+2, False, f"Nueva pag {M+2}  -> analisis OPT con varias sucias"),
        # ── Fase 5: accesos repetidos (TLB hits, R=1) ─────────────────────────
        (0, False, "Acceso a codigo pag 0     -> posible TLB HIT"),
        (2, False, "Leer pila pag 2           -> bit R activado"),
        # ── Fase 6: nuevas paginas, mas reemplazos ────────────────────────────
        (M+3, False, f"Nueva pag {M+3}  -> reemplazo; OPT mira uso futuro"),
        (M+4, True,  f"Nueva pag {M+4}  -> escritura inmediata, D=1 al nacer"),
        (1, False,   "Leer datos pag 1 (usada pronto)"),
        (0, False,   "Codigo pag 0  -> confirmar TLB o recargar"),
        (M+3, True,  f"Modificar pag {M+3}  -> D=1"),
        (2, False,   "Pila pag 2  -> R activado de nuevo"),
        (M+5, False, f"Nueva pag {M+5}  -> ultimo reemplazo de la demo"),
    ]
    return accesos


# ─────────────────────────── PUNTO DE ENTRADA ────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Simulador MMU con RAM real")
    parser.add_argument("--frames", type=int, default=4,
                        help="Numero de marcos fisicos (default: 4 = 16 KB de RAM real). "
                             "Puedes usar 1024 para 4 MB, 262144 para 1 GB, etc.")
    parser.add_argument("--auto",   action="store_true",
                        help="Modo automatico: no espera ENTER entre pasos")
    parser.add_argument("--delay",  type=float, default=0.0,
                        help="Segundos entre pasos en modo auto (default: 0)")
    args = parser.parse_args()

    num_marcos = max(2, args.frames)
    imprimir_cabecera(num_marcos)

    # ── Inicializar hardware real ──────────────────────────────────────────────
    print(f"{C.BOLD}Inicializando hardware...{C.RST}")
    disco = Disco()
    print(f"  {C.GRN}[DISCO] directorio temporal: {DISK_DIR}{C.RST}")
    ram = RAM(num_marcos)
    tlb = TLB(TLB_CAP)
    mmu = MMU(ram, disco, tlb)
    print()

    accesos  = generar_accesos(num_marcos)
    cadena   = [a[0] for a in accesos]

    print(f"{C.BOLD}Cadena de referencias:{C.RST}  "
          + " -> ".join(str(p) for p in cadena))
    print(f"  {len(accesos)} accesos  |  {len(set(cadena))} paginas distintas  |  "
          f"{num_marcos} marcos en RAM\n")

    if not args.auto:
        input(f"{C.YEL}Presiona ENTER para iniciar (paso a paso)...{C.RST}\n")

    try:
        for paso, (pag, escritura, desc) in enumerate(accesos):
            va   = pag * PAGE_SIZE + (0x0A0 if escritura else 0x000)
            tipo = f"{C.RED}ESCRITURA{C.RST}" if escritura else f"{C.GRN}LECTURA {C.RST}"

            print(f"\n{'═'*70}")
            print(f"{C.BOLD}PASO {paso+1:02d}/{len(accesos)}:  {desc}{C.RST}")
            print(f"  Tipo          : {tipo}")
            print(f"  Dir. virtual  : {_fmt_addr(va)}")
            print(f"  Pagina virtual: {pag}  (VA {_fmt_addr(va)} / 0x{PAGE_SIZE:04X})")
            print(f"{'─'*70}")

            pa = mmu.traducir(va, escritura, cadena, paso)

            print(f"\n  {C.BOLD}{C.GRN}Direccion fisica REAL: {_fmt_addr(pa)}{C.RST}")

            imprimir_estado(mmu, cadena, paso, paso + 1)

            if paso < len(accesos) - 1:
                if args.auto:
                    if args.delay > 0:
                        time.sleep(args.delay)
                else:
                    input(f"\n{C.DIM}  [ENTER -> paso {paso+2}/{len(accesos)}]{C.RST}")

        # ── Resumen final ──────────────────────────────────────────────────────
        print(f"\n{'═'*70}")
        print(f"{C.BOLD}{C.BGGRN}{C.WHT} {'SIMULACION COMPLETADA':^68} {C.RST}")
        print(f"{'═'*70}\n")

        tot    = mmu.accesos
        tl_tot = mmu.tlb.aciertos + mmu.tlb.fallos
        print(f"  RAM asignada (real)    : {kb(num_marcos * PAGE_SIZE)}"
              f"  ({num_marcos} marcos x {kb(PAGE_SIZE)})")
        print(f"  Accesos totales        : {tot}")
        print(f"  Page Faults            : {C.RED}{mmu.faults}{C.RST}  "
              f"({mmu.faults/tot*100:.1f}%)")
        print(f"  TLB Hit Rate           : {C.GRN}{mmu.tlb.aciertos/tl_tot*100:.1f}%{C.RST}")
        print(f"  Lecturas de disco      : {mmu.disco.lecturas}")
        print(f"  Escrituras a disco     : {C.RED}{mmu.escr_disco}{C.RST}  "
              f"(solo paginas con D=1)")
        print(f"  Datos escritos disco   : {kb(mmu.escr_disco * PAGE_SIZE)}")
        print(f"  Archivos en disco sim  : {DISK_DIR}\n")

        print(f"{C.BOLD}Conceptos demostrados con memoria REAL:{C.RST}")
        print(f"  {C.GRN}[v]{C.RST} Marcos fisicos reales asignados via ctypes en tu RAM")
        print(f"  {C.GRN}[v]{C.RST} Direcciones fisicas reales del proceso (no simuladas)")
        print(f"  {C.GRN}[v]{C.RST} Escrituras/lecturas reales de bytes en esas direcciones")
        print(f"  {C.GRN}[v]{C.RST} Archivos .bin reales en /tmp como almacenamiento de disco")
        print(f"  {C.GRN}[v]{C.RST} Paginacion: VA = (pagina * {PAGE_SIZE}) + offset -> PA real")
        print(f"  {C.GRN}[v]{C.RST} TLB: cache de traducciones con hits/misses/shootdown")
        print(f"  {C.GRN}[v]{C.RST} Bit P: presencia en RAM vs disco")
        print(f"  {C.GRN}[v]{C.RST} Bit D: paginas sucias fuerzan I/O real al disco")
        print(f"  {C.GRN}[v]{C.RST} Bit R: hardware activa en cada acceso")
        print(f"  {C.GRN}[v]{C.RST} Page Fault: carga real de datos desde archivo a RAM")
        print(f"  {C.GRN}[v]{C.RST} Algoritmo Optimo: minimo de page faults posible\n")

    finally:
        disco.limpiar()
        print(f"{C.DIM}Archivos temporales de disco eliminados.{C.RST}\n")


if __name__ == "__main__":
    main()
