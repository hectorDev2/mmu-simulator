#!/usr/bin/env python3
"""
MMU Simulator - Interfaz Web Interactiva
=========================================
Simula el MMU, TLB, Tabla de Paginas y Algoritmo Optimo de Belady.
Usa procesos REALES del sistema (Chrome, Safari, etc.) como carga.
Asigna marcos de memoria REAL con ctypes.

Instalacion:
    pip install flask psutil

Uso:
    python3 mmu_gui.py
    Abrir navegador en: http://localhost:5050
"""

import ctypes, os, sys, json, time, random, struct, threading, shutil, tempfile
from typing import Optional, List, Dict, Tuple, Any

# ── Auto-instalar dependencias ────────────────────────────────────────────────
for _pkg in ("flask", "psutil"):
    try:
        __import__(_pkg)
    except ImportError:
        print(f"Instalando {_pkg}...")
        os.system(f"{sys.executable} -m pip install {_pkg} -q")

from flask import Flask, jsonify, request
import psutil

# ─────────────────────── CONSTANTES ──────────────────────────────────────────
PAGE_SIZE = 4096

COLORES_PROCESO = {
    "chrome":    "#4285F4", "chromium": "#4285F4", "google":  "#4285F4",
    "safari":    "#FF6B35",
    "firefox":   "#FF9500",
    "figma":     "#A259FF",
    "code":      "#0078D4", "cursor":   "#0078D4", "vscode":  "#0078D4",
    "node":      "#68A063",
    "python":    "#FFD43B",
    "terminal":  "#2D9436", "iterm":    "#2D9436", "zsh":     "#2D9436",
    "blender":   "#F5792A",
    "slack":     "#E01E5A",
    "spotify":   "#1DB954",
    "zoom":      "#2D8CFF",
    "discord":   "#5865F2",
}
PALETA = [
    "#4285F4","#FF6B35","#A259FF","#2D9436",
    "#FF9500","#E01E5A","#1DB954","#00BCD4",
    "#FF5722","#9C27B0","#FFD43B","#5865F2",
]

def color_proceso(nombre: str, idx: int) -> str:
    nl = nombre.lower()
    for k, c in COLORES_PROCESO.items():
        if k in nl:
            return c
    return PALETA[idx % len(PALETA)]

# ─────────────────────── MARCO FISICO REAL ───────────────────────────────────
class MarcoFisico:
    """4 KB de RAM real asignados con ctypes."""
    def __init__(self, num: int):
        self.num      = num
        self._buf     = ctypes.create_string_buffer(PAGE_SIZE)
        self.base     = ctypes.addressof(self._buf)   # direccion real del OS
        self.pagina   : Optional[str] = None           # "proc_ID:pag_num"
        self.libre    = True

    def escribir(self, offset: int, datos: bytes):
        n = min(len(datos), PAGE_SIZE - offset)
        ctypes.memmove(self.base + offset, datos, n)

    def leer(self, offset: int, n: int = 8) -> bytes:
        return bytes((ctypes.c_uint8 * min(n, PAGE_SIZE - offset))
                     .from_address(self.base + offset))

    def volcar(self) -> bytes:
        return bytes((ctypes.c_uint8 * PAGE_SIZE).from_address(self.base))

    def cargar(self, datos: bytes):
        ctypes.memmove(self.base, datos[:PAGE_SIZE].ljust(PAGE_SIZE, b"\x00"), PAGE_SIZE)

    def limpiar(self):
        ctypes.memset(self.base, 0, PAGE_SIZE)

# ─────────────────────── DISCO REAL ──────────────────────────────────────────
class Disco:
    def __init__(self):
        self.dir     = tempfile.mkdtemp(prefix="mmu_sim_")
        self._archivos: Dict[str, str] = {}
        self.lecturas = 0
        self.escrituras = 0

    def _ruta(self, llave: str) -> str:
        safe = llave.replace(":", "_").replace("/", "_")
        return os.path.join(self.dir, f"{safe}.bin")

    def _init_datos(self, llave: str) -> bytes:
        h = struct.pack(">I", hash(llave) & 0xFFFFFFFF)
        return h + bytes([(hash(llave) + i) % 256 for i in range(PAGE_SIZE - 4)])

    def guardar(self, llave: str, datos: bytes):
        ruta = self._ruta(llave)
        with open(ruta, "wb") as f:
            f.write(datos[:PAGE_SIZE].ljust(PAGE_SIZE, b"\x00"))
        self._archivos[llave] = ruta
        self.escrituras += 1

    def cargar(self, llave: str) -> bytes:
        self.lecturas += 1
        ruta = self._ruta(llave)
        if not os.path.exists(ruta):
            datos = self._init_datos(llave)
            self.guardar(llave, datos)
            self.escrituras -= 1
            return datos
        with open(ruta, "rb") as f:
            return f.read(PAGE_SIZE)

    def limpiar(self):
        shutil.rmtree(self.dir, ignore_errors=True)

# ─────────────────────── PROCESO SIMULADO ────────────────────────────────────
class ProcSim:
    """Representa un proceso del sistema como carga de trabajo."""
    def __init__(self, pid: int, nombre: str, mem_mb: float, color: str, icono: str):
        self.pid    = pid
        self.nombre = nombre
        self.mem_mb = mem_mb
        self.color  = color
        self.icono  = icono
        # numero de paginas virtuales proporcional a la memoria
        self.num_paginas = max(4, min(20, int(mem_mb / 50)))
        self.paginas = [f"P{pid}:{i}" for i in range(self.num_paginas)]

# ─────────────────────── TLB ─────────────────────────────────────────────────
class EntradaTLB:
    def __init__(self, llave: str, marco: int):
        self.llave = llave
        self.marco = marco
        self.valida = True

class TLB:
    def __init__(self, cap: int = 8):
        self.cap      = cap
        self.entradas : List[EntradaTLB] = []
        self.aciertos = 0
        self.fallos   = 0

    def buscar(self, llave: str) -> Optional[int]:
        for e in self.entradas:
            if e.valida and e.llave == llave:
                self.aciertos += 1
                return e.marco
        self.fallos += 1
        return None

    def agregar(self, llave: str, marco: int):
        for e in self.entradas:
            if e.llave == llave:
                e.marco = marco; e.valida = True; return
        if len(self.entradas) >= self.cap:
            self.entradas.pop(0)
        self.entradas.append(EntradaTLB(llave, marco))

    def invalidar(self, llave: str):
        for e in self.entradas:
            if e.llave == llave:
                e.valida = False; return

    def to_list(self) -> List[dict]:
        return [{"llave": e.llave, "marco": e.marco, "valida": e.valida}
                for e in self.entradas]

# ─────────────────────── ENTRADA TABLA DE PAGINAS ────────────────────────────
class PTE:
    def __init__(self, llave: str):
        self.llave      = llave
        self.marco      : Optional[int] = None
        self.presente   = False   # bit P
        self.sucio      = False   # bit D
        self.referencia = False   # bit R

# ─────────────────────── ALGORITMO OPTIMO ────────────────────────────────────
class Optimo:
    def __init__(self, cadena: List[str]):
        self.cadena = cadena

    def elegir_victima(self, en_ram: List[str], idx: int) -> Tuple[str, Dict]:
        analisis: Dict[str, Any] = {}
        mas_lejano = -1
        victima = en_ram[0]
        for llave in en_ram:
            prox = float("inf")
            for i in range(idx + 1, len(self.cadena)):
                if self.cadena[i] == llave:
                    prox = i; break
            analisis[llave] = {"prox": prox, "es_victima": False}
            if prox > mas_lejano:
                mas_lejano = prox; victima = llave
        analisis[victima]["es_victima"] = True
        return victima, analisis

