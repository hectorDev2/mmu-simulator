# Guía de Despliegue - MMU Simulator

Esta guía te ayudará a desplegar el simulador MMU en internet usando Render (gratis).

## Opción 1: Desplegar en Render (Recomendado)

### Requisitos previos
- Cuenta en [GitHub](https://github.com)
- Cuenta en [Render](https://render.com) (puedes usar tu cuenta de GitHub para registrarte)

### Pasos

#### 1. Subir código a GitHub

Si aún no tienes el código en GitHub:

```bash
cd /Users/hector/Documents/s04

# Inicializar repositorio Git (si no existe)
git init

# Agregar archivos necesarios
git add mmu_gui.py requirements.txt render.yaml
git commit -m "Preparar app para despliegue en Render"

# Crear repositorio en GitHub y subir
# Ve a https://github.com/new y crea un repositorio llamado "mmu-simulator"
# Luego ejecuta:
git remote add origin https://github.com/TU_USUARIO/mmu-simulator.git
git branch -M main
git push -u origin main
```

#### 2. Conectar Render con GitHub

1. Ve a [render.com/dashboard](https://dashboard.render.com)
2. Haz clic en **"New +"** → **"Web Service"**
3. Conecta tu cuenta de GitHub si aún no lo has hecho
4. Busca y selecciona el repositorio **mmu-simulator**
5. Render detectará automáticamente el archivo `render.yaml`

#### 3. Configurar el servicio

Render usará la configuración de `render.yaml` automáticamente:
- **Name**: mmu-simulator
- **Runtime**: Python
- **Build Command**: `pip install -r requirements.txt`
- **Start Command**: `gunicorn --bind 0.0.0.0:$PORT --workers 2 --timeout 120 mmu_gui:app`
- **Plan**: Free (gratis)

Haz clic en **"Deploy Web Service"**.

#### 4. Esperar el despliegue

El despliegue toma entre 2-5 minutos. Podrás ver los logs en tiempo real.

Una vez completado, tendrás una URL pública como:
```
https://mmu-simulator.onrender.com
```

### Ventajas de Render
- ✅ **Gratis**: 750 horas/mes de uso gratuito
- ✅ **HTTPS automático**: Certificado SSL incluido
- ✅ **Auto-deploy**: Se actualiza automáticamente cuando haces push a GitHub
- ✅ **Logs en tiempo real**: Puedes ver qué está pasando en el servidor

### Limitaciones del plan gratuito
- ⚠️ **Se duerme después de 15 minutos sin uso**: Primera visita puede tardar ~30 segundos en "despertar"
- ⚠️ **750 horas/mes**: Suficiente para uso educativo normal
- ⚠️ **RAM limitada**: 512 MB (suficiente para esta app)

---

## Opción 2: Desplegar en Railway

Otra alternativa gratuita similar a Render:

1. Ve a [railway.app](https://railway.app)
2. Conéctate con GitHub
3. Clic en **"New Project"** → **"Deploy from GitHub repo"**
4. Selecciona tu repositorio
5. Railway detectará automáticamente que es una app Python Flask

**Configuración en Railway:**
- Build Command: `pip install -r requirements.txt`
- Start Command: `gunicorn --bind 0.0.0.0:$PORT --workers 2 --timeout 120 mmu_gui:app`

Railway te da $5 de crédito gratis cada mes.

---

## Opción 3: Ejecutar localmente con Gunicorn

Para pruebas locales con un servidor más robusto que Flask dev server:

```bash
# Instalar dependencias
pip install -r requirements.txt

# Ejecutar con Gunicorn
gunicorn --bind 0.0.0.0:5050 --workers 2 --timeout 120 mmu_gui:app
```

Accede desde tu navegador: `http://localhost:5050`

---

## Solución de problemas

### Error: "Worker timeout"
Si ves este error en los logs, significa que una operación tardó mucho. Posibles causas:
- El servidor está procesando demasiados procesos del sistema
- Puedes ajustar `--timeout 180` para dar más tiempo

### Error: "No module named 'psutil'"
Las dependencias no se instalaron correctamente. Verifica que `requirements.txt` esté en el repositorio.

### La app se ve rota o no carga CSS
Verifica que accedas vía `https://` (no `http://`) cuando uses Render.

### App muy lenta en Render
Es normal la primera vez después de 15 minutos de inactividad (free tier se "duerme"). Luego funciona normalmente.

---

## Actualizar la app desplegada

Cada vez que hagas cambios:

```bash
git add .
git commit -m "Descripción de los cambios"
git push origin main
```

Render detectará el cambio y desplegará automáticamente la nueva versión.

---

## Monitoreo y logs

En Render dashboard puedes:
- Ver logs en tiempo real
- Ver métricas de uso (CPU, RAM)
- Reiniciar el servicio manualmente si es necesario
- Ver historial de deploys

---

## Costos

**Plan Free de Render:**
- 750 horas/mes gratis
- Si necesitas más, el plan Starter cuesta $7/mes y elimina las limitaciones

**Railway:**
- $5 de crédito gratis mensual
- Suficiente para ~100-500 horas según uso

Para un proyecto educativo, el plan gratuito es más que suficiente.
