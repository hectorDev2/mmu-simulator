# MMU Simulator — Simulador de Unidad de Gestión de Memoria

Simulador educativo de una MMU (Memory Management Unit) que demuestra en tiempo real cómo juegos y aplicaciones pesadas compiten por los marcos de RAM. Incluye versión terminal y una interfaz web interactiva con visualizaciones de PTBR, TLB, tabla de páginas y algoritmo Óptimo de Belady.

---

## Vista general de la interfaz web

```
┌─────────────────────────────────────────────────────────────────────────┐
│ HEADER: controles (Anterior ◀ | Siguiente ▶ | AUTO | velocidad | reset) │
├─────────────────┬───────────────────────────────┬───────────────────────┤
│ Procesos        │ Evento actual                 │ TLB — 8 slots         │
│ ⛏️ Minecraft    │ ⚡ TLB HIT / ⚠️ PAGE FAULT    │ [●] Pag 0 → M2 ⛏️   │
│ 🖼️ Photoshop   │ Flujo: Pag → Marco → Dir.Fís. │ [●] Pag 1 → M5 🖼️   │
│ 🎬 Blender     │ Bits: P=1 D=0 R=1             │ [○] vacío             │
│ 🎮 Unity Editor │ Análisis Óptimo (víctima)     │ ...                   │
│ 📡 OBS Studio  ├───────────────────────────────┤                       │
│ 💬 Discord     │ Próximas referencias           │ Historial reciente    │
│                 │ [Pag3 READ] › [Pag1 WRITE] › │                       │
│ RAM usage bar  ├───────────────────────────────┤                       │
│                 │ RAM — 8 GB (barra gráfica)    │                       │
│ PTBR register  │ [M0 ⛏️][M1 🖼️][M2 🎬][M3 🎮] │                       │
│ ↓              ├───────────────────────────────┤                       │
│ Tabla páginas  │ Marcos físicos — detalle       │                       │
│ Pag 0 → M2 P R │ [card][card][card][card]...   │                       │
│ Pag 1 → DISCO  │                               │                       │
├─────────────────┴───────────────────────────────┴───────────────────────┤
│ STATS: Page Faults | TLB Hit Rate | Lecturas Disco | Escrituras | Acc.  │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Características

### Versión Terminal (`mmu_simulador.py`)
- Asignación real de RAM con `ctypes` (buffers de 4 KB del SO)
- Traducción real de direcciones virtuales a físicas
- TLB de 8 entradas con política FIFO y estadísticas hit/miss
- Manejo de fallos de página con el algoritmo Óptimo (Belady)
- I/O de disco real con archivos binarios temporales
- Bits P (presente), D (sucio), R (referenciado) en tabla de páginas
- Salida con colores ANSI, modo paso a paso o automático

### Versión Web (`mmu_gui.py`)

#### Simulación realista de procesos
- Detecta apps pesadas reales del sistema vía `psutil` (juegos, editores, motores)
- Fallback con perfiles predefinidos: **Minecraft, Photoshop, Blender, Unity Editor, OBS Studio, Discord**
- Cada proceso tiene un color único, ícono y número de páginas proporcional a su uso real de RAM
- Descripciones de acceso específicas por tipo de app:
  - Juegos: texturas 4K, chunks de mundo, física, audio, networking
  - Editores de imagen: buffers de capa, exportar RAW, LUT de color
  - 3D/render: mallas 3D, path tracing, BVH traversal
  - Motores: compilación JIT, asset bundles, shaders HLSL
  - Streaming: encoding H.264, captura de frames

#### Visualizaciones interactivas
- **PTBR (Page Table Base Register)**: registro de CPU con el proceso activo, flecha apuntando a su tabla de páginas con todas las entradas (en RAM / en disco), entrada actual resaltada en azul con scroll automático
- **TLB visual**: 8 slots con borde izquierdo del color de la app, punto verde/rojo de validez, animación `glow-hit` en TLB hit y `slide-in` al agregar entrada nueva
- **Barra RAM 8 GB**: rectángulo horizontal con N slots iguales (uno por marco), coloreados por app, bits D/R visibles, marco activo con borde azul, leyenda de apps en RAM, escala mostrando proporción real (24 KB de 8 GB)
- **Grid de marcos físicos**: tarjetas con borde de 3px del color de la app, animaciones `anim-in` al cargar página, `anim-hit` en TLB hit, `anim-write` al escribir
- **Cola de próximas referencias**: strip horizontal scrolleable con las siguientes 11 referencias — ícono, página, READ/WRITE, coloreadas por app
- **Análisis del algoritmo Óptimo**: tabla de uso futuro de cada página en RAM, víctima resaltada en rojo con etiqueta NUNCA / lejano / cerca

#### Controles de navegación
- **◀ Anterior**: retrocede al estado exacto del paso previo (RAM, TLB, tabla de páginas, stats, disco restaurados completamente)
- **▶ Siguiente**: avanza un paso
- **AUTO**: ejecución automática con velocidades Lenta / Normal / Rápida / Turbo
- **Reiniciar**: reinicia con el mismo número de marcos o uno diferente
- Selector de marcos de RAM: 3, 4, 5, 6, 8 ó 12

#### Panel central con scroll
El panel central hace scroll completo cuando el contenido (evento + referencias futuras + barra RAM + grid) supera la altura de la pantalla.

---

## Cómo funciona el paso anterior (undo)

Antes de cada avance se guarda un snapshot completo del estado:

```
[Paso 0] → snap₀ → [Paso 1] → snap₁ → [Paso 2] → snap₂ → [Paso 3] ← actual
◀ Anterior → restaura snap₂ → [Paso 2]
```

Cada snapshot incluye: buffers ctypes de cada marco (4 KB reales), entradas TLB, tabla de páginas (P/D/R), estadísticas, historial y archivos de disco.

---

## Tecnologías

| Componente | Tecnología |
|---|---|
| Lenguaje | Python 3.8+ |
| Memoria real | `ctypes` (buffers reales del SO) |
| I/O de disco | `tempfile`, `struct`, `shutil` |
| Web framework | Flask 3.0+ |
| Monitoreo de procesos | psutil 5.9+ |
| Servidor producción | Gunicorn 21.0+ |
| Despliegue | Render |

---

## Instalación y Uso

### Versión Terminal (sin dependencias externas)

```bash
python3 mmu_simulador.py
python3 mmu_simulador.py --frames 4          # 4 marcos, modo interactivo
python3 mmu_simulador.py --frames 1024       # 1024 marcos = 4 MB de RAM real
python3 mmu_simulador.py --auto --delay 0.5  # Automático, 0.5 s entre pasos
```

### Versión Web (GUI)

```bash
pip install -r requirements.txt
python3 mmu_gui.py
# Abrir http://localhost:5050
```

### Producción con Gunicorn

```bash
gunicorn --bind 0.0.0.0:5050 --workers 2 --timeout 120 mmu_gui:app
```

### Despliegue en Render

Ver [DEPLOY.md](DEPLOY.md). El archivo `render.yaml` ya está configurado para despliegue automático.

---

## Estructura del Proyecto

```
s04/
├── mmu_simulador.py   # Simulador terminal (ctypes, TLB, Belady, colores ANSI)
├── mmu_gui.py         # App web Flask: simulación + HTML/CSS/JS embebido
├── requirements.txt   # Flask, psutil, gunicorn
├── render.yaml        # Despliegue Render
├── DEPLOY.md          # Guía de despliegue
└── .gitignore
```

---

## Conceptos demostrados

| Concepto | Qué se ve en la simulación |
|---|---|
| Paginación | Páginas de 4 KB cargadas en marcos físicos |
| Tabla de páginas | PTBR apuntando a entradas con bits P/D/R |
| TLB | Cache de 8 slots, hit/miss animados en tiempo real |
| Fallo de página | Lectura de disco, asignación de marco |
| Algoritmo Óptimo | Análisis de uso futuro, selección de víctima |
| Dirty page | Bit D=1 → escritura al disco antes de desalojar |
| Memoria física real | Direcciones reportadas son reales del proceso del SO |

---

## Requisitos

- Python 3.8 o superior
- Versión web: `Flask`, `psutil`, `gunicorn` (ver `requirements.txt`)
- Versión terminal: sin dependencias externas