# ─────────────────────── MOTOR DE SIMULACION ─────────────────────────────────
class Motor:
    def __init__(self):
        self.lock     = threading.Lock()
        self.procesos : List[ProcSim] = []
        self.cadena   : List[str]     = []   # "P{pid}:{pag}"
        self.acceso_meta: List[dict]  = []   # info de cada acceso
        self.num_marcos = 6
        self.ram    : List[MarcoFisico] = []
        self.disco  : Optional[Disco]   = None
        self.tlb    : Optional[TLB]     = None
        self.tabla  : Dict[str, PTE]    = {}
        self.paso   = -1                     # -1 = no iniciado
        self.historial: List[dict] = []
        self.stats  = {"faults": 0, "tlb_hits": 0, "tlb_misses": 0,
                       "disk_reads": 0, "disk_writes": 0, "accesos": 0}
        self.ultimo_evento: dict = {}

    def _pte(self, llave: str) -> PTE:
        if llave not in self.tabla:
            self.tabla[llave] = PTE(llave)
        return self.tabla[llave]

    # ── recolectar procesos reales ──────────────────────────────────────────
    def recolectar_procesos(self) -> List[dict]:
        resultados = []
        IGNORAR = {"launchd","kernel_task","WindowServer","loginwindow",
                   "mds","mds_stores","distnoted","cfprefsd"}
        procs = []
        try:
            for p in psutil.process_iter(["pid", "name", "memory_info"]):
                try:
                    info   = p.info
                    nombre = (info.get("name") or "").strip()
                    mem    = info.get("memory_info")
                    rss    = mem.rss if mem else 0
                    if nombre and nombre not in IGNORAR and rss > 50 * 1024 * 1024:
                        procs.append((p.pid, nombre, rss))
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue
            procs.sort(key=lambda x: x[2], reverse=True)
            procs = procs[:10]
        except Exception:
            pass
        if not procs:
            procs = [(1, "Chrome", 400*1024*1024), (2, "Safari", 250*1024*1024),
                     (3, "Figma", 180*1024*1024), (4, "VSCode", 150*1024*1024)]
        ICONOS = {"chrome":"🌐","safari":"🧭","firefox":"🦊","figma":"🎨",
                  "code":"💻","cursor":"💻","node":"🟢","python":"🐍",
                  "terminal":"⬛","slack":"💬","spotify":"🎵","zoom":"📹",
                  "blender":"🎬","discord":"💬"}
        def icono(n):
            nl = n.lower()
            for k,v in ICONOS.items():
                if k in nl: return v
            return "⚙️"
        resultados_obj = []
        for idx, (pid, nombre, rss) in enumerate(procs):
            mb   = rss / (1024*1024)
            col  = color_proceso(nombre, idx)
            ps   = ProcSim(pid, nombre, mb, col, icono(nombre))
            resultados_obj.append(ps)
            resultados.append({"pid": pid, "nombre": nombre,
                                "mem_mb": round(mb,1), "color": col,
                                "icono": icono(nombre),
                                "num_paginas": ps.num_paginas})
        return resultados_obj, resultados

    # ── generar cadena de referencias ──────────────────────────────────────
    def generar_cadena(self, procs: List[ProcSim]) -> Tuple[List[str], List[dict]]:
        cadena: List[str] = []
        meta  : List[dict] = []
        def acc(p: ProcSim, pag_idx: int, escritura: bool, desc: str):
            llave = p.paginas[pag_idx % p.num_paginas]
            cadena.append(llave)
            meta.append({"proc_nombre": p.nombre, "proc_color": p.color,
                         "proc_icono": p.icono, "llave": llave,
                         "pag_idx": pag_idx % p.num_paginas,
                         "escritura": escritura, "desc": desc})
        if not procs:
            return [], []
        p0 = procs[0]
        p1 = procs[1] if len(procs) > 1 else procs[0]
        p2 = procs[2] if len(procs) > 2 else procs[0]
        p3 = procs[3] if len(procs) > 3 else procs[0]

        # Fase 1: cargar paginas iniciales (llenar RAM)
        acc(p0,0,False,f"{p0.nombre}: cargar codigo principal")
        acc(p0,1,False,f"{p0.nombre}: cargar datos de inicio")
        acc(p1,0,False,f"{p1.nombre}: iniciar proceso")
        acc(p2,0,False,f"{p2.nombre}: cargar libreria UI")
        acc(p0,2,True, f"{p0.nombre}: escribir en heap")
        acc(p1,1,False,f"{p1.nombre}: leer configuracion")
        # Fase 2: TLB hits
        acc(p0,0,False,f"{p0.nombre}: releer codigo (TLB hit esperado)")
        acc(p1,0,True, f"{p1.nombre}: modificar datos (D=1)")
        # Fase 3: RAM se llena - primer reemplazo
        acc(p3,0,False,f"{p3.nombre}: nuevo proceso entra a RAM -> LLENA")
        acc(p0,3,False,f"{p0.nombre}: nueva pestaña / nuevo modulo")
        # Fase 4: reemplazos con paginas sucias
        acc(p2,1,True, f"{p2.nombre}: render frame -> D=1")
        acc(p1,2,False,f"{p1.nombre}: leer cache")
        acc(p3,1,True, f"{p3.nombre}: compilar / procesar -> D=1")
        acc(p0,4,False,f"{p0.nombre}: cargar plugin / extension")
        # Fase 5: presion maxima
        acc(p2,2,True, f"{p2.nombre}: segundo frame de render -> D=1")
        acc(p0,5,False,f"{p0.nombre}: nueva tab del navegador")
        acc(p1,3,True, f"{p1.nombre}: guardar documento")
        acc(p3,2,False,f"{p3.nombre}: leer assets / recursos")
        # Fase 6: reaccesos (algunos TLB hit)
        acc(p0,0,False,f"{p0.nombre}: volver al codigo base")
        acc(p1,0,False,f"{p1.nombre}: volver al inicio del proceso")
        acc(p2,0,False,f"{p2.nombre}: reiniciar render loop")
        acc(p0,2,True, f"{p0.nombre}: heap otra vez (ya debe estar sucia)")
        acc(p3,0,False,f"{p3.nombre}: releer codigo base")
        acc(p0,6,False,f"{p0.nombre}: cargar otro modulo pesado")
        acc(p1,4,True, f"{p1.nombre}: buffer de video / audio -> D=1")
        acc(p2,3,False,f"{p2.nombre}: textura GPU / shader")
        return cadena, meta

    # ── inicializar simulacion ──────────────────────────────────────────────
    def inicializar(self, num_marcos: int):
        print(f"[INIT] Entrando con {num_marcos} marcos")
        with self.lock:
            print(f"[INIT] Lock adquirido")
            if self.disco:
                self.disco.limpiar()
            self.num_marcos = num_marcos
            self.ram        = [MarcoFisico(i) for i in range(num_marcos)]
            print(f"[INIT] RAM creada: {len(self.ram)} marcos")
            self.disco      = Disco()
            print(f"[INIT] Disco creado")
            self.tlb        = TLB(cap=min(8, num_marcos))
            print(f"[INIT] TLB creada")
            self.tabla      = {}
            self.paso       = -1
            self.historial  = []
            self.stats      = {"faults":0,"tlb_hits":0,"tlb_misses":0,
                               "disk_reads":0,"disk_writes":0,"accesos":0}
            self.ultimo_evento = {}
            print(f"[INIT] Recolectando procesos...")
            procs_obj, procs_json = self.recolectar_procesos()
            print(f"[INIT] {len(procs_obj)} procesos recolectados")
            self.procesos   = procs_obj
            print(f"[INIT] Generando cadena...")
            self.cadena, self.acceso_meta = self.generar_cadena(procs_obj)
            print(f"[INIT] Cadena generada: {len(self.cadena)} accesos")
            return procs_json

    # ── estado JSON actual ──────────────────────────────────────────────────
    def _estado_interno(self) -> dict:
        """Version interna sin lock, usada cuando ya se tiene el lock"""
        marcos_json = []
        for m in self.ram:
            if m.libre:
                marcos_json.append({"num": m.num, "libre": True,
                                    "addr": f"0x{m.base:016X}"})
            else:
                pte = self.tabla.get(m.pagina, PTE(m.pagina or ""))
                partes = (m.pagina or "").split(":")
                pid_str = partes[0] if partes else "?"
                pag_num = partes[1] if len(partes) > 1 else "?"
                proc = next((p for p in self.procesos
                             if f"P{p.pid}" == pid_str), None)
                marcos_json.append({
                    "num": m.num, "libre": False,
                    "llave": m.pagina,
                    "pid_str": pid_str, "pag_num": pag_num,
                    "nombre": proc.nombre if proc else pid_str,
                    "color":  proc.color  if proc else "#6E7681",
                    "icono":  proc.icono  if proc else "⚙️",
                    "P": pte.presente, "D": pte.sucio, "R": pte.referencia,
                    "addr": f"0x{m.base:016X}",
                })
        proc_json = [{"pid": p.pid, "nombre": p.nombre,
                      "mem_mb": round(p.mem_mb,1), "color": p.color,
                      "icono": p.icono, "num_paginas": p.num_paginas}
                     for p in self.procesos]
        total_tlb = self.stats["tlb_hits"] + self.stats["tlb_misses"]
        total_acc = self.stats["accesos"]
        return {
            "paso": self.paso,
            "total_pasos": len(self.cadena),
            "iniciado": self.paso >= 0,
            "terminado": self.paso >= len(self.cadena) - 1,
            "marcos": marcos_json,
            "num_marcos": self.num_marcos,
            "tlb": self.tlb.to_list() if self.tlb else [],
            "tlb_cap": self.tlb.cap if self.tlb else 0,
            "procesos": proc_json,
            "stats": {**self.stats,
                      "tlb_hit_pct": round(self.stats["tlb_hits"]/total_tlb*100,1) if total_tlb else 0,
                      "fault_pct":   round(self.stats["faults"]/total_acc*100,1)   if total_acc else 0},
            "evento": self.ultimo_evento,
            "historial": self.historial[-8:],
            "meta_actual": self.acceso_meta[self.paso] if 0 <= self.paso < len(self.acceso_meta) else {},
        }

    def estado(self) -> dict:
        with self.lock:
            return self._estado_interno()

    # ── avanzar un paso ─────────────────────────────────────────────────────
    def avanzar(self) -> dict:
        import sys
        print(f"[AVANZAR] Entrando... paso={self.paso}, cadena_len={len(self.cadena)}", file=sys.stderr, flush=True)
        with self.lock:
            print(f"[AVANZAR] Lock adquirido", file=sys.stderr, flush=True)
            if self.paso >= len(self.cadena) - 1:
                print(f"[AVANZAR] Ya terminado, retornando estado", file=sys.stderr, flush=True)
                return self._estado_interno()
            self.paso += 1
            idx   = self.paso
            llave = self.cadena[idx]
            meta  = self.acceso_meta[idx]
            print(f"[AVANZAR] Paso {idx}: {llave}", file=sys.stderr, flush=True)
            self.stats["accesos"] += 1
            eventos: List[str] = []
            tipo_evento = "acceso"
            victima_info = None
            opt_analisis = None

            # ── 1. Buscar TLB ────────────────────────────────────────────────
            print(f"[AVANZAR] Buscando en TLB...", file=sys.stderr, flush=True)
            marco = self.tlb.buscar(llave)
            print(f"[AVANZAR] TLB resultado: {marco}", file=sys.stderr, flush=True)
            if marco is not None:
                print(f"[AVANZAR] TLB HIT path", file=sys.stderr, flush=True)
                self.stats["tlb_hits"] += 1
                tipo_evento = "tlb_hit"
                pte = self._pte(llave)
                eventos.append(f"TLB HIT: {llave} -> marco {marco}")
                eventos.append(f"Traduccion inmediata sin acceder a RAM")
            else:
                print(f"[AVANZAR] TLB MISS path", file=sys.stderr, flush=True)
                self.stats["tlb_misses"] += 1
                print(f"[AVANZAR] Stats updated", file=sys.stderr, flush=True)
                eventos.append(f"TLB MISS: {llave} no en cache")
                print(f"[AVANZAR] Getting PTE...", file=sys.stderr, flush=True)
                pte = self._pte(llave)
                print(f"[AVANZAR] PTE obtenido, presente={pte.presente}", file=sys.stderr, flush=True)

                if not pte.presente:
                    # ── PAGE FAULT ───────────────────────────────────────────
                    print(f"[AVANZAR] PAGE FAULT!", file=sys.stderr, flush=True)
                    self.stats["faults"] += 1
                    self.stats["disk_reads"] += 1
                    tipo_evento = "page_fault"
                    eventos.append(f"PAGE FAULT: bit P=0, pagina ausente en RAM")

                    # marco libre?
                    print(f"[AVANZAR] Buscando marco libre... ram len={len(self.ram)}", file=sys.stderr, flush=True)
                    marco_libre = next((m.num for m in self.ram if m.libre), None)
                    print(f"[AVANZAR] Marco libre encontrado: {marco_libre}", file=sys.stderr, flush=True)
                    if marco_libre is not None:
                        marco = marco_libre
                        eventos.append(f"Marco libre disponible: marco {marco}")
                    else:
                        # RAM LLENA -> algoritmo optimo
                        tipo_evento = "page_fault_reemplazo"
                        eventos.append(f"RAM LLENA ({self.num_marcos} marcos) -> Algoritmo Optimo")
                        en_ram = [m.pagina for m in self.ram if not m.libre and m.pagina]
                        opt = Optimo(self.cadena)
                        victima_llave, analisis = opt.elegir_victima(en_ram, idx)
                        victima_pte = self._pte(victima_llave)
                        marco = victima_pte.marco

                        # analisis para el frontend
                        opt_analisis = {}
                        for k, v in analisis.items():
                            parts = k.split(":")
                            pn = parts[1] if len(parts) > 1 else k
                            pid_s = parts[0] if parts else ""
                            pr = next((p for p in self.procesos if f"P{p.pid}" == pid_s), None)
                            prox_s = f"indice {v['prox']}" if v["prox"] != float("inf") else "NUNCA"
                            opt_analisis[k] = {
                                "nombre": pr.nombre if pr else pid_s,
                                "pag": pn, "prox": prox_s,
                                "es_victima": v["es_victima"],
                                "color": pr.color if pr else "#6E7681"}

                        # info de la victima para el frontend
                        vp = next((p for p in self.procesos
                                   if f"P{p.pid}" == victima_llave.split(":")[0]), None)
                        victima_info = {
                            "llave": victima_llave,
                            "nombre": vp.nombre if vp else victima_llave,
                            "color":  vp.color  if vp else "#6E7681",
                            "sucio":  victima_pte.sucio,
                            "marco":  marco}

                        if victima_pte.sucio:
                            self.stats["disk_writes"] += 1
                            datos = self.ram[marco].volcar()
                            self.disco.guardar(victima_llave, datos)
                            eventos.append(f"DISCO WRITE: {victima_llave} (D=1) -> escrita al disco")
                        else:
                            eventos.append(f"Descartada {victima_llave} (D=0) sin escritura")

                        # desalojar
                        victima_pte.presente   = False
                        victima_pte.marco      = None
                        victima_pte.sucio      = False
                        victima_pte.referencia = False
                        self.ram[marco].limpiar()
                        self.ram[marco].libre  = True
                        self.ram[marco].pagina = None
                        self.tlb.invalidar(victima_llave)
                        eventos.append(f"TLB shootdown: entrada {victima_llave} invalidada")

                    # cargar pagina desde disco
                    print(f"[AVANZAR] Cargando {llave} desde disco...", file=sys.stderr, flush=True)
                    datos = self.disco.cargar(llave)
                    print(f"[AVANZAR] Disco cargar OK, {len(datos)} bytes", file=sys.stderr, flush=True)
                    self.ram[marco].cargar(datos)
                    print(f"[AVANZAR] RAM cargar OK", file=sys.stderr, flush=True)
                    self.ram[marco].libre  = False
                    self.ram[marco].pagina = llave
                    print(f"[AVANZAR] Marco {marco} asignado a {llave}", file=sys.stderr, flush=True)
                    pte.marco     = marco
                    pte.presente  = True
                    pte.referencia = False
                    pte.sucio     = meta["escritura"]
                    print(f"[AVANZAR] PTE actualizado", file=sys.stderr, flush=True)
                    eventos.append(f"Pagina {llave} cargada desde disco -> marco {marco}")
                    print(f"[AVANZAR] Agregando a TLB...", file=sys.stderr, flush=True)
                    self.tlb.agregar(llave, marco)
                    print(f"[AVANZAR] TLB agregado OK", file=sys.stderr, flush=True)
                    eventos.append(f"TLB actualizado: {llave} -> marco {marco}")
                else:
                    marco = pte.marco
                    eventos.append(f"Tabla paginas: {llave} -> marco {marco} (P=1)")
                    self.tlb.agregar(llave, marco)

            # ── bits de control ──────────────────────────────────────────────
            pte = self._pte(llave)
            pte.referencia = True
            if meta["escritura"]:
                pte.sucio = True
                payload = struct.pack(">IIQ", hash(llave) & 0xFFFFFFFF,
                                      idx, int(time.time_ns()))
                self.ram[marco].escribir(0, payload)
                eventos.append(f"Escritura real a addr 0x{self.ram[marco].base:016X} (D=1)")

            pa = self.ram[marco].base
            eventos.append(f"Direccion fisica REAL: 0x{pa:016X}")

            # evento para el frontend
            self.ultimo_evento = {
                "tipo": tipo_evento,
                "paso": idx,
                "llave": llave,
                "marco": marco,
                "pa": f"0x{pa:016X}",
                "desc": meta["desc"],
                "proc_nombre": meta["proc_nombre"],
                "proc_color":  meta["proc_color"],
                "proc_icono":  meta["proc_icono"],
                "pag_idx":     meta["pag_idx"],
                "escritura":   meta["escritura"],
                "mensajes":    eventos,
                "victima":     victima_info,
                "opt_analisis": opt_analisis,
                "P": pte.presente, "D": pte.sucio, "R": pte.referencia,
            }
            self.historial.append({
                "paso": idx, "tipo": tipo_evento,
                "llave": llave, "marco": marco,
                "proc": meta["proc_nombre"], "color": meta["proc_color"],
                "icono": meta["proc_icono"],
                "desc": meta["desc"][:55] + ("..." if len(meta["desc"]) > 55 else ""),
                "escritura": meta["escritura"],
            })
            print("[AVANZAR] historial actualizado, retornando estado", file=sys.stderr, flush=True)
            return self._estado_interno()

