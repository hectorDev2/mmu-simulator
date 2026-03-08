# MMU Simulator — Simulador de Unidad de Gestión de Memoria

Simulador educativo de una MMU (Memory Management Unit) que demuestra conceptos de memoria virtual, paginación y el algoritmo de reemplazo Óptimo (Belady). Disponible en versión terminal y con interfaz web interactiva.

---

## Características

### Versión Terminal (`mmu_simulador.py`)
- Asignación real de RAM con `ctypes` (buffers de 4 KB reales del SO)
- Traducción real de direcciones virtuales a físicas
- Simulación de TLB (Translation Lookaside Buffer) con 8 entradas y política FIFO
- Manejo de fallos de página con el algoritmo Óptimo (Belady)
- I/O de disco real usando archivos binarios temporales (páginas de 4 KB)
- Bits de control en la tabla de páginas: P (presente), D (sucio), R (referenciado)
- Salida con colores ANSI para facilitar la visualización
- Modo paso a paso o ejecución automática

### Versión Web (`mmu_gui.py`)
- Interfaz oscura e interactiva accesible desde el navegador
- Monitoreo de procesos reales del sistema (Chrome, Safari, Firefox, etc.)
- Visualización en tiempo real de:
  - Marcos de RAM (tarjetas con proceso/página asignada)
  - Entradas de la TLB con estado de validez
  - Tabla de páginas de todos los procesos
  - Estadísticas en vivo (fallos de página, hit rate TLB, I/O de disco)
- Controles interactivos:
  - Inicio, paso a paso, auto-play y reset
  - Control de velocidad (Lento / Normal / Rápido / Turbo)
  - Configuración de marcos de RAM (3–32)
- Registro de eventos con análisis del algoritmo Óptimo

---

## Tecnologías

| Componente | Tecnología |
|---|---|
| Lenguaje | Python 3.8+ |
| Memoria real | `ctypes` |
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
```

**Opciones:**

```bash
python3 mmu_simulador.py --frames 4          # 4 marcos de RAM, modo interactivo
python3 mmu_simulador.py --frames 1024       # 1024 marcos = 4 MB de RAM real
python3 mmu_simulador.py --auto --delay 0.5  # Modo automático, 0.5 s entre pasos
```

---

### Versión Web (GUI)

```bash
# Instalar dependencias
pip install -r requirements.txt

# Iniciar el servidor
python3 mmu_gui.py
```

Abrir en el navegador: [http://localhost:5050](http://localhost:5050)

---

### Producción con Gunicorn

```bash
pip install -r requirements.txt
gunicorn --bind 0.0.0.0:5050 --workers 2 --timeout 120 mmu_gui:app
```

---

### Despliegue en Render

Ver [DEPLOY.md](DEPLOY.md) para instrucciones detalladas. El archivo `render.yaml` ya está configurado para despliegue automático.

---

## Estructura del Proyecto

```
s04/
├── mmu_simulador.py   # Simulador de terminal (paso a paso / automático)
├── mmu_gui.py         # Aplicación web Flask con GUI interactiva
├── requirements.txt   # Dependencias Python
├── render.yaml        # Configuración de despliegue en Render
├── DEPLOY.md          # Guía de despliegue (Render, Railway, local)
└── .gitignore
```

---

## Conceptos Demostrados

- **Paginación**: División de la memoria en páginas de 4 KB (tamaño real de x86/x86-64)
- **Tabla de páginas**: Mapeo de páginas virtuales a marcos físicos con bits P/D/R
- **TLB**: Caché de traducción de direcciones con estadísticas de hit/miss
- **Fallo de página**: Qué ocurre cuando una página no está en RAM
- **Algoritmo Óptimo (Belady)**: Reemplazo de la página cuyo próximo uso está más lejano en el futuro
- **Memoria física real**: Las direcciones reportadas son direcciones reales del proceso del SO

---

## Estadísticas en Tiempo Real

El simulador reporta:

- Total de accesos a memoria
- Fallos de página (cantidad y porcentaje)
- Hits y misses de TLB (cantidad y porcentaje)
- Lecturas y escrituras a disco
- Uso de RAM (marcos ocupados vs libres)
- Direcciones físicas reales

---

## Requisitos

- Python 3.8 o superior
- Para la versión web: `Flask`, `psutil`, `gunicorn` (ver `requirements.txt`)
- La versión terminal no requiere dependencias externas
