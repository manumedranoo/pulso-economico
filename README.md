# Pulso Económico

Web de noticias de economía y finanzas: mercados, España, internacional, macroeconomía, bancos centrales, empresas y finanzas personales.

- `index.html`: la portada (HTML y CSS en un solo archivo).
- Se publica gratis con GitHub Pages.

Los titulares enlazan siempre a su medio original.

## Noticias automáticas

- `scripts/actualizar.py`: el robot. Lee los titulares públicos (RSS) de varios medios y los tipos de cambio del BCE, y los guarda en `noticias.json`. Solo guarda titular, fuente, hora y enlace.
- `.github/workflows/noticias.yml`: hace que GitHub ejecute el robot cada hora. También se puede lanzar a mano desde la pestaña **Actions** › **Actualizar noticias** › **Run workflow**.
- Para añadir o quitar una fuente, se edita la lista `FUENTES` del robot.