# ─────────────────────── FLASK APP ───────────────────────────────────────────
app   = Flask(__name__)
motor = Motor()

@app.route("/")
def index():
    return HTML_PAGE

@app.route("/api/inicializar", methods=["POST"])
def api_inicializar():
    datos  = request.get_json(silent=True) or {}
    marcos = max(3, min(32, int(datos.get("marcos", 6))))
    procs  = motor.inicializar(marcos)
    return jsonify({"ok": True, "procesos": procs,
                    "total_pasos": len(motor.cadena)})

@app.route("/api/estado")
def api_estado():
    return jsonify(motor.estado())

@app.route("/api/avanzar", methods=["POST"])
def api_avanzar():
    return jsonify(motor.avanzar())

@app.route("/api/reset", methods=["POST"])
def api_reset():
    datos  = request.get_json(silent=True) or {}
    marcos = max(3, min(32, int(datos.get("marcos", motor.num_marcos))))
    procs  = motor.inicializar(marcos)
    return jsonify({"ok": True, "procesos": procs})

# ─────────────────────── HTML / CSS / JS ─────────────────────────────────────
HTML_PAGE = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>MMU Simulator</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#0d1117;--bg2:#161b22;--bg3:#21262d;--bg4:#2d333b;
  --border:#30363d;--text:#e6edf3;--text2:#8b949e;--text3:#6e7681;
  --green:#3fb950;--red:#f85149;--yellow:#d29922;--blue:#58a6ff;
  --purple:#bc8cff;--cyan:#39c5cf;--orange:#f0883e;
  --radius:8px;--shadow:0 4px 24px rgba(0,0,0,.5);
}
body{background:var(--bg);color:var(--text);font-family:'SF Mono',Monaco,Consolas,monospace;font-size:13px;min-height:100vh}
h1,h2,h3{font-weight:600}
.app{display:grid;grid-template-rows:auto 1fr auto;height:100vh;overflow:hidden}

