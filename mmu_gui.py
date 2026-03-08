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
    # Juegos y apps pesadas
    "minecraft": "#6B8E23",
    "java":      "#5382A1",
    "photoshop": "#001E36",
    "premiere":  "#E77CFF",
    "aftereffects": "#CF96FD",
    "unity":     "#222222",
    "unreal":    "#0D47A1",
    "steam":     "#1B2838",
    "valorant":  "#FF4655",
    "gta":       "#F7921E",
    "cyberpunk": "#00B4D8",
    "fortnite":  "#9B59B6",
    "obs":       "#302E31",
    "davinci":   "#233A52",
    "illustrator": "#FF7C00",
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
        # Juegos/apps pesadas tienen muchas más páginas (1 GB = ~12 páginas)
        self.num_paginas = max(6, min(40, int(mem_mb / 120)))
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
    # Palabras clave de apps "pesadas" que merecen simularse
    _APPS_PESADAS = {
        "minecraft","java","terraria","valheim","gta","cyberpunk","valorant",
        "fortnite","steam","unreal","photoshop","lightroom","illustrator",
        "premiere","aftereffects","davinci","blender","cinema","maya","houdini",
        "unity","godot","obs","shadowplay","streamlabs","figma","xcode",
        "android studio","intellij","eclipse","resolve","3ds max","zbrush",
    }

    def recolectar_procesos(self) -> List[dict]:
        resultados = []
        IGNORAR = {"launchd","kernel_task","WindowServer","loginwindow",
                   "mds","mds_stores","distnoted","cfprefsd","UserEventAgent",
                   "coreaudiod","bird","cloudd","rapportd","trustd","syspolicyd"}
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

        # Si no hay apps pesadas reconocidas, usar perfiles de juegos/apps
        tiene_app_pesada = any(
            any(kw in nombre.lower() for kw in self._APPS_PESADAS)
            for _, nombre, _ in procs
        )
        if not procs or not tiene_app_pesada:
            # Fallback: simular escenario típico de gamer/creador de contenido
            procs = [
                (1,  "Minecraft",       2048*1024*1024),   # 2 GB
                (2,  "Photoshop",       1800*1024*1024),   # 1.8 GB
                (3,  "Blender",         1400*1024*1024),   # 1.4 GB
                (4,  "Unity Editor",    1100*1024*1024),   # 1.1 GB
                (5,  "OBS Studio",       600*1024*1024),   # 600 MB
                (6,  "Discord",          300*1024*1024),   # 300 MB
            ]
        ICONOS = {"chrome":"🌐","safari":"🧭","firefox":"🦊","figma":"🎨",
                  "code":"💻","cursor":"💻","node":"🟢","python":"🐍",
                  "terminal":"⬛","slack":"💬","spotify":"🎵","zoom":"📹",
                  "blender":"🎬","discord":"💬",
                  "minecraft":"⛏️","java":"☕","photoshop":"🖼️",
                  "premiere":"🎬","aftereffects":"✨","unity":"🎮",
                  "unreal":"🎮","steam":"🎮","valorant":"🎯","gta":"🚗",
                  "cyberpunk":"🤖","fortnite":"🏆","obs":"📡",
                  "davinci":"🎞️","illustrator":"🖌️"}
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
    def _desc_acceso(self, nombre: str, tipo: str) -> str:
        """Genera descripciones realistas según el tipo de app/juego."""
        n = nombre.lower()
        descripciones = {
            "juego_textura":   [
                "Cargar textura diffuse 4K (64 MB)",
                "Cargar normal map del terreno",
                "Streaming de textura de personaje",
                "LOD: textura de baja resolución distante",
                "Cargar skybox HDR",
            ],
            "juego_mundo":     [
                "Generar chunk del mundo (16x16x256)",
                "Cargar datos de bioma vecino",
                "Actualizar mapa de altura del terreno",
                "Serializar chunk al disco (guardado)",
                "Deserializar chunk desde disco",
            ],
            "juego_fisica":    [
                "Calcular colisiones físicas (broadphase)",
                "Actualizar árbol BVH de objetos",
                "Simular física de cuerpo rígido",
                "Raycast de proyectiles en escena",
                "Actualizar posición de NPC (pathfinding)",
            ],
            "juego_audio":     [
                "Buffer de audio PCM (música de fondo)",
                "Cargar efecto de sonido (disparo/golpe)",
                "Mezclar canales de audio (spatializado)",
            ],
            "juego_red":       [
                "Recibir paquete de estado del servidor",
                "Enviar input del jugador al servidor",
                "Sincronizar posición de entidades remotas",
            ],
            "img_capa":        [
                "Buffer de capa de 16K x 16K px",
                "Smart Object: leer datos embebidos",
                "Aplicar filtro Gaussian Blur en memoria",
                "Histórico de deshacer (16 MB)",
                "Guardar TIFF sin comprimir al disco",
            ],
            "img_render":      [
                "Renderizar composición final (RAW)",
                "Exportar JPEG con perfil de color",
                "Color grading LUT en memoria GPU",
                "Cargar preset de Camera Raw",
            ],
            "render3d_mesh":   [
                "Cargar malla 3D (1.2M polígonos)",
                "Subdivisión de superficie (Catmull-Clark)",
                "Calcular normales suavizadas",
                "Importar FBX con esqueleto de animación",
                "Aplicar modificador Boolean en memoria",
            ],
            "render3d_render": [
                "Path tracing: acumular muestra #1024",
                "Denoising: buffer de iluminación global",
                "Calcular sombras de área (soft shadows)",
                "BVH traversal: escena completa",
                "Guardar EXR de 32 bits al disco",
            ],
            "motor_script":    [
                "Compilar C# → IL → código nativo (JIT)",
                "Cargar asset bundle de escena",
                "Instanciar prefab complejo en runtime",
                "Actualizar sistema de partículas (VFX)",
                "Serializar estado de escena (autosave)",
            ],
            "motor_shader":    [
                "Compilar shader HLSL para GPU",
                "Cargar pipeline de renderizado (PSO)",
                "Actualizar constant buffer (matrices MVP)",
            ],
            "stream_encode":   [
                "Encodear frame H.264 (CPU software)",
                "Capturar frame del escritorio (GDI)",
                "Escribir segmento RTMP al buffer",
                "Escalar resolución 4K → 1080p",
            ],
            "generico":        [
                "Leer configuración de usuario",
                "Actualizar interfaz gráfica (UI redraw)",
                "Procesar evento de entrada (teclado/mouse)",
                "Enviar IPC al sistema operativo",
            ],
        }
        # Clasificar la app y elegir categoría
        if any(x in n for x in ["minecraft","java","terraria","valheim","gta","cyberpunk","valorant","fortnite","steam","unreal"]):
            cats = ["juego_textura","juego_mundo","juego_fisica","juego_audio","juego_red"]
        elif any(x in n for x in ["photoshop","illustrator","lightroom","gimp","affinity","paint"]):
            cats = ["img_capa","img_render","generico"]
        elif any(x in n for x in ["blender","cinema","houdini","3ds","maya","zbrush"]):
            cats = ["render3d_mesh","render3d_render","generico"]
        elif any(x in n for x in ["unity","godot","unreal","engine"]):
            cats = ["motor_script","motor_shader","juego_fisica","generico"]
        elif any(x in n for x in ["obs","shadowplay","streamlabs","davinci","premiere","aftereffects"]):
            cats = ["stream_encode","img_render","generico"]
        else:
            cats = ["generico","img_render","juego_audio"]
        cat = random.choice(cats)
        return random.choice(descripciones[cat])

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

        # Usar hasta 4 procesos para la secuencia narrativa
        p0 = procs[0]
        p1 = procs[1] if len(procs) > 1 else procs[0]
        p2 = procs[2] if len(procs) > 2 else procs[0]
        p3 = procs[3] if len(procs) > 3 else procs[0]
        p4 = procs[4] if len(procs) > 4 else procs[0]
        p5 = procs[5] if len(procs) > 5 else procs[0]

        # ── Fase 1: Arranque — cada app carga sus páginas iniciales ──────────
        acc(p0, 0, False, f"{p0.nombre}: inicializar motor/engine (código base)")
        acc(p0, 1, False, f"{p0.nombre}: {self._desc_acceso(p0.nombre, 'init')}")
        acc(p1, 0, False, f"{p1.nombre}: inicializar motor/engine (código base)")
        acc(p2, 0, False, f"{p2.nombre}: inicializar motor/engine (código base)")
        acc(p0, 2, True,  f"{p0.nombre}: {self._desc_acceso(p0.nombre, 'write')}")
        acc(p1, 1, False, f"{p1.nombre}: {self._desc_acceso(p1.nombre, 'read')}")

        # ── Fase 2: TLB hits — re-acceso a páginas ya cargadas ───────────────
        acc(p0, 0, False, f"{p0.nombre}: re-acceso código base (TLB hit esperado)")
        acc(p1, 0, True,  f"{p1.nombre}: modificar buffer de trabajo (D=1)")
        acc(p0, 1, False, f"{p0.nombre}: re-leer configuración cargada (TLB hit)")

        # ── Fase 3: Nuevos procesos entran — RAM se llena ────────────────────
        acc(p3, 0, False, f"{p3.nombre}: inicializar — RAM comienza a llenarse")
        acc(p0, 3, False, f"{p0.nombre}: {self._desc_acceso(p0.nombre, 'load')}")
        acc(p3, 1, True,  f"{p3.nombre}: {self._desc_acceso(p3.nombre, 'write')}")
        acc(p1, 2, False, f"{p1.nombre}: {self._desc_acceso(p1.nombre, 'load')}")

        # ── Fase 4: RAM LLENA — empiezan los reemplazos ───────────────────────
        acc(p4, 0, False, f"{p4.nombre}: inicializar — RAM LLENA, se necesita reemplazo")
        acc(p0, 4, True,  f"{p0.nombre}: {self._desc_acceso(p0.nombre, 'write')} (D=1)")
        acc(p2, 1, True,  f"{p2.nombre}: {self._desc_acceso(p2.nombre, 'write')} (D=1)")
        acc(p3, 2, False, f"{p3.nombre}: {self._desc_acceso(p3.nombre, 'load')}")
        acc(p1, 3, True,  f"{p1.nombre}: escribir resultado al buffer de salida (D=1)")

        # ── Fase 5: Presión máxima de memoria ────────────────────────────────
        acc(p5, 0, False, f"{p5.nombre}: conectar — máxima presión de memoria")
        acc(p0, 5, False, f"{p0.nombre}: {self._desc_acceso(p0.nombre, 'load')}")
        acc(p2, 2, True,  f"{p2.nombre}: {self._desc_acceso(p2.nombre, 'write')} (D=1)")
        acc(p4, 1, False, f"{p4.nombre}: {self._desc_acceso(p4.nombre, 'load')}")
        acc(p3, 3, True,  f"{p3.nombre}: {self._desc_acceso(p3.nombre, 'write')} (D=1)")
        acc(p5, 1, False, f"{p5.nombre}: {self._desc_acceso(p5.nombre, 'load')}")

        # ── Fase 6: Reaccesos — algunas páginas vuelven (TLB miss → RAM hit) ─
        acc(p0, 0, False, f"{p0.nombre}: volver al código base (puede estar swapped)")
        acc(p1, 0, False, f"{p1.nombre}: recuperar estado inicial del proceso")
        acc(p2, 0, False, f"{p2.nombre}: reiniciar loop principal")
        acc(p0, 2, True,  f"{p0.nombre}: {self._desc_acceso(p0.nombre, 'write')} (página sucia)")
        acc(p3, 0, False, f"{p3.nombre}: re-acceso al código base")

        # ── Fase 7: Carga pesada final — muchos reemplazos seguidos ──────────
        acc(p0, 6, False, f"{p0.nombre}: {self._desc_acceso(p0.nombre, 'heavy')}")
        acc(p1, 4, True,  f"{p1.nombre}: {self._desc_acceso(p1.nombre, 'write')} (D=1)")
        acc(p2, 3, False, f"{p2.nombre}: {self._desc_acceso(p2.nombre, 'load')}")
        acc(p4, 2, True,  f"{p4.nombre}: {self._desc_acceso(p4.nombre, 'write')} (D=1)")
        acc(p0, 7, False, f"{p0.nombre}: {self._desc_acceso(p0.nombre, 'load')}")
        acc(p5, 2, True,  f"{p5.nombre}: {self._desc_acceso(p5.nombre, 'write')} (D=1)")
        acc(p3, 4, False, f"{p3.nombre}: {self._desc_acceso(p3.nombre, 'load')}")
        acc(p1, 5, False, f"{p1.nombre}: {self._desc_acceso(p1.nombre, 'load')}")

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

        # PTBR: proceso cuya tabla de páginas está siendo consultada ahora
        ptbr_data = None
        if 0 <= self.paso < len(self.acceso_meta):
            llave_cur = self.cadena[self.paso]
            parts_cur = llave_cur.split(":")
            pid_s_cur = parts_cur[0]
            pag_cur   = parts_cur[1] if len(parts_cur) > 1 else "?"
            proc_cur  = next((p for p in self.procesos if f"P{p.pid}" == pid_s_cur), None)
            if proc_cur:
                ptbr_data = {"pid": proc_cur.pid, "nombre": proc_cur.nombre,
                             "color": proc_cur.color, "icono": proc_cur.icono,
                             "pag_actual": pag_cur}

        # Tabla de páginas completa agrupada por proceso
        tabla_procs: Dict[int, dict] = {}
        for llave, pte in self.tabla.items():
            parts = llave.split(":")
            pid_s = parts[0]
            pag_n = parts[1] if len(parts) > 1 else "0"
            proc  = next((p for p in self.procesos if f"P{p.pid}" == pid_s), None)
            if not proc:
                continue
            if proc.pid not in tabla_procs:
                tabla_procs[proc.pid] = {"pid": proc.pid, "nombre": proc.nombre,
                                         "color": proc.color, "icono": proc.icono,
                                         "entradas": []}
            tabla_procs[proc.pid]["entradas"].append({
                "llave": llave,
                "pag":   int(pag_n) if pag_n.isdigit() else 0,
                "marco": pte.marco,
                "presente":   pte.presente,
                "sucio":      pte.sucio,
                "referencia": pte.referencia,
            })
        for v in tabla_procs.values():
            v["entradas"].sort(key=lambda e: e["pag"])

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
            "ptbr": ptbr_data,
            "tabla_procesos": list(tabla_procs.values()),
            "stats": {**self.stats,
                      "tlb_hit_pct": round(self.stats["tlb_hits"]/total_tlb*100,1) if total_tlb else 0,
                      "fault_pct":   round(self.stats["faults"]/total_acc*100,1)   if total_acc else 0},
            "evento": self.ultimo_evento,
            "historial": self.historial[-8:],
            "meta_actual": self.acceso_meta[self.paso] if 0 <= self.paso < len(self.acceso_meta) else {},
            "proximas": [
                {
                    "idx": i,
                    "llave": self.cadena[i],
                    "proc_nombre": self.acceso_meta[i]["proc_nombre"],
                    "proc_color":  self.acceso_meta[i]["proc_color"],
                    "proc_icono":  self.acceso_meta[i]["proc_icono"],
                    "pag_idx":     self.acceso_meta[i]["pag_idx"],
                    "escritura":   self.acceso_meta[i]["escritura"],
                    "desc":        self.acceso_meta[i]["desc"][:45],
                }
                for i in range(self.paso + 1,
                               min(self.paso + 12, len(self.cadena)))
            ],
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
HTML_PAGE = r"""<!DOCTYPE html>
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
  --radius:8px;
}
body{background:var(--bg);color:var(--text);font-family:'SF Mono',Monaco,Consolas,monospace;font-size:13px;min-height:100vh}
h1,h2,h3{font-weight:600}
.app{display:grid;grid-template-rows:auto 1fr auto;height:100vh;overflow:hidden}

/* HEADER */
.header{background:var(--bg2);border-bottom:1px solid var(--border);padding:10px 16px;display:flex;align-items:center;gap:12px;flex-wrap:wrap}
.header h1{font-size:15px;color:var(--blue);white-space:nowrap}
.header h1 span{color:var(--text2);font-weight:400}
.controls{display:flex;gap:6px;align-items:center;flex:1;flex-wrap:wrap}
.btn{padding:5px 12px;border:1px solid var(--border);border-radius:6px;background:var(--bg3);color:var(--text);cursor:pointer;font-size:12px;font-family:inherit;transition:all .15s}
.btn:hover{background:var(--bg4);border-color:var(--text3)}
.btn.primary{background:#238636;border-color:#2ea043;color:#fff}
.btn.primary:hover{background:#2ea043}
.btn.danger{background:#b62324;border-color:#da3633;color:#fff}
.btn.danger:hover{background:#da3633}
.btn:disabled{opacity:.4;cursor:not-allowed}
.speed-label{color:var(--text2);font-size:11px;white-space:nowrap}
select{background:var(--bg3);border:1px solid var(--border);color:var(--text);padding:4px 8px;border-radius:6px;font-size:12px;font-family:inherit}
.auto-indicator{width:8px;height:8px;border-radius:50%;background:var(--green);animation:pulse .8s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}

/* MAIN 3-COL GRID */
.main{display:grid;grid-template-columns:250px 1fr 280px;overflow:hidden}
.panel{border-right:1px solid var(--border);overflow-y:auto;padding:12px}
.panel:last-child{border-right:none}
.panel-title{font-size:10px;font-weight:700;color:var(--text2);text-transform:uppercase;letter-spacing:.08em;margin-bottom:8px;display:flex;align-items:center;gap:6px}

/* PROCESOS */
.proc-item{display:flex;align-items:center;gap:8px;padding:5px 8px;border-radius:6px;margin-bottom:3px;background:var(--bg2);border:1px solid var(--border)}
.proc-swatch{width:10px;height:10px;border-radius:2px;flex-shrink:0}
.proc-name{font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.proc-sub{font-size:9px;color:var(--text3)}

/* RAM usage bar */
.ram-usage-box{margin-top:8px;padding:8px;background:var(--bg2);border-radius:6px;border:1px solid var(--border)}

/* PTBR */
.ptbr-section{margin-top:10px}
.ptbr-reg-box{background:var(--bg3);border:1px solid var(--border);border-radius:6px;padding:7px 10px;display:flex;align-items:center;gap:8px;margin-bottom:3px;transition:border-color .3s}
.ptbr-reg-box.active{border-color:var(--blue);box-shadow:0 0 8px rgba(88,166,255,.25)}
.ptbr-reg-label{font-size:9px;font-weight:700;color:var(--text3);background:var(--bg4);padding:2px 5px;border-radius:3px;letter-spacing:.05em;flex-shrink:0}
.ptbr-reg-val{display:flex;align-items:center;gap:6px;font-size:12px;font-weight:700;min-width:0}
.ptbr-connector{text-align:center;color:var(--text3);font-size:16px;line-height:1;margin:2px 6px}
.pt-box{background:var(--bg2);border:1px solid var(--border);border-radius:6px;overflow:hidden}
.pt-header{padding:4px 8px;font-size:9px;font-weight:700;text-transform:uppercase;color:var(--text3);letter-spacing:.08em;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:6px}
.pt-entries{padding:4px;max-height:200px;overflow-y:auto}
.pt-row{display:flex;align-items:center;gap:3px;padding:3px 5px;border-radius:4px;margin-bottom:1px;font-size:10px;border-left:2px solid transparent;transition:all .3s}
.pt-row.en-ram{border-left-color:var(--green);background:rgba(63,185,80,.06)}
.pt-row.en-disco{color:var(--text3);border-left-color:transparent}
.pt-row.activa{background:rgba(88,166,255,.15);border-left-color:var(--blue);animation:ptPulse .6s ease}
@keyframes ptPulse{0%,100%{}50%{box-shadow:0 0 8px rgba(88,166,255,.5)}}
.pt-pag{font-weight:700;width:34px;flex-shrink:0}
.pt-arrow{color:var(--text3);margin:0 2px}
.pt-dest{font-weight:700;width:58px;color:var(--blue)}
.pt-dest.disk{color:var(--text3)}
.pt-bits{display:flex;gap:2px;margin-left:auto}
.pt-bit{font-size:8px;padding:1px 3px;border-radius:2px;font-weight:700}
.pt-bit.P1{background:rgba(63,185,80,.25);color:var(--green)}
.pt-bit.D1{background:rgba(240,136,62,.25);color:var(--orange)}
.pt-bit.R1{background:rgba(210,153,34,.25);color:var(--yellow)}
.pt-bit.off{background:rgba(255,255,255,.06);color:var(--text3)}

/* CENTRO */
.center{display:flex;flex-direction:column;overflow:hidden}
.evento-box{padding:12px 16px;border-bottom:1px solid var(--border);flex-shrink:0;min-height:155px}
.evento-tipo{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;margin-bottom:6px}
.evento-tipo.fault{color:var(--red)}
.evento-tipo.tlb_hit{color:var(--green)}
.evento-tipo.acceso{color:var(--blue)}
.evento-tipo.reemplazo{color:var(--orange)}
.evento-tipo.inicio{color:var(--text2)}
.evento-heading{font-size:17px;font-weight:700;margin-bottom:5px;display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.evento-desc{color:var(--text2);font-size:12px;margin-bottom:8px}
.flujo-row{display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin-bottom:7px}
.flujo-box{padding:3px 9px;border-radius:20px;font-size:11px;background:var(--bg3);border:1px solid var(--border)}
.flujo-arrow{color:var(--text3);font-size:14px}
.bits-row{display:flex;gap:7px;flex-wrap:wrap}
.bit{padding:2px 9px;border-radius:20px;font-size:11px;font-weight:700}
.bit.P1{background:#0f3d1f;color:var(--green)}
.bit.P0{background:#3d0f0f;color:var(--red)}
.bit.D1{background:#3d220f;color:var(--orange)}
.bit.D0{background:#1a1f2e;color:var(--text3)}
.bit.R1{background:#2a2014;color:var(--yellow)}
.bit.R0{background:#1a1f2e;color:var(--text3)}
.badge{display:inline-flex;align-items:center;gap:4px;padding:2px 7px;border-radius:4px;font-size:10px}
.badge.disk{background:rgba(248,81,73,.15);border:1px solid rgba(248,81,73,.3);color:var(--red)}
.badge.write{background:rgba(240,136,62,.15);border:1px solid rgba(240,136,62,.3);color:var(--orange)}

/* OPT analisis */
.opt-box{background:var(--bg2);border:1px solid var(--border);border-radius:6px;padding:8px;margin-top:7px}
.opt-title{font-size:9px;font-weight:700;color:var(--orange);text-transform:uppercase;margin-bottom:5px}
.opt-row{display:flex;align-items:center;gap:5px;padding:2px 5px;border-radius:3px;margin-bottom:2px;font-size:10px}
.opt-row.vic{background:rgba(248,81,73,.12);border:1px solid rgba(248,81,73,.25)}
.opt-prox{margin-left:auto;font-weight:700}
.opt-prox.nunca{color:var(--red)}
.opt-prox.lejano{color:var(--orange)}
.opt-prox.cerca{color:var(--green)}

/* RAM GRID */
.ram-area{flex:1;overflow-y:auto;padding:12px 16px}
.ram-title{font-size:10px;font-weight:700;color:var(--text2);text-transform:uppercase;letter-spacing:.08em;margin-bottom:10px}
.ram-grid{display:grid;gap:8px;grid-template-columns:repeat(auto-fill,minmax(120px,1fr))}

.frame-card{border-radius:var(--radius);border:3px solid;padding:10px;position:relative;transition:background .4s,border-color .4s;cursor:default;min-height:105px;display:flex;flex-direction:column;gap:3px}
.frame-card.libre{background:var(--bg2);border-color:var(--border);border-style:dashed}
.frame-card.libre .frame-num{color:var(--text3)}
.frame-num{font-size:9px;color:rgba(255,255,255,.45);font-weight:700;letter-spacing:.05em}
.frame-proc{font-size:12px;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.frame-pag{font-size:10px;color:rgba(255,255,255,.65);margin-bottom:2px}
.frame-bits{display:flex;gap:3px;flex-wrap:wrap}
.fb{font-size:9px;padding:1px 4px;border-radius:8px;font-weight:700}
.fb.P1{background:rgba(63,185,80,.25);color:var(--green)}
.fb.D1{background:rgba(240,136,62,.25);color:var(--orange)}
.fb.R1{background:rgba(210,153,34,.25);color:var(--yellow)}
.fb.off{background:rgba(255,255,255,.07);color:rgba(255,255,255,.25)}
.frame-addr{font-size:8px;color:rgba(255,255,255,.25);margin-top:auto;word-break:break-all}

/* Animaciones de marcos */
@keyframes frameIn  {0%{opacity:0;transform:scale(.85)}60%{transform:scale(1.05)}100%{opacity:1;transform:scale(1)}}
@keyframes frameOut {0%{box-shadow:0 0 0 0 rgba(248,81,73,.9)}40%{box-shadow:0 0 22px 8px rgba(248,81,73,.6);background:rgba(248,81,73,.25)}100%{box-shadow:none}}
@keyframes frameHit {0%,100%{}50%{box-shadow:0 0 18px 5px rgba(63,185,80,.7);border-color:var(--green)!important}}
@keyframes frameWrite{0%,100%{}50%{box-shadow:0 0 14px 4px rgba(240,136,62,.6)}}
.frame-card.anim-in   {animation:frameIn  .55s ease}
.frame-card.anim-out  {animation:frameOut .45s ease}
.frame-card.anim-hit  {animation:frameHit .55s ease}
.frame-card.anim-write{animation:frameWrite .45s ease}

/* TLB SLOTS */
.tlb-slots{display:flex;flex-direction:column;gap:3px;margin-bottom:8px}
.tlb-slot{display:flex;align-items:center;gap:6px;padding:5px 8px;border-radius:5px;border:1px solid var(--border);border-left:3px solid;font-size:11px;transition:all .3s;min-height:30px;position:relative}
.tlb-slot.vacio{border-left-color:var(--bg4);background:var(--bg2);color:var(--text3);font-style:italic}
.tlb-slot.invalida{border-left-color:var(--border);background:var(--bg2);opacity:.4}
.tlb-slot.valida{background:var(--bg2)}
@keyframes tlbHit {0%,100%{}50%{box-shadow:0 0 14px 3px rgba(63,185,80,.7);background:rgba(63,185,80,.12)}}
@keyframes tlbNew {0%{opacity:0;transform:translateX(-12px)}100%{opacity:1;transform:none}}
.tlb-slot.glow-hit{animation:tlbHit .7s ease}
.tlb-slot.glow-new{animation:tlbNew .45s ease}
.tlb-idx{font-size:9px;color:var(--text3);width:14px;flex-shrink:0;text-align:center}
.tlb-vdot{width:7px;height:7px;border-radius:50%;flex-shrink:0}
.tlb-page{font-weight:700;width:36px}
.tlb-sym{color:var(--text3);font-size:11px}
.tlb-frame{color:var(--blue);font-weight:700;width:50px}
.tlb-app{font-size:9px;color:var(--text3);margin-left:auto;max-width:80px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;text-align:right}
.tlb-stats{font-size:10px;color:var(--text3);padding:4px 0;display:flex;gap:10px}

/* HISTORIAL */
.hist-item{padding:5px 7px;border-radius:6px;border-left:3px solid;margin-bottom:3px;background:var(--bg2);font-size:10px}
.hist-item.fault{border-color:var(--red)}
.hist-item.page_fault_reemplazo{border-color:var(--orange)}
.hist-item.tlb_hit{border-color:var(--green)}
.hist-item.acceso{border-color:var(--blue)}
.hist-paso{color:var(--text3);font-size:9px}
.hist-desc{color:var(--text2);margin-top:1px}

/* STATS BAR */
.stats-bar{background:var(--bg2);border-top:1px solid var(--border);padding:8px 16px;display:flex;gap:16px;align-items:center;flex-wrap:wrap;flex-shrink:0}
.stat{display:flex;flex-direction:column;align-items:center;gap:1px}
.stat-val{font-size:16px;font-weight:700}
.stat-val.fault{color:var(--red)}
.stat-val.hit{color:var(--green)}
.stat-val.disk{color:var(--orange)}
.stat-val.blue{color:var(--blue)}
.stat-label{font-size:9px;color:var(--text3);text-transform:uppercase;letter-spacing:.06em}
.progress-bar{flex:1;min-width:100px}
.progress-label{font-size:9px;color:var(--text3);margin-bottom:2px;display:flex;justify-content:space-between}
.progress-track{height:5px;background:var(--bg4);border-radius:3px;overflow:hidden}
.progress-fill{height:100%;border-radius:3px;transition:width .4s}
.progress-fill.fault{background:var(--red)}
.progress-fill.hit{background:var(--green)}

/* SPLASH */
.splash{display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;gap:14px;padding:40px;text-align:center}
.splash h2{color:var(--blue);font-size:20px}
.splash p{color:var(--text2);max-width:500px;line-height:1.6}
.splash .config-row{display:flex;gap:10px;align-items:center}

/* PRÓXIMAS REFERENCIAS */
.proximas-strip{border-bottom:1px solid var(--border);padding:8px 16px;flex-shrink:0;background:var(--bg)}
.proximas-header{font-size:9px;font-weight:700;color:var(--text3);text-transform:uppercase;letter-spacing:.08em;margin-bottom:6px;display:flex;align-items:center;gap:8px}
.proximas-scroll{display:flex;gap:5px;overflow-x:auto;padding-bottom:4px;align-items:stretch}
.proximas-scroll::-webkit-scrollbar{height:3px}
.prox-card{display:flex;flex-direction:column;align-items:center;gap:2px;padding:5px 7px;border-radius:6px;border:1px solid var(--border);border-top:2px solid;background:var(--bg2);min-width:64px;flex-shrink:0;font-size:10px;cursor:default;transition:all .2s}
.prox-card:hover{background:var(--bg3)}
.prox-step{font-size:8px;color:var(--text3)}
.prox-icon{font-size:13px;line-height:1}
.prox-pag{font-weight:700;font-size:11px}
.prox-rw{font-size:8px;font-weight:700}
.prox-sep{color:var(--text3);align-self:center;font-size:16px;flex-shrink:0;opacity:.5}

/* RAM BAR 8 GB */
.ram-bar-section{border-bottom:1px solid var(--border);padding:10px 16px;flex-shrink:0}
.ram-bar-header{display:flex;align-items:center;gap:10px;margin-bottom:8px}
.ram-bar-title-txt{font-size:10px;font-weight:700;color:var(--text2);text-transform:uppercase;letter-spacing:.08em}
.ram-bar-meta{font-size:10px;color:var(--text3)}
.ram-bar-legend{display:flex;gap:8px;flex-wrap:wrap;margin-left:auto}
.rbl-item{display:flex;align-items:center;gap:4px;font-size:9px;color:var(--text2)}
.rbl-dot{width:8px;height:8px;border-radius:2px;flex-shrink:0}
/* el contenedor externo: 8 GB total */
.ram-bar-outer{width:100%;height:64px;border:2px solid var(--border);border-radius:6px;overflow:hidden;display:flex;position:relative;background:repeating-linear-gradient(45deg,var(--bg2),var(--bg2) 4px,var(--bg3) 4px,var(--bg3) 8px)}
/* etiquetas de capacidad */
.ram-bar-scale{display:flex;justify-content:space-between;font-size:8px;color:var(--text3);margin-top:3px;padding:0 2px}
/* cada slot (marco físico) */
.rfs{flex:1;border-right:1px solid rgba(255,255,255,.06);display:flex;flex-direction:column;align-items:center;justify-content:center;gap:1px;padding:3px 2px;transition:all .4s;position:relative;overflow:hidden;min-width:0}
.rfs:last-child{border-right:none}
.rfs.libre{background:transparent;color:rgba(255,255,255,.15)}
.rfs.active{outline:2px solid var(--blue);outline-offset:-2px;z-index:2}
.rfs.dirty{border-bottom:2px solid var(--orange)}
.rfs-num{font-size:7px;opacity:.55;font-weight:700}
.rfs-icon{font-size:12px;line-height:1}
.rfs-name{font-size:7px;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:100%;text-align:center}
.rfs-pag{font-size:7px;opacity:.75}
.rfs-dbits{display:flex;gap:1px;margin-top:1px}
.rfs-dbit{font-size:6px;padding:0 2px;border-radius:1px;font-weight:700}
@keyframes rfsIn{0%{opacity:0;transform:scaleY(.3)}100%{opacity:1;transform:scaleY(1)}}
@keyframes rfsOut{0%{filter:brightness(1)}50%{filter:brightness(2);background:rgba(248,81,73,.5)!important}100%{filter:brightness(1)}}
.rfs.anim-in{animation:rfsIn .4s ease}
.rfs.anim-out{animation:rfsOut .35s ease}

/* SCROLLBAR */
::-webkit-scrollbar{width:5px;height:5px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:var(--border);border-radius:3px}
</style>
</head>
<body>
<div class="app">

<!-- HEADER -->
<div class="header">
  <h1>MMU Simulator <span>Belady Optimo</span></h1>
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
    <span id="pasoLabel" style="color:var(--text2);font-size:11px;margin-left:6px"></span>
  </div>
</div>

<!-- MAIN -->
<div class="main" id="mainContent">

  <!-- SPLASH -->
  <div id="splash" style="grid-column:1/-1;display:flex">
    <div class="splash">
      <h2>Simulador MMU — Memoria Virtual y RAM</h2>
      <p>Simula como juegos y apps pesadas compiten por los marcos de RAM.
         Observa el PTBR apuntando a la tabla de paginas, las traducciones en la TLB,
         y el algoritmo Optimo eligiendo la victima cuando la RAM esta llena.</p>
      <ul style="color:var(--text2);text-align:left;line-height:2;list-style:none">
        <li>⚡ <strong>TLB HIT</strong> — traduccion instantanea desde la cache</li>
        <li>⚠️ <strong>PAGE FAULT</strong> — pagina ausente, se carga del disco</li>
        <li>🔄 <strong>REEMPLAZO</strong> — RAM llena, algoritmo Optimo elige victima</li>
        <li>🟠 <strong>D=1 (sucio)</strong> — se escribe al disco antes de desalojar</li>
      </ul>
      <div class="config-row">
        <label style="color:var(--text2)">Marcos en RAM:</label>
        <select id="selMarcos2" style="background:var(--bg3);border:1px solid var(--border);color:var(--text);padding:7px 12px;border-radius:6px;font-size:13px">
          <option value="3">3 marcos (muy poca RAM)</option>
          <option value="4">4 marcos</option>
          <option value="5">5 marcos</option>
          <option value="6" selected>6 marcos</option>
          <option value="8">8 marcos</option>
          <option value="12">12 marcos</option>
        </select>
        <button id="btnSplash" class="btn primary" style="padding:8px 18px;font-size:13px" onclick="iniciarDesde()">
          Iniciar simulacion
        </button>
      </div>
    </div>
  </div>

  <!-- LEFT PANEL: Procesos + RAM usage + PTBR + Tabla paginas -->
  <div class="panel" id="panelProcesos" style="display:none">
    <div class="panel-title">Procesos simulados</div>
    <div id="listaProcesos"></div>
    <div class="ram-usage-box">
      <div style="font-size:9px;color:var(--text3);margin-bottom:5px;text-transform:uppercase">Uso de RAM</div>
      <div id="ramUsage" style="font-size:11px;color:var(--text2)"></div>
    </div>

    <!-- PTBR -->
    <div class="ptbr-section" id="ptbrSection" style="display:none">
      <div class="panel-title" style="margin-bottom:5px">
        <span style="color:var(--yellow)">▶</span> CPU Register
      </div>
      <!-- CR3 / PTBR register -->
      <div class="ptbr-reg-box" id="ptbrRegBox">
        <span class="ptbr-reg-label">PTBR</span>
        <div class="ptbr-reg-val" id="ptbrRegVal">
          <span style="color:var(--text3)">—</span>
        </div>
      </div>
      <div class="ptbr-connector">↓</div>
      <!-- Page table del proceso activo -->
      <div class="pt-box">
        <div class="pt-header" id="ptHeader">
          <span>Tabla de Paginas</span>
        </div>
        <div class="pt-entries" id="ptEntries">
          <div style="color:var(--text3);padding:4px">Sin datos</div>
        </div>
      </div>
    </div>
  </div>

  <!-- CENTRO: Evento + RAM -->
  <div class="center" id="panelCentro" style="display:none">
    <div class="evento-box" id="eventoBox">
      <div class="evento-tipo inicio" id="eventoTipo">LISTO</div>
      <div class="evento-heading" id="eventoHeading">Simulacion lista</div>
      <div class="evento-desc" id="eventoDesc">Presiona "Siguiente paso" para comenzar</div>
      <div class="flujo-row" id="eventoFlujo"></div>
      <div class="bits-row" id="eventoBits"></div>
      <div id="opcionVictima"></div>
    </div>

    <!-- PRÓXIMAS REFERENCIAS -->
    <div class="proximas-strip" id="proximasStrip" style="display:none">
      <div class="proximas-header">
        <span>Próximas referencias</span>
        <span id="proximasContador" style="color:var(--text3)"></span>
      </div>
      <div class="proximas-scroll" id="proximasScroll"></div>
    </div>

    <!-- RAM BAR 8 GB -->
    <div class="ram-bar-section" id="ramBarSection" style="display:none">
      <div class="ram-bar-header">
        <span class="ram-bar-title-txt">RAM — 8 GB</span>
        <span class="ram-bar-meta" id="ramBarMeta"></span>
        <div class="ram-bar-legend" id="ramBarLegend"></div>
      </div>
      <div class="ram-bar-outer" id="ramBarOuter"></div>
      <div class="ram-bar-scale" id="ramBarScale"></div>
    </div>

    <div class="ram-area">
      <div class="ram-title" id="ramTitle">MARCOS FÍSICOS — DETALLE</div>
      <div class="ram-grid" id="ramGrid"></div>
    </div>
  </div>

  <!-- RIGHT PANEL: TLB visual + Historial -->
  <div class="panel" id="panelDerecho" style="display:none">
    <div class="panel-title">
      TLB <span id="tlbCap" style="font-weight:400;color:var(--text3)"></span>
    </div>
    <div class="tlb-slots" id="tlbSlots"></div>
    <div class="tlb-stats" id="tlbStats">
      <span>Hits: <strong id="tlbHitPct" style="color:var(--green)">0%</strong></span>
      <span>Misses: <strong id="tlbMissN" style="color:var(--red)">0</strong></span>
    </div>

    <div class="panel-title" style="margin-top:10px">Historial reciente</div>
    <div id="historial"></div>
  </div>

</div><!-- /main -->

<!-- STATS BAR -->
<div class="stats-bar" id="statsBar" style="display:none">
  <div class="stat"><div class="stat-val fault" id="statFaults">0</div><div class="stat-label">Page Faults</div></div>
  <div class="stat"><div class="stat-val hit" id="statHitPct">0%</div><div class="stat-label">TLB Hit Rate</div></div>
  <div class="stat"><div class="stat-val disk" id="statDiskR">0</div><div class="stat-label">Lecturas Disco</div></div>
  <div class="stat"><div class="stat-val disk" id="statDiskW">0</div><div class="stat-label">Escrituras Disco</div></div>
  <div class="stat"><div class="stat-val blue" id="statAccesos">0</div><div class="stat-label">Accesos</div></div>
  <div class="progress-bar">
    <div class="progress-label"><span>Faults</span><span id="faultPct2">0%</span></div>
    <div class="progress-track"><div class="progress-fill fault" id="faultBar" style="width:0%"></div></div>
  </div>
  <div class="progress-bar">
    <div class="progress-label"><span>TLB Hit Rate</span><span id="hitPct2">0%</span></div>
    <div class="progress-track"><div class="progress-fill hit" id="hitBar" style="width:0%"></div></div>
  </div>
  <div style="color:var(--text3);font-size:10px;margin-left:auto" id="pasoFinal"></div>
</div>

</div><!-- /app -->

<script>
let autoMode=false,autoTimer=null,estado=null,iniciado=false;

function getMarcos(){
  return document.getElementById('selMarcos').value||
         document.getElementById('selMarcos2').value||'6';
}

async function iniciarDesde(){
  const m=document.getElementById('selMarcos2').value;
  document.getElementById('selMarcos').value=m;
  await iniciar();
}

async function iniciar(){
  const btns=[document.getElementById('btnSplash'),document.getElementById('btnIniciar')];
  btns.forEach(b=>{if(b){b.textContent='Leyendo procesos...';b.disabled=true;}});
  try{
    const marcos=getMarcos();
    const res=await fetch('/api/inicializar',{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({marcos:parseInt(marcos)})
    });
    if(!res.ok)throw new Error('HTTP '+res.status);
    const data=await res.json();
    iniciado=true;
    mostrarUI();
    renderProcesos(data.procesos);
    document.getElementById('pasoLabel').textContent=`0 / ${data.total_pasos} pasos`;
    document.getElementById('btnPaso').disabled=false;
    document.getElementById('btnAuto').disabled=false;
    document.getElementById('btnReset').style.display='';
    document.getElementById('btnIniciar').style.display='none';
    const est=await fetch('/api/estado').then(r=>r.json());
    actualizarVista(est);
  }catch(err){
    btns.forEach(b=>{if(b){b.textContent='Iniciar simulacion';b.disabled=false;}});
    alert('Error: '+err.message);
  }
}

function mostrarUI(){
  document.getElementById('splash').style.display='none';
  ['panelProcesos','panelCentro','panelDerecho','statsBar'].forEach(id=>{
    document.getElementById(id).style.display='';
  });
}

async function paso(){
  if(!iniciado)return;
  const res=await fetch('/api/avanzar',{method:'POST'});
  const est=await res.json();
  actualizarVista(est);
  if(est.terminado){
    document.getElementById('btnPaso').disabled=true;
    stopAuto();
    document.getElementById('btnAuto').disabled=true;
    document.getElementById('pasoFinal').textContent='Simulacion completada';
  }
}

function toggleAuto(){if(autoMode)stopAuto();else startAuto();}
function startAuto(){
  autoMode=true;
  document.getElementById('btnAuto').textContent='PAUSAR';
  document.getElementById('btnAuto').className='btn danger';
  document.getElementById('autoInd').style.display='';
  runAuto();
}
function stopAuto(){
  autoMode=false;clearTimeout(autoTimer);
  document.getElementById('btnAuto').textContent='AUTO';
  document.getElementById('btnAuto').className='btn';
  document.getElementById('autoInd').style.display='none';
}
function runAuto(){
  if(!autoMode)return;
  paso().then(()=>{
    if(autoMode&&estado&&!estado.terminado){
      const spd=parseInt(document.getElementById('selSpeed').value);
      autoTimer=setTimeout(runAuto,spd);
    }else stopAuto();
  });
}

async function reset(){
  stopAuto();
  const marcos=getMarcos();
  await fetch('/api/reset',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({marcos:parseInt(marcos)})});
  const est=await fetch('/api/estado').then(r=>r.json());
  actualizarVista(est);
  document.getElementById('btnPaso').disabled=false;
  document.getElementById('btnAuto').disabled=false;
  document.getElementById('pasoFinal').textContent='';
  document.getElementById('pasoLabel').textContent=`0 / ${est.total_pasos} pasos`;
}

// ── RENDER PRINCIPAL ─────────────────────────────────────────────────────────
function actualizarVista(est){
  estado=est;
  renderEvento(est.evento,est.meta_actual);
  renderRAM(est.marcos,est.evento);
  renderRAMBar(est.marcos,est.num_marcos,est.evento,est.procesos);
  renderProximas(est.proximas);
  renderTLB(est.tlb,est.tlb_cap,est.evento);
  renderPTBR(est.ptbr,est.tabla_procesos,est.evento);
  renderHistorial(est.historial);
  renderStats(est.stats);
  document.getElementById('pasoLabel').textContent=`${est.paso+1} / ${est.total_pasos} pasos`;
  actualizarRamUsage(est.marcos,est.num_marcos);
}

function renderProcesos(procs){
  document.getElementById('listaProcesos').innerHTML=procs.map(p=>`
    <div class="proc-item">
      <div class="proc-swatch" style="background:${p.color}"></div>
      <div style="min-width:0;flex:1">
        <div class="proc-name">${p.icono} ${p.nombre}</div>
        <div class="proc-sub">${p.mem_mb.toFixed(0)} MB &middot; ${p.num_paginas} pags virtuales</div>
      </div>
    </div>`).join('');
}

function actualizarRamUsage(marcos,total){
  const ocup=marcos?marcos.filter(m=>!m.libre).length:0;
  const libre=total-ocup;
  const pct=total?Math.round(ocup/total*100):0;
  const col=pct>85?'var(--red)':pct>60?'var(--orange)':'var(--green)';
  document.getElementById('ramUsage').innerHTML=`
    <div style="margin-bottom:4px;display:flex;justify-content:space-between">
      <span style="color:${col}">${ocup} ocupados</span>
      <span style="color:var(--green)">${libre} libres</span>
      <span style="color:var(--text3)">${pct}%</span>
    </div>
    <div style="height:5px;background:var(--bg4);border-radius:3px;overflow:hidden">
      <div style="height:100%;width:${pct}%;background:${col};transition:width .4s;border-radius:3px"></div>
    </div>`;
}

// ── PTBR + Tabla de Paginas ───────────────────────────────────────────────────
function renderPTBR(ptbr,tablaProcs,evento){
  const sec=document.getElementById('ptbrSection');
  if(!ptbr){sec.style.display='none';return;}
  sec.style.display='';

  // Registro PTBR
  const box=document.getElementById('ptbrRegBox');
  box.className='ptbr-reg-box active';
  document.getElementById('ptbrRegVal').innerHTML=
    `<span style="font-size:14px">${ptbr.icono}</span>
     <span style="color:${ptbr.color}">${ptbr.nombre}</span>
     <span style="color:var(--text3);font-size:10px">pid=${ptbr.pid}</span>`;
  box.style.borderColor=ptbr.color;
  box.style.boxShadow=`0 0 10px ${hexToRgba(ptbr.color,.3)}`;

  // Tabla de paginas del proceso actual
  const procData=tablaProcs?tablaProcs.find(p=>p.pid===ptbr.pid):null;
  document.getElementById('ptHeader').innerHTML=
    `<span style="color:${ptbr.color}">${ptbr.icono} ${ptbr.nombre}</span>
     <span style="color:var(--text3);margin-left:auto">Tabla de Paginas</span>`;

  if(!procData||!procData.entradas||procData.entradas.length===0){
    document.getElementById('ptEntries').innerHTML=
      '<div style="color:var(--text3);padding:4px;font-size:10px">Ninguna pagina accedida aun</div>';
    return;
  }

  const pagActual=ptbr.pag_actual;
  document.getElementById('ptEntries').innerHTML=procData.entradas.map(e=>{
    const isActiva=String(e.pag)===String(pagActual);
    const cls=isActiva?'activa':e.presente?'en-ram':'en-disco';
    const dest=e.presente
      ?`<span class="pt-dest">Marco ${e.marco}</span>`
      :`<span class="pt-dest disk">DISCO</span>`;
    const bits=`
      <span class="pt-bit ${e.presente?'P1':'off'}">${e.presente?'P':'p'}</span>
      ${e.sucio?`<span class="pt-bit D1">D</span>`:''}
      ${e.referencia?`<span class="pt-bit R1">R</span>`:''}`;
    return `<div class="pt-row ${cls}">
      <span class="pt-pag">Pag ${e.pag}</span>
      <span class="pt-arrow">→</span>
      ${dest}
      <span class="pt-bits">${bits}</span>
    </div>`;
  }).join('');

  // Scroll al entry activo
  requestAnimationFrame(()=>{
    const active=document.querySelector('.pt-row.activa');
    if(active)active.scrollIntoView({block:'nearest',behavior:'smooth'});
  });
}

// ── RAM GRID ─────────────────────────────────────────────────────────────────
let prevMarcos={};
function renderRAM(marcos,evento){
  const grid=document.getElementById('ramGrid');
  const evMarco=evento?evento.marco:-1;
  const evTipo=evento?evento.tipo:'';
  const esVictima=evento&&evento.victima?evento.victima.marco:-1;

  grid.innerHTML=marcos.map(m=>{
    if(m.libre){
      return `<div class="frame-card libre" id="fc${m.num}">
        <div class="frame-num">MARCO ${m.num}</div>
        <div style="color:var(--border);font-size:20px;margin:auto 0;text-align:center">▭</div>
        <div class="frame-addr" style="margin-top:auto">${m.addr}</div>
      </div>`;
    }
    const isEvento=m.num===evMarco;
    const wasVictim=m.num===esVictima;
    let animCls='';
    if(isEvento){
      if(evTipo==='tlb_hit') animCls='anim-hit';
      else if(evTipo==='page_fault'||evTipo==='page_fault_reemplazo') animCls='anim-in';
      else if(evento&&evento.escritura) animCls='anim-write';
    }
    const bg=hexToRgba(m.color,.14);
    const borderCol=isEvento?m.color:hexToRgba(m.color,.55);
    const glow=isEvento?`box-shadow:0 0 16px ${hexToRgba(m.color,.4)};`:'';
    return `<div class="frame-card ${animCls}" id="fc${m.num}"
              style="background:${bg};border-color:${borderCol};${glow}">
      <div class="frame-num" style="color:${hexToRgba(m.color,.7)}">MARCO ${m.num}</div>
      <div class="frame-proc" style="color:${m.color}">${m.icono} ${m.nombre}</div>
      <div class="frame-pag">Pagina virtual ${m.pag_num}</div>
      <div class="frame-bits">
        <span class="fb ${m.P?'P1':'off'}">${m.P?'P=1':'P=0'}</span>
        <span class="fb ${m.D?'D1':'off'}">${m.D?'D=1':'D=0'}</span>
        <span class="fb ${m.R?'R1':'off'}">${m.R?'R=1':'R=0'}</span>
      </div>
      <div class="frame-addr">${m.addr}</div>
    </div>`;
  }).join('');
}

// ── TLB SLOTS ────────────────────────────────────────────────────────────────
let prevTLBKeys=[];
function renderTLB(tlb,cap,evento){
  document.getElementById('tlbCap').textContent=`(${cap} entradas)`;
  const evLlave=evento?evento.llave:'';
  const evTipo=evento?evento.tipo:'';

  // Construir N slots (cap total), los vacios al final
  const slots=[];
  for(let i=0;i<cap;i++){
    const e=tlb&&tlb[i]?tlb[i]:null;
    slots.push({idx:i,entry:e});
  }

  const html=slots.map(({idx,entry})=>{
    if(!entry){
      return `<div class="tlb-slot vacio">
        <span class="tlb-idx">${idx}</span>
        <span style="color:var(--bg4)">●</span>
        <span style="font-size:10px">— vacio —</span>
      </div>`;
    }
    const parts=entry.llave.split(':');
    const pid=parts[0],pag=parts[1]||'?';
    const proc=estado?estado.procesos.find(p=>`P${p.pid}`===pid):null;
    const color=proc?proc.color:'#6E7681';
    const nombre=proc?proc.nombre:pid;
    const icono=proc?proc.icono:'⚙️';
    const isHit=entry.llave===evLlave&&evTipo==='tlb_hit';
    const isNew=entry.llave===evLlave&&(evTipo==='page_fault'||evTipo==='page_fault_reemplazo');
    const animCls=isHit?'glow-hit':isNew?'glow-new':'';
    const cls=entry.valida?'valida':'invalida';
    const dotColor=entry.valida?'var(--green)':'var(--red)';
    return `<div class="tlb-slot ${cls} ${animCls}" style="border-left-color:${color}">
      <span class="tlb-idx">${idx}</span>
      <span class="tlb-vdot" style="background:${dotColor}"></span>
      <span class="tlb-page">Pag ${pag}</span>
      <span class="tlb-sym">→</span>
      <span class="tlb-frame">M${entry.marco}</span>
      <span class="tlb-app">${icono} ${nombre.substring(0,10)}</span>
    </div>`;
  }).join('');

  document.getElementById('tlbSlots').innerHTML=html;
}

// ── EVENTO ───────────────────────────────────────────────────────────────────
function renderEvento(ev,meta){
  if(!ev||!ev.tipo){
    document.getElementById('eventoTipo').className='evento-tipo inicio';
    document.getElementById('eventoTipo').textContent='LISTO';
    document.getElementById('eventoHeading').textContent='Simulacion lista para iniciar';
    document.getElementById('eventoDesc').textContent='Presiona "Siguiente paso" para comenzar';
    document.getElementById('eventoFlujo').innerHTML='';
    document.getElementById('eventoBits').innerHTML='';
    document.getElementById('opcionVictima').innerHTML='';
    return;
  }
  const tipos={
    page_fault:{label:'PAGE FAULT',cls:'fault',emoji:'⚠️'},
    page_fault_reemplazo:{label:'PAGE FAULT + REEMPLAZO',cls:'reemplazo',emoji:'🔄'},
    tlb_hit:{label:'TLB HIT',cls:'tlb_hit',emoji:'⚡'},
    acceso:{label:'ACCESO',cls:'acceso',emoji:'→'},
  };
  const t=tipos[ev.tipo]||{label:ev.tipo,cls:'acceso',emoji:'→'};
  const rw=ev.escritura
    ?'<span style="color:var(--orange);font-weight:700">ESCRITURA</span>'
    :'<span style="color:var(--green)">LECTURA</span>';

  document.getElementById('eventoTipo').className=`evento-tipo ${t.cls}`;
  document.getElementById('eventoTipo').textContent=`${t.emoji} ${t.label}`;
  document.getElementById('eventoHeading').innerHTML=
    `<span style="color:${ev.proc_color};font-size:18px">${ev.proc_icono}</span>
     <span style="color:${ev.proc_color}">${ev.proc_nombre}</span>
     <span style="color:var(--text3)">Pagina</span>
     <span>${ev.pag_idx}</span>
     <span style="color:var(--text3)">—</span> ${rw}`;
  document.getElementById('eventoDesc').textContent=ev.desc||'';

  // Flujo: VA → Pagina → Marco → Direccion Fisica
  const flujo=[
    {l:'Pag Virtual',v:`${ev.pag_idx}`},
    {arrow:true},
    {l:'Marco',v:`${ev.marco}`},
    {arrow:true},
    {l:'Dir. Fisica',v:ev.pa||'?'},
  ];
  document.getElementById('eventoFlujo').innerHTML=flujo.map(f=>
    f.arrow
      ?'<span class="flujo-arrow">→</span>'
      :`<span class="flujo-box"><span style="color:var(--text3)">${f.l}: </span>${f.v}</span>`
  ).join('');

  const P=ev.P,D=ev.D,R=ev.R;
  document.getElementById('eventoBits').innerHTML=`
    <span class="bit ${P?'P1':'P0'}">P=${P?1:0} ${P?'en RAM':'en disco'}</span>
    <span class="bit ${D?'D1':'D0'}">D=${D?1:0} ${D?'SUCIO':''}</span>
    <span class="bit ${R?'R1':'R0'}">R=${R?1:0}</span>
    ${ev.escritura?'<span class="badge write">escritura real</span>':''}
    ${ev.tipo==='page_fault'||ev.tipo==='page_fault_reemplazo'?'<span class="badge disk">lectura de disco</span>':''}
  `;

  let vicHTML='';
  if(ev.victima){
    const v=ev.victima;
    vicHTML=`<div class="opt-box">
      <div class="opt-title">Victima — Algoritmo Optimo de Belady</div>
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:7px">
        <div style="width:10px;height:10px;border-radius:2px;background:${v.color}"></div>
        <strong>${v.nombre}</strong> pag ${v.llave.split(':')[1]} marco ${v.marco}
        ${v.sucio?'<span class="badge disk" style="font-size:10px">D=1 → escrita al disco</span>':'<span style="color:var(--green);font-size:10px">D=0 → descartada sin I/O</span>'}
      </div>`;
    if(ev.opt_analisis){
      vicHTML+='<div class="opt-title" style="margin-bottom:3px">Analisis de uso futuro</div>';
      const sorted=Object.entries(ev.opt_analisis)
        .sort((a,b)=>{
          const pa=a[1].prox==='NUNCA'?Infinity:parseInt(a[1].prox.replace('indice ',''));
          const pb=b[1].prox==='NUNCA'?Infinity:parseInt(b[1].prox.replace('indice ',''));
          return pb-pa;
        });
      for(const[k,v2]of sorted){
        const isVic=v2.es_victima;
        const prox=v2.prox;
        const cls=prox==='NUNCA'?'nunca':prox.includes('indice')&&parseInt(prox.split(' ')[1])>15?'lejano':'cerca';
        vicHTML+=`<div class="opt-row ${isVic?'vic':''}">
          <div style="width:9px;height:9px;border-radius:2px;background:${v2.color};flex-shrink:0"></div>
          <span>${v2.nombre} pag ${v2.pag}</span>
          ${isVic?'<strong style="color:var(--red)">← VICTIMA</strong>':''}
          <span class="opt-prox ${cls}">${prox}</span>
        </div>`;
      }
    }
    vicHTML+='</div>';
  }
  document.getElementById('opcionVictima').innerHTML=vicHTML;
}

// ── HISTORIAL ────────────────────────────────────────────────────────────────
function renderHistorial(hist){
  const el=document.getElementById('historial');
  if(!hist||hist.length===0){el.innerHTML='';return;}
  el.innerHTML=[...hist].reverse().map(h=>`
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
    </div>`).join('');
}

// ── STATS ────────────────────────────────────────────────────────────────────
function renderStats(stats){
  document.getElementById('statFaults').textContent=stats.faults;
  document.getElementById('statHitPct').textContent=stats.tlb_hit_pct+'%';
  document.getElementById('statDiskR').textContent=stats.disk_reads;
  document.getElementById('statDiskW').textContent=stats.disk_writes;
  document.getElementById('statAccesos').textContent=stats.accesos;
  document.getElementById('tlbHitPct').textContent=stats.tlb_hit_pct+'%';
  document.getElementById('tlbMissN').textContent=stats.tlb_misses;
  document.getElementById('faultPct2').textContent=stats.fault_pct+'%';
  document.getElementById('hitPct2').textContent=stats.tlb_hit_pct+'%';
  document.getElementById('faultBar').style.width=stats.fault_pct+'%';
  document.getElementById('hitBar').style.width=stats.tlb_hit_pct+'%';
}

// ── PRÓXIMAS REFERENCIAS ─────────────────────────────────────────────────────
function renderProximas(proximas){
  const strip=document.getElementById('proximasStrip');
  if(!proximas||proximas.length===0){strip.style.display='none';return;}
  strip.style.display='';
  document.getElementById('proximasContador').textContent=`(${proximas.length} siguientes)`;
  const html=proximas.map((p,i)=>{
    const rw=p.escritura
      ?'<span class="prox-rw" style="color:var(--orange)">WRITE</span>'
      :'<span class="prox-rw" style="color:var(--green)">READ</span>';
    const sep=i<proximas.length-1?'<span class="prox-sep">›</span>':'';
    return `<div class="prox-card" style="border-top-color:${p.proc_color}" title="${p.desc}">
      <span class="prox-step">Paso ${p.idx+1}</span>
      <span class="prox-icon">${p.proc_icono}</span>
      <span class="prox-pag" style="color:${p.proc_color}">Pag ${p.pag_idx}</span>
      ${rw}
    </div>${sep}`;
  }).join('');
  document.getElementById('proximasScroll').innerHTML=html;
}

// ── RAM BAR 8 GB ─────────────────────────────────────────────────────────────
function renderRAMBar(marcos,num_marcos,evento,procesos){
  const sec=document.getElementById('ramBarSection');
  if(!marcos||marcos.length===0){sec.style.display='none';return;}
  sec.style.display='';

  const evMarco=evento?evento.marco:-1;
  const totalGB=8;
  const frameKB=4;
  const totalUsedKB=num_marcos*frameKB;
  const ocupados=marcos.filter(m=>!m.libre).length;
  const pct=Math.round(ocupados/num_marcos*100);
  const col=pct>85?'var(--red)':pct>60?'var(--orange)':'var(--green)';

  document.getElementById('ramBarMeta').innerHTML=
    `<span style="color:${col}">${ocupados}/${num_marcos} marcos ocupados</span>
     &nbsp;·&nbsp;${totalUsedKB} KB de ${totalGB} GB total
     &nbsp;·&nbsp;<span style="color:${col}">${pct}% de marcos en uso</span>`;

  // Leyenda de apps activas
  const appsEnRam=[...new Map(
    marcos.filter(m=>!m.libre).map(m=>[m.nombre,{nombre:m.nombre,color:m.color,icono:m.icono}])
  ).values()];
  document.getElementById('ramBarLegend').innerHTML=appsEnRam.map(a=>
    `<span class="rbl-item"><span class="rbl-dot" style="background:${a.color}"></span>${a.icono} ${a.nombre.substring(0,8)}</span>`
  ).join('');

  // Slots del barra
  document.getElementById('ramBarOuter').innerHTML=marcos.map(m=>{
    const isActive=m.num===evMarco;
    if(m.libre){
      return `<div class="rfs libre ${isActive?'active':''}">
        <span class="rfs-num">M${m.num}</span>
        <span style="font-size:10px;opacity:.2">□</span>
        <span class="rfs-name" style="opacity:.2">libre</span>
      </div>`;
    }
    const bg=hexToRgba(m.color,.55);
    const borderTop=`3px solid ${m.color}`;
    const dirtyClass=m.D?'dirty':'';
    return `<div class="rfs ocupado ${isActive?'active':''} ${dirtyClass} anim-in"
                 style="background:${bg};border-top:${borderTop}">
      <span class="rfs-num" style="color:rgba(255,255,255,.55)">M${m.num}</span>
      <span class="rfs-icon">${m.icono}</span>
      <span class="rfs-name">${m.nombre.substring(0,6)}</span>
      <span class="rfs-pag">P${m.pag_num}</span>
      <div class="rfs-dbits">
        ${m.D?'<span class="rfs-dbit" style="background:rgba(240,136,62,.5);color:var(--orange)">D</span>':''}
        ${m.R?'<span class="rfs-dbit" style="background:rgba(210,153,34,.5);color:var(--yellow)">R</span>':''}
      </div>
    </div>`;
  }).join('');

  // Escala: 0 GB ... N/total GB ... 8 GB
  const fraccionUsada=(totalUsedKB/1024/1024*100).toFixed(4);
  document.getElementById('ramBarScale').innerHTML=
    `<span>0 GB</span>
     <span style="color:var(--text3)">${num_marcos} marcos = ${totalUsedKB} KB (${fraccionUsada}% de 8 GB)</span>
     <span>8 GB</span>`;
}

// ── UTILIDADES ───────────────────────────────────────────────────────────────
function hexToRgba(hex,alpha){
  try{
    const r=parseInt(hex.slice(1,3),16);
    const g=parseInt(hex.slice(3,5),16);
    const b=parseInt(hex.slice(5,7),16);
    return `rgba(${r},${g},${b},${alpha})`;
  }catch(e){return `rgba(110,118,129,${alpha})`;}
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
