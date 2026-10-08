# Leeway Calculator (web) — creado por TheJorgeMC

Página web como Mutualify: la gente entra con **"Iniciar sesión con osu!"** y osu! muestra tu aplicación
(**Leeway_spin**) como **"Owned by TheJorgeMC"** en su lista de aplicaciones autorizadas (sale solo, porque la
aplicación OAuth está registrada en tu cuenta).

- Cualquiera ve el **top 8** del mapa sin poner ninguna clave (el servidor usa tus credenciales; los visitantes nunca las ven).
- Quien inicia sesión además ve su **propio score** en ese mapa, evaluado igual que el top.

## Cómo publicarla (gratis, ~15 minutos)

### 1. Sube esta carpeta a GitHub
Igual que hiciste con LimaTrackFX: repositorio nuevo → *uploading an existing file* → arrastra el CONTENIDO de esta
carpeta (`server.py`, `leeway_core.py`, `index.html`, `render.yaml`, `requirements.txt`, `README.md`, `.gitignore`).
**No subas tu Client Secret a GitHub** (no está en ningún archivo; se pone en Render, paso 3).

### 2. Crea el sitio en Render
1. Entra a https://render.com y regístrate con tu cuenta de GitHub.
2. **New +** → **Blueprint** → elige tu repositorio → Render lee `render.yaml`.
3. Te pedirá tres variables (paso 3). El nombre del servicio es `leeway-spin`; si Render dice que ya existe, cámbialo
   (por ejemplo `leeway-spin-jorge`). Tu dirección será `https://NOMBRE.onrender.com`.

### 3. Variables de entorno (en Render)
| Variable | Valor |
|---|---|
| `OSU_CLIENT_ID` | el número de tu aplicación en osu! |
| `OSU_CLIENT_SECRET` | el Client Secret de tu aplicación (solo aquí, nunca en GitHub) |
| `BASE_URL` | `https://NOMBRE.onrender.com` (sin `/` al final) |

### 4. Registra la dirección de retorno en osu!
En osu.ppy.sh/home/account/edit → OAuth → tu aplicación **Leeway_spin** → **Edit** → en *Application Callback URLs* pon,
una por línea:
```
https://NOMBRE.onrender.com/callback
http://localhost:8765/callback
```
(la segunda es solo para probar en tu PC). Guarda. Debe coincidir EXACTO con `BASE_URL` + `/callback`.

### 5. Listo
Abre `https://NOMBRE.onrender.com`, pulsa **Iniciar sesión con osu!** y prueba un mapa. Comparte ese link con quien quieras.

## Notas
- En el plan gratis, Render "duerme" el sitio tras ~15 min sin visitas; la primera visita después tarda ~30–60 s en despertar.
- Para probar en tu PC (necesita Python): define `OSU_CLIENT_ID`, `OSU_CLIENT_SECRET`, `BASE_URL=http://localhost:8765` y ejecuta `python server.py`.
- Límite: 40 análisis por minuto por persona. El ranking de cada mapa se guarda 5 min para no saturar la API de osu!.
- Si algún día cambias el Client Secret en osu!, actualízalo también en Render.