/* HEADER */
.header{background:var(--bg2);border-bottom:1px solid var(--border);padding:12px 20px;display:flex;align-items:center;gap:16px;flex-wrap:wrap}
.header h1{font-size:16px;color:var(--blue);white-space:nowrap}
.header h1 span{color:var(--text2);font-weight:400}
.controls{display:flex;gap:8px;align-items:center;flex:1;flex-wrap:wrap}
.btn{padding:6px 14px;border:1px solid var(--border);border-radius:6px;background:var(--bg3);color:var(--text);cursor:pointer;font-size:12px;font-family:inherit;transition:all .15s}
.btn:hover{background:var(--bg4);border-color:var(--text3)}
.btn.primary{background:#238636;border-color:#2ea043;color:#fff}
.btn.primary:hover{background:#2ea043}
.btn.danger{background:#b62324;border-color:#da3633;color:#fff}
.btn.danger:hover{background:#da3633}
.btn:disabled{opacity:.4;cursor:not-allowed}
.speed-label{color:var(--text2);font-size:11px;white-space:nowrap}
select{background:var(--bg3);border:1px solid var(--border);color:var(--text);padding:5px 8px;border-radius:6px;font-size:12px;font-family:inherit}
.chip{padding:3px 10px;border-radius:20px;font-size:11px;font-weight:600;white-space:nowrap}
.chip.fault{background:#6e1a1a;color:#f85149}
.chip.hit{background:#0f3d1f;color:#3fb950}
.chip.ok{background:#0d2137;color:#58a6ff}

/* MAIN GRID */
.main{display:grid;grid-template-columns:220px 1fr 260px;overflow:hidden}
.panel{border-right:1px solid var(--border);overflow-y:auto;padding:14px}
.panel:last-child{border-right:none}
.panel-title{font-size:11px;font-weight:700;color:var(--text2);text-transform:uppercase;letter-spacing:.08em;margin-bottom:10px;display:flex;align-items:center;gap:6px}
.dot{width:8px;height:8px;border-radius:50%;background:currentColor;flex-shrink:0}

/* PROCESOS */
.proc-item{display:flex;align-items:center;gap:8px;padding:6px 8px;border-radius:6px;margin-bottom:4px;background:var(--bg2);border:1px solid var(--border);cursor:default;transition:background .15s}
.proc-item:hover{background:var(--bg3)}
.proc-dot{width:12px;height:12px;border-radius:3px;flex-shrink:0}
.proc-info{flex:1;min-width:0}
.proc-name{font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.proc-mem{font-size:10px;color:var(--text3)}
.proc-pages{font-size:10px;color:var(--text3)}

/* CENTRO: EVENTO + RAM */
.center{display:flex;flex-direction:column;gap:0;overflow:hidden}
.evento-box{padding:14px 18px;border-bottom:1px solid var(--border);flex-shrink:0;min-height:160px}
.evento-tipo{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;margin-bottom:8px}
.evento-tipo.fault{color:var(--red)}
.evento-tipo.tlb_hit{color:var(--green)}
.evento-tipo.acceso{color:var(--blue)}
.evento-tipo.reemplazo{color:var(--orange)}
.evento-tipo.inicio{color:var(--text2)}
.evento-heading{font-size:18px;font-weight:700;margin-bottom:6px;display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.evento-desc{color:var(--text2);font-size:12px;margin-bottom:10px}
.evento-flujo{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:8px}
.flujo-item{padding:4px 10px;border-radius:20px;font-size:12px;background:var(--bg3);border:1px solid var(--border)}
.flujo-arrow{color:var(--text3);font-size:16px}
.bits-row{display:flex;gap:8px;flex-wrap:wrap}
.bit{padding:3px 10px;border-radius:20px;font-size:11px;font-weight:700}
.bit-P1{background:#0f3d1f;color:#3fb950}
.bit-P0{background:#3d0f0f;color:#f85149}
.bit-D1{background:#3d220f;color:#f0883e}
.bit-D0{background:#1a1f2e;color:var(--text3)}
.bit-R1{background:#2a2014;color:#d29922}
.bit-R0{background:#1a1f2e;color:var(--text3)}

/* RAM GRID */
.ram-area{flex:1;overflow-y:auto;padding:14px 18px}
.ram-title{font-size:11px;font-weight:700;color:var(--text2);text-transform:uppercase;letter-spacing:.08em;margin-bottom:10px}
.ram-grid{display:grid;gap:8px;grid-template-columns:repeat(auto-fill,minmax(110px,1fr))}
.frame-card{border-radius:var(--radius);border:2px solid transparent;padding:10px;position:relative;transition:all .4s;cursor:default;min-height:90px}
.frame-card.libre{background:var(--bg2);border-color:var(--border)}
.frame-card.ocupado{border-color:rgba(255,255,255,.15)}
.frame-num{font-size:10px;color:rgba(255,255,255,.5);margin-bottom:4px}
.frame-proc{font-size:12px;font-weight:700;color:#fff;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.frame-pag{font-size:11px;color:rgba(255,255,255,.7);margin-bottom:6px}
.frame-bits{display:flex;gap:3px;flex-wrap:wrap}
.fb{font-size:10px;padding:1px 5px;border-radius:10px;font-weight:700}
.fb-P1{background:rgba(63,185,80,.25);color:#3fb950}
.fb-D1{background:rgba(240,136,62,.25);color:#f0883e}
.fb-R1{background:rgba(210,153,34,.25);color:#d29922}
.fb-off{background:rgba(255,255,255,.07);color:rgba(255,255,255,.3)}
.frame-addr{font-size:9px;color:rgba(255,255,255,.3);margin-top:4px;word-break:break-all}
.frame-card.flash-fault{animation:flashFault .6s ease}
.frame-card.flash-hit{animation:flashHit .6s ease}
.frame-card.flash-new{animation:flashNew .8s ease}
@keyframes flashFault{0%{box-shadow:0 0 0 0 rgba(248,81,73,.8)}50%{box-shadow:0 0 20px 8px rgba(248,81,73,.6)}100%{box-shadow:none}}
@keyframes flashHit {0%{box-shadow:0 0 0 0 rgba(63,185,80,.8)}50%{box-shadow:0 0 20px 8px rgba(63,185,80,.6)}100%{box-shadow:none}}
@keyframes flashNew {0%{opacity:0;transform:scale(.9)}60%{opacity:1;transform:scale(1.04)}100%{transform:scale(1)}}

/* OPT ANALISIS */
.opt-box{background:var(--bg2);border:1px solid var(--border);border-radius:6px;padding:10px;margin-top:8px}
.opt-title{font-size:10px;font-weight:700;color:var(--orange);text-transform:uppercase;margin-bottom:6px}
.opt-row{display:flex;align-items:center;gap:6px;padding:3px 6px;border-radius:4px;margin-bottom:2px;font-size:11px}
.opt-row.victima{background:rgba(248,81,73,.15);border:1px solid rgba(248,81,73,.3)}
.opt-prox{margin-left:auto;font-weight:700}
.opt-prox.nunca{color:var(--red)}
.opt-prox.lejano{color:var(--orange)}
.opt-prox.cerca{color:var(--green)}

/* DISCO WRITE */
.disco-badge{display:inline-flex;align-items:center;gap:4px;padding:3px 8px;border-radius:4px;background:rgba(248,81,73,.15);border:1px solid rgba(248,81,73,.3);color:var(--red);font-size:11px;animation:pulseDisco 1s ease}
@keyframes pulseDisco{0%,100%{opacity:1}50%{opacity:.5}}

/* PANEL DERECHO */
.tlb-section{margin-bottom:16px}
.tlb-table{width:100%;border-collapse:collapse}
.tlb-table th{font-size:10px;color:var(--text3);font-weight:600;text-align:left;padding:3px 6px;border-bottom:1px solid var(--border)}
.tlb-table td{padding:4px 6px;font-size:11px;border-bottom:1px solid rgba(48,54,61,.5)}
.tlb-row.valida{color:var(--text)}
.tlb-row.invalida{color:var(--text3);text-decoration:line-through}
.valida-dot{width:7px;height:7px;border-radius:50%;background:var(--green);display:inline-block}
.invalida-dot{width:7px;height:7px;border-radius:50%;background:var(--red);display:inline-block}

/* HISTORIAL */
.hist-item{padding:6px 8px;border-radius:6px;border-left:3px solid;margin-bottom:4px;background:var(--bg2);font-size:11px}
.hist-item.fault{border-color:var(--red)}
.hist-item.fault.reemplazo{border-color:var(--orange)}
.hist-item.tlb_hit{border-color:var(--green)}
.hist-item.acceso{border-color:var(--blue)}
.hist-paso{color:var(--text3);font-size:10px}
.hist-desc{color:var(--text2);margin-top:2px}

/* STATS BAR */
.stats-bar{background:var(--bg2);border-top:1px solid var(--border);padding:10px 20px;display:flex;gap:20px;align-items:center;flex-wrap:wrap;flex-shrink:0}
.stat{display:flex;flex-direction:column;align-items:center;gap:2px}
.stat-val{font-size:18px;font-weight:700}
.stat-val.fault{color:var(--red)}
.stat-val.hit{color:var(--green)}
.stat-val.disk{color:var(--orange)}
.stat-val.blue{color:var(--blue)}
.stat-label{font-size:10px;color:var(--text3);text-transform:uppercase;letter-spacing:.06em}
.progress-bar{flex:1;min-width:120px}
.progress-label{font-size:10px;color:var(--text3);margin-bottom:3px;display:flex;justify-content:space-between}
.progress-track{height:6px;background:var(--bg4);border-radius:3px;overflow:hidden}
.progress-fill{height:100%;border-radius:3px;transition:width .4s}
.progress-fill.fault{background:var(--red)}
.progress-fill.hit{background:var(--green)}

/* SPLASH */
.splash{display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;gap:16px;padding:40px;text-align:center}
.splash h2{color:var(--blue);font-size:22px}
.splash p{color:var(--text2);max-width:480px;line-height:1.6}
.splash .config-row{display:flex;gap:10px;align-items:center}

/* SCROLLBAR */
::-webkit-scrollbar{width:6px;height:6px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:var(--border);border-radius:3px}

/* AUTO mode indicator */
.auto-indicator{width:8px;height:8px;border-radius:50%;background:var(--green);animation:pulse .8s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
</style>
</head>
<body>
<div class="app">

<!-- HEADER -->
<div class="header">
  <h1>MMU Simulator <span>Algoritmo Optimo de Belady</span></h1>
  <div class="controls">
    <button class="btn primary" id="btnIniciar" onclick="iniciar()">Iniciar simulacion</button>
    <button class="btn" id="btnPaso" onclick="paso()" disabled>Siguiente paso</button>
    <button class="btn" id="btnAuto" onclick="toggleAuto()" disabled>AUTO</button>
    <button class="btn danger" id="btnReset" onclick="reset()" style="display:none">Reiniciar</button>
    <span class="speed-label">Velocidad:</span>
    <select id="selSpeed">
      <option value="1500">Lenta</option>
      <option value="800" selected>Normal</option>
      <option value="350">Rapida</option>
      <option value="100">Turbo</option>
    </select>
    <span class="speed-label">Marcos RAM:</span>
    <select id="selMarcos">
      <option value="3">3 marcos</option>
      <option value="4">4 marcos</option>
      <option value="5">5 marcos</option>
      <option value="6" selected>6 marcos</option>
      <option value="8">8 marcos</option>
      <option value="12">12 marcos</option>
    </select>
    <div id="autoInd" class="auto-indicator" style="display:none"></div>
    <span id="pasoLabel" style="color:var(--text2);font-size:11px;margin-left:8px"></span>
  </div>
</div>

<!-- MAIN -->
<div class="main" id="mainContent">

  <!-- SPLASH INICIAL -->
  <div id="splash" style="grid-column:1/-1;display:flex">
    <div class="splash">
      <h2>Simulador MMU con Memoria RAM Real</h2>
      <p>
        Esta simulacion usa procesos <strong>reales de tu sistema</strong> (Chrome, Safari, etc.)
        como carga de trabajo. Cada marco de RAM es un bloque de <strong>4 KB asignado
        realmente con ctypes</strong>. Podras observar en tiempo real:
      </p>
      <ul style="color:var(--text2);text-align:left;line-height:2;list-style:none">
        <li>🔵 <strong>TLB HIT / MISS</strong> — cache de traducciones de direcciones</li>
        <li>🔴 <strong>PAGE FAULT</strong> — pagina ausente en RAM, se carga desde disco</li>
        <li>🟠 <strong>Bit Sucio (D=1)</strong> — pagina modificada que debe escribirse al disco</li>
        <li>🟡 <strong>Bit Referencia (R=1)</strong> — accedida recientemente</li>
        <li>⚙️ <strong>Algoritmo Optimo</strong> — elige la victima con analisis del futuro</li>
      </ul>
      <div class="config-row">
        <label style="color:var(--text2)">Marcos en RAM:</label>
        <select id="selMarcos2" style="background:var(--bg3);border:1px solid var(--border);color:var(--text);padding:8px 12px;border-radius:6px;font-size:14px">
          <option value="3">3 marcos (muy poca RAM)</option>
          <option value="4">4 marcos</option>
          <option value="5">5 marcos</option>
          <option value="6" selected>6 marcos (recomendado)</option>
          <option value="8">8 marcos</option>
          <option value="12">12 marcos (holgada)</option>
        </select>
        <button id="btnSplash" class="btn primary" style="padding:9px 20px;font-size:14px" onclick="iniciarDesde()">
          Iniciar simulacion
        </button>
      </div>
    </div>
  </div>

  <!-- PANEL IZQUIERDO: PROCESOS -->
  <div class="panel" id="panelProcesos" style="display:none">
    <div class="panel-title">Procesos del sistema</div>
    <div id="listaProcesos"></div>
    <div style="margin-top:12px;padding:8px;background:var(--bg2);border-radius:6px;border:1px solid var(--border)">
      <div style="font-size:10px;color:var(--text3);margin-bottom:6px;text-transform:uppercase">Uso RAM real</div>
      <div id="ramUsage" style="font-size:12px;color:var(--text2)"></div>
    </div>
  </div>

  <!-- CENTRO: EVENTO + RAM -->
  <div class="center" id="panelCentro" style="display:none">
    <!-- evento actual -->
    <div class="evento-box" id="eventoBox">
      <div class="evento-tipo inicio" id="eventoTipo">LISTO</div>
      <div class="evento-heading" id="eventoHeading">Simulacion lista para iniciar</div>
      <div class="evento-desc" id="eventoDesc">Presiona "Siguiente paso" para comenzar la simulacion paso a paso</div>
      <div class="evento-flujo" id="eventoFlujo"></div>
      <div class="bits-row" id="eventoBits"></div>
      <div id="opcionVictima"></div>
    </div>
    <!-- RAM -->
    <div class="ram-area">
      <div class="ram-title" id="ramTitle">MEMORIA FISICA (RAM)</div>
      <div class="ram-grid" id="ramGrid"></div>
    </div>
  </div>

  <!-- PANEL DERECHO: TLB + HISTORIAL -->
  <div class="panel" id="panelDerecho" style="display:none">
    <!-- TLB -->
    <div class="tlb-section">
      <div class="panel-title">TLB <span id="tlbCap" style="font-weight:400;color:var(--text3)"></span></div>
      <table class="tlb-table">
        <thead><tr><th></th><th>Pagina</th><th>Marco</th><th>Proceso</th></tr></thead>
        <tbody id="tlbBody"></tbody>
      </table>
      <div style="margin-top:8px;font-size:10px;color:var(--text3)">
        TLB Hits: <span id="tlbHitPct" style="color:var(--green)">0%</span>
        &nbsp;|&nbsp; Misses: <span id="tlbMissN" style="color:var(--red)">0</span>
      </div>
    </div>

    <!-- Tabla de paginas resumen -->
    <div class="tlb-section" style="margin-top:4px">
      <div class="panel-title">Tabla de paginas</div>
      <div id="tablaPaginas" style="font-size:11px"></div>
    </div>

    <!-- Historial -->
    <div>
      <div class="panel-title" style="margin-top:4px">Historial reciente</div>
      <div id="historial"></div>
    </div>
  </div>

</div><!-- /main -->

<!-- STATS BAR -->
<div class="stats-bar" id="statsBar" style="display:none">
  <div class="stat">
    <div class="stat-val fault" id="statFaults">0</div>
    <div class="stat-label">Page Faults</div>
  </div>
  <div class="stat">
    <div class="stat-val hit" id="statHitPct">0%</div>
    <div class="stat-label">TLB Hit Rate</div>
  </div>
  <div class="stat">
    <div class="stat-val disk" id="statDiskR">0</div>
    <div class="stat-label">Lecturas Disco</div>
  </div>
  <div class="stat">
    <div class="stat-val disk" id="statDiskW">0</div>
    <div class="stat-label">Escrituras Disco</div>
  </div>
  <div class="stat">
    <div class="stat-val blue" id="statAccesos">0</div>
    <div class="stat-label">Accesos</div>
  </div>
  <div class="progress-bar">
    <div class="progress-label">
      <span>Faults</span><span id="faultPct2">0%</span>
    </div>
    <div class="progress-track">
      <div class="progress-fill fault" id="faultBar" style="width:0%"></div>
    </div>
  </div>
  <div class="progress-bar">
    <div class="progress-label">
      <span>TLB Hit Rate</span><span id="hitPct2">0%</span>
    </div>
    <div class="progress-track">
      <div class="progress-fill hit" id="hitBar" style="width:0%"></div>
    </div>
  </div>
  <div style="color:var(--text3);font-size:11px;margin-left:auto" id="pasoFinal"></div>
</div>

</div><!-- /app -->

<script>
let autoMode = false;
let autoTimer = null;
let estado = null;
let iniciado = false;

function getMarcos(){
  return document.getElementById('selMarcos').value ||
         document.getElementById('selMarcos2').value || '6';
}

async function iniciarDesde(){
  const m = document.getElementById('selMarcos2').value;
  document.getElementById('selMarcos').value = m;
  await iniciar();
}

async function iniciar(){
  // feedback visual inmediato en ambos botones
  const btns = [document.getElementById('btnSplash'), document.getElementById('btnIniciar')];
  btns.forEach(b=>{ if(b){ b.textContent='Leyendo procesos del sistema...'; b.disabled=true; }});

  try {
    const marcos = getMarcos();
    const res = await fetch('/api/inicializar',{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({marcos:parseInt(marcos)})
    });
    console.log('[3] Fetch completado, status:', res.status);
    if(!res.ok) throw new Error('HTTP '+res.status);
    const data = await res.json();
    console.log('[4] JSON parseado, procesos:', data.procesos?.length);
    iniciado = true;
    console.log('[5] Mostrando UI...');
    mostrarUI();
    console.log('[6] Renderizando procesos...');
    renderProcesos(data.procesos);
    document.getElementById('pasoLabel').textContent =
      `0 / ${data.total_pasos} pasos`;
    document.getElementById('btnPaso').disabled = false;
    document.getElementById('btnAuto').disabled = false;
    document.getElementById('btnReset').style.display = '';
    document.getElementById('btnIniciar').style.display = 'none';
    console.log('[7] Obteniendo estado...');
    const est = await fetch('/api/estado').then(r=>r.json());
    console.log('[8] Estado obtenido, paso:', est.paso);
    actualizarVista(est);
    console.log('[9] Vista actualizada - LISTO');
  } catch(err) {
    btns.forEach(b=>{ if(b){ b.textContent='Iniciar simulacion'; b.disabled=false; }});
    console.error('Error en iniciar():', err);
    alert('Error al inicializar: ' + err.message + '. Revisa la consola (F12).');
  }
}

function mostrarUI(){
  document.getElementById('splash').style.display = 'none';
  document.getElementById('panelProcesos').style.display = '';
  document.getElementById('panelCentro').style.display = '';
  document.getElementById('panelDerecho').style.display = '';
  document.getElementById('statsBar').style.display = '';
}

async function paso(){
  console.log('[PASO] Iniciado:', iniciado);
  if(!iniciado) {
    console.log('[PASO] Bloqueado - no iniciado');
    return;
  }
  console.log('[PASO] Llamando /api/avanzar...');
  const res = await fetch('/api/avanzar',{method:'POST'});
  console.log('[PASO] Status:', res.status);
  const est = await res.json();
  console.log('[PASO] Paso actual:', est.paso);
  actualizarVista(est);
  if(est.terminado){
    document.getElementById('btnPaso').disabled = true;
    stopAuto();
    document.getElementById('btnAuto').disabled = true;
    document.getElementById('pasoFinal').textContent = 'Simulacion completada';
  }
  console.log('[PASO] Completado');
}

function toggleAuto(){
  if(autoMode){ stopAuto(); } else { startAuto(); }
}
function startAuto(){
  autoMode = true;
  document.getElementById('btnAuto').textContent = 'PAUSAR';
  document.getElementById('btnAuto').className = 'btn danger';
  document.getElementById('autoInd').style.display = '';
  runAuto();
}
function stopAuto(){
  autoMode = false;
  clearTimeout(autoTimer);
  document.getElementById('btnAuto').textContent = 'AUTO';
  document.getElementById('btnAuto').className = 'btn';
  document.getElementById('autoInd').style.display = 'none';
}
function runAuto(){
  if(!autoMode) return;
  paso().then(()=>{
    if(autoMode && estado && !estado.terminado){
      const spd = parseInt(document.getElementById('selSpeed').value);
      autoTimer = setTimeout(runAuto, spd);
    } else {
      stopAuto();
    }
  });
}

async function reset(){
  stopAuto();
  const marcos = getMarcos();
  await fetch('/api/reset',{
    method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({marcos:parseInt(marcos)})
  });
  const est = await fetch('/api/estado').then(r=>r.json());
  actualizarVista(est);
  document.getElementById('btnPaso').disabled = false;
  document.getElementById('btnAuto').disabled = false;
  document.getElementById('pasoFinal').textContent = '';
  document.getElementById('pasoLabel').textContent = `0 / ${est.total_pasos} pasos`;
}

// ── RENDER PRINCIPAL ─────────────────────────────────────────────────────────
function actualizarVista(est){
  estado = est;
  renderEvento(est.evento, est.meta_actual);
  renderRAM(est.marcos, est.evento);
  renderTLB(est.tlb, est.tlb_cap);
  renderTablaPaginas(est.marcos, est.tlb);
  renderHistorial(est.historial);
  renderStats(est.stats);
  document.getElementById('pasoLabel').textContent =
    `${est.paso+1} / ${est.total_pasos} pasos`;
  document.getElementById('ramTitle').textContent =
    `MEMORIA FISICA (RAM) — ${est.num_marcos} marcos x 4 KB reales`;
  actualizarRamUsage();
}

function renderProcesos(procs){
  const el = document.getElementById('listaProcesos');
  el.innerHTML = procs.map(p=>`
    <div class="proc-item">
      <div class="proc-dot" style="background:${p.color}"></div>
      <div class="proc-info">
        <div class="proc-name">${p.icono} ${p.nombre}</div>
        <div class="proc-mem">${p.mem_mb.toFixed(0)} MB en RAM</div>
        <div class="proc-pages">${p.num_paginas} paginas virtuales</div>
      </div>
    </div>
  `).join('');
}

function actualizarRamUsage(){
  try{
    fetch('/api/estado').then(r=>r.json()).then(est=>{
      const ocup = est.marcos.filter(m=>!m.libre).length;
      const libre = est.num_marcos - ocup;
      const pct = Math.round(ocup/est.num_marcos*100);
      document.getElementById('ramUsage').innerHTML =
        `<div style="margin-bottom:4px">
          <span style="color:var(--red)">${ocup} marcos ocupados</span>
          &nbsp;/&nbsp;
          <span style="color:var(--green)">${libre} libres</span>
          &nbsp;(${pct}%)
        </div>
        <div style="height:6px;background:var(--bg4);border-radius:3px;overflow:hidden">
          <div style="height:100%;width:${pct}%;background:${pct>85?'var(--red)':pct>60?'var(--orange)':'var(--green)'};transition:width .4s;border-radius:3px"></div>
        </div>`;
    });
  }catch(e){}
}

function renderEvento(ev, meta){
  if(!ev || !ev.tipo){
    document.getElementById('eventoTipo').className = 'evento-tipo inicio';
    document.getElementById('eventoTipo').textContent = 'LISTO';
    document.getElementById('eventoHeading').textContent = 'Simulacion lista para iniciar';
    document.getElementById('eventoDesc').textContent = 'Presiona "Siguiente paso" para comenzar la simulacion paso a paso';
    document.getElementById('eventoFlujo').innerHTML = '';
    document.getElementById('eventoBits').innerHTML = '';
    document.getElementById('opcionVictima').innerHTML = '';
    return;
  }
  const tipos = {
    page_fault: {label:'PAGE FAULT', cls:'fault', emoji:'⚠️'},
    page_fault_reemplazo: {label:'PAGE FAULT + REEMPLAZO', cls:'reemplazo', emoji:'🔄'},
    tlb_hit: {label:'TLB HIT', cls:'tlb_hit', emoji:'⚡'},
    acceso: {label:'ACCESO', cls:'acceso', emoji:'→'},
  };
  const t = tipos[ev.tipo] || {label:ev.tipo, cls:'acceso', emoji:'→'};
  const escritura = ev.escritura;
  const tipoAcceso = escritura
    ? '<span style="color:var(--orange);font-weight:700">ESCRITURA</span>'
    : '<span style="color:var(--green)">LECTURA</span>';

  document.getElementById('eventoTipo').className = `evento-tipo ${t.cls}`;
  document.getElementById('eventoTipo').textContent = t.label;

  document.getElementById('eventoHeading').innerHTML =
    `<span style="color:${ev.proc_color};font-size:20px">${ev.proc_icono}</span>
     <span style="color:${ev.proc_color}">${ev.proc_nombre}</span>
     <span style="color:var(--text3)">Pagina</span>
     <span style="color:var(--text)">${ev.pag_idx}</span>
     <span style="color:var(--text3)">—</span> ${tipoAcceso}`;

  document.getElementById('eventoDesc').textContent = ev.desc || '';

  // flujo VA -> pag -> marco -> PA
  const flujoItems = [
    {label: `VA`, val: ev.pa ? `Pag ${ev.pag_idx}` : '?'},
    {label: `→`},
    {label: `Marco`, val: `${ev.marco}`},
    {label: `→`},
    {label: `PA real`, val: ev.pa || '?'},
  ];
  document.getElementById('eventoFlujo').innerHTML = flujoItems.map(f=>
    f.val === undefined
      ? `<span class="flujo-arrow">${f.label}</span>`
      : `<span class="flujo-item"><span style="color:var(--text3)">${f.label}: </span>${f.val}</span>`
  ).join('');

  // bits
  const P = ev.P, D = ev.D, R = ev.R;
  document.getElementById('eventoBits').innerHTML = `
    <span class="bit ${P?'bit-P1':'bit-P0'}">P=${P?1:0} ${P?'en RAM':'en disco'}</span>
    <span class="bit ${D?'bit-D1':'bit-D0'}">D=${D?1:0} ${D?'SUCIO':'limpio'}</span>
    <span class="bit ${R?'bit-R1':'bit-R0'}">R=${R?1:0} ${R?'referenciado':''}</span>
    ${escritura ? '<span class="disco-badge">escritura real a RAM</span>' : ''}
    ${ev.tipo==='page_fault'||ev.tipo==='page_fault_reemplazo' ? '<span class="disco-badge" style="background:rgba(248,81,73,.25)">lectura de disco</span>' : ''}
  `;

  // victima + OPT analisis
  let vicHTML = '';
  if(ev.victima){
    const v = ev.victima;
    vicHTML = `<div class="opt-box">
      <div class="opt-title">Victima seleccionada por Algoritmo Optimo</div>
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
        <div style="width:12px;height:12px;border-radius:3px;background:${v.color}"></div>
        <strong>${v.nombre}</strong> pagina ${v.llave.split(':')[1]}
        marco ${v.marco}
        ${v.sucio ? '<span class="disco-badge">SUCIA → escrita al disco</span>' : '<span style="color:var(--green);font-size:11px">limpia → descartada sin I/O</span>'}
      </div>`;
    if(ev.opt_analisis){
      vicHTML += '<div class="opt-title" style="margin-bottom:4px">Analisis de uso futuro</div>';
      const sorted = Object.entries(ev.opt_analisis)
        .sort((a,b)=> {
          const pa = a[1].prox==='NUNCA'?Infinity:parseInt(a[1].prox.replace('indice ',''));
          const pb = b[1].prox==='NUNCA'?Infinity:parseInt(b[1].prox.replace('indice ',''));
          return pb - pa;
        });
      for(const [k,v2] of sorted){
        const isVic = v2.es_victima;
        const prox  = v2.prox;
        const cls   = prox==='NUNCA'?'nunca':prox.includes('indice') && parseInt(prox.split(' ')[1])>15?'lejano':'cerca';
        vicHTML += `<div class="opt-row ${isVic?'victima':''}">
          <div style="width:10px;height:10px;border-radius:2px;background:${v2.color};flex-shrink:0"></div>
          <span>${v2.nombre} pag ${v2.pag}</span>
          ${isVic?'<strong style="color:var(--red)">← VICTIMA</strong>':''}
          <span class="opt-prox ${cls}">${prox}</span>
        </div>`;
      }
    }
    vicHTML += '</div>';
  }
  document.getElementById('opcionVictima').innerHTML = vicHTML;
}

function renderRAM(marcos, evento){
  const grid = document.getElementById('ramGrid');
  const evMarco = evento ? evento.marco : -1;
  const evTipo  = evento ? evento.tipo  : '';

  grid.innerHTML = marcos.map(m => {
    if(m.libre){
      return `<div class="frame-card libre" id="fc${m.num}">
        <div class="frame-num">Marco ${m.num}</div>
        <div style="color:var(--text3);font-size:12px;margin-top:8px">LIBRE</div>
        <div class="frame-addr">${m.addr}</div>
      </div>`;
    }
    const isEvento = m.num === evMarco;
    let flashClass = '';
    if(isEvento){
      if(evTipo==='tlb_hit') flashClass = 'flash-hit';
      else if(evTipo==='page_fault'||evTipo==='page_fault_reemplazo') flashClass = 'flash-new';
    }
    const bg = hexToRgba(m.color, 0.18);
    const border = hexToRgba(m.color, 0.5);
    return `<div class="frame-card ocupado ${flashClass}" id="fc${m.num}"
              style="background:${bg};border-color:${border}">
      <div class="frame-num">Marco ${m.num}</div>
      <div class="frame-proc" style="color:${m.color}">${m.icono} ${m.nombre}</div>
      <div class="frame-pag">Pagina ${m.pag_num}</div>
      <div class="frame-bits">
        <span class="fb ${m.P?'fb-P1':'fb-off'}">${m.P?'P=1':'P=0'}</span>
        <span class="fb ${m.D?'fb-D1':'fb-off'}">${m.D?'D=1':'D=0'}</span>
        <span class="fb ${m.R?'fb-R1':'fb-off'}">${m.R?'R=1':'R=0'}</span>
      </div>
      <div class="frame-addr">${m.addr}</div>
    </div>`;
  }).join('');
}

function renderTLB(tlb, cap){
  document.getElementById('tlbCap').textContent = `(${cap} entradas)`;
  const tbody = document.getElementById('tlbBody');
  if(!tlb || tlb.length===0){
    tbody.innerHTML = '<tr><td colspan="4" style="color:var(--text3);padding:6px">Vacio</td></tr>';
    return;
  }
  tbody.innerHTML = tlb.map(e=>{
    const parts = e.llave.split(':');
    const pid = parts[0];
    const pag = parts[1]||'?';
    const proc = estado ? estado.procesos.find(p=>`P${p.pid}`===pid) : null;
    const color = proc ? proc.color : '#6E7681';
    const nombre = proc ? proc.nombre : pid;
    return `<tr class="tlb-row ${e.valida?'valida':'invalida'}">
      <td><span class="${e.valida?'valida':'invalida'}-dot"></span></td>
      <td>${pag}</td>
      <td>${e.marco}</td>
      <td><span style="color:${color}">${nombre.substring(0,8)}</span></td>
    </tr>`;
  }).join('');
}

function renderTablaPaginas(marcos, tlb){
  const el = document.getElementById('tablaPaginas');
  if(!marcos) return;
  const ocupados = marcos.filter(m=>!m.libre);
  if(ocupados.length===0){
    el.innerHTML = '<div style="color:var(--text3)">Sin paginas cargadas</div>';
    return;
  }
  el.innerHTML = `<table style="width:100%;border-collapse:collapse">
    <thead><tr>
      <th style="text-align:left;color:var(--text3);font-size:10px;padding:2px 4px">Pagina</th>
      <th style="text-align:left;color:var(--text3);font-size:10px;padding:2px 4px">Marco</th>
      <th style="text-align:center;color:var(--text3);font-size:10px;padding:2px 4px">P</th>
      <th style="text-align:center;color:var(--text3);font-size:10px;padding:2px 4px">D</th>
      <th style="text-align:center;color:var(--text3);font-size:10px;padding:2px 4px">R</th>
    </tr></thead>
    <tbody>${ocupados.map(m=>`
      <tr>
        <td style="padding:2px 4px"><span style="color:${m.color}">${m.nombre.substring(0,7)}</span> P${m.pag_num}</td>
        <td style="padding:2px 4px;color:var(--text2)">${m.num}</td>
        <td style="text-align:center;padding:2px 4px;color:${m.P?'var(--green)':'var(--red)'}">${m.P?1:0}</td>
        <td style="text-align:center;padding:2px 4px;color:${m.D?'var(--orange)':'var(--text3)'}">${m.D?1:0}</td>
        <td style="text-align:center;padding:2px 4px;color:${m.R?'var(--yellow)':'var(--text3)'}">${m.R?1:0}</td>
      </tr>`).join('')}
    </tbody>
  </table>`;
}

function renderHistorial(hist){
  const el = document.getElementById('historial');
  if(!hist || hist.length===0){ el.innerHTML=''; return; }
  el.innerHTML = [...hist].reverse().map(h=>`
    <div class="hist-item ${h.tipo}">
      <div class="hist-paso">Paso ${h.paso+1} &nbsp;
        ${h.tipo==='tlb_hit'?'<span style="color:var(--green)">TLB HIT</span>':
          h.tipo.includes('fault')?'<span style="color:var(--red)">PAGE FAULT</span>':
          '<span style="color:var(--blue)">ACCESO</span>'}
        &nbsp;<span style="color:${h.color}">${h.icono} ${h.proc}</span>
        &nbsp;pag ${h.llave.split(':')[1]}
        ${h.escritura?'<span style="color:var(--orange)">[W]</span>':'<span style="color:var(--green)">[R]</span>'}
      </div>
      <div class="hist-desc">${h.desc}</div>
    </div>
  `).join('');
}

function renderStats(stats){
  document.getElementById('statFaults').textContent  = stats.faults;
  document.getElementById('statHitPct').textContent  = stats.tlb_hit_pct + '%';
  document.getElementById('statDiskR').textContent   = stats.disk_reads;
  document.getElementById('statDiskW').textContent   = stats.disk_writes;
  document.getElementById('statAccesos').textContent = stats.accesos;
  document.getElementById('tlbHitPct').textContent   = stats.tlb_hit_pct + '%';
  document.getElementById('tlbMissN').textContent    = stats.tlb_misses;
  const fp = stats.fault_pct;
  const hp = stats.tlb_hit_pct;
  document.getElementById('faultPct2').textContent   = fp + '%';
  document.getElementById('hitPct2').textContent     = hp + '%';
  document.getElementById('faultBar').style.width    = fp + '%';
  document.getElementById('hitBar').style.width      = hp + '%';
}

// ── UTILIDADES ───────────────────────────────────────────────────────────────
function hexToRgba(hex, alpha){
  try{
    const r = parseInt(hex.slice(1,3),16);
    const g = parseInt(hex.slice(3,5),16);
    const b = parseInt(hex.slice(5,7),16);
    return `rgba(${r},${g},${b},${alpha})`;
  }catch(e){ return `rgba(110,118,129,${alpha})`; }
}
</script>
</body>
</html>"""

# ─────────────────────── PUNTO DE ENTRADA ────────────────────────────────────
if __name__ == "__main__":
    print("""
╔══════════════════════════════════════════════════════════════╗
║   MMU Simulator - Interfaz Web                              ║
╠══════════════════════════════════════════════════════════════╣
║   Abriendo en: http://localhost:5050                        ║
╚══════════════════════════════════════════════════════════════╝
""")
    try:
        import webbrowser
        threading.Timer(1.2, lambda: webbrowser.open("http://localhost:5050")).start()
    except Exception:
        pass
    app.run(host="0.0.0.0", port=5050, debug=False)
