"""Robot de Pulso Económico.

Cada hora (desde GitHub Actions) lee los titulares públicos (RSS) de varias
fuentes y los tipos de cambio oficiales del BCE, y los guarda en noticias.json.
La web lee ese archivo y lo muestra. Solo se guarda titular, fuente, hora y
enlace: nunca el texto de los artículos.

Solo usa la biblioteca estándar de Python, así no hay nada que instalar.
"""

import json
import re
import sys
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

SALIDA = Path(__file__).resolve().parent.parent / "noticias.json"
MAX_NOTICIAS = 60
HORAS_MAX = 48  # no mostrar noticias de hace más de dos días

# Fuente, dirección del RSS y sección por defecto si las palabras clave no deciden otra.
FUENTES = [
    ("Expansión", "https://e00-expansion.uecdn.es/rss/mercados.xml", "Mercados"),
    ("Expansión", "https://e00-expansion.uecdn.es/rss/economia.xml", "España"),
    ("Expansión", "https://e00-expansion.uecdn.es/rss/empresas.xml", "Empresas"),
    ("Expansión", "https://e00-expansion.uecdn.es/rss/ahorro.xml", "Tus finanzas"),
    ("Cinco Días", "https://feeds.elpais.com/mrss-s/pages/ep/site/cincodias.elpais.com/section/mercados/portada", "Mercados"),
    ("Cinco Días", "https://feeds.elpais.com/mrss-s/pages/ep/site/cincodias.elpais.com/section/economia/portada", "España"),
    ("Cinco Días", "https://feeds.elpais.com/mrss-s/pages/ep/site/cincodias.elpais.com/section/companias/portada", "Empresas"),
    ("Cinco Días", "https://feeds.elpais.com/mrss-s/pages/ep/site/cincodias.elpais.com/section/mis-finanzas/portada", "Tus finanzas"),
    ("Europa Press", "https://www.europapress.es/rss/rss.aspx?ch=00136", "España"),
    ("BCE", "https://www.ecb.europa.eu/rss/press.html", "Bancos centrales"),
]

# Palabras clave para clasificar (se buscan sin tildes y en minúsculas). El orden importa.
REGLAS = [
    ("Bancos centrales", None, r"\b(bce|fed|reserva federal|lagarde|powell|banco de espana|banco de inglaterra|banco de japon|tipos de interes|politica monetaria)\b"),
    ("Mercados", "Materias primas", r"\b(petroleo|brent|opep|oro|plata|cobre|gas natural|materias primas|trigo)\b"),
    ("Mercados", "Divisas", r"\b(divisas?|euro frente|dolar|yen|libra esterlina|tipo de cambio|bitcoin|criptomonedas?)\b"),
    ("Mercados", "Renta fija", r"\b(bonos?|deuda publica|prima de riesgo|letras del tesoro|rentabilidad del bono|tesoro publico|renta fija)\b"),
    ("Mercados", "Renta variable", r"\b(ibex|bolsas?|wall street|stoxx|dax|nasdaq|s&p|acciones|cotizacion)\b"),
    ("Tus finanzas", None, r"\b(hipotecas?|ahorradores?|ahorro|irpf|declaracion de la renta|pensiones?|jubilacion|fondos de inversion|depositos?|euribor|planes de pensiones)\b"),
    ("Macroeconomia", None, r"\b(ipc|inflacion|pib|paro|desempleo|empleo|afiliacion|deficit|recaudacion|crecimiento economico|recesion|ocde|fmi)\b"),
    ("Internacional", None, r"\b(ee\.? ?uu\.?|estados unidos|china|alemania|francia|italia|reino unido|japon|trump|bruselas|comision europea|union europea|eurozona|paris|berlin|londres|pekin|washington|le pen|rusia|ucrania|india|brasil|venezuela|latinoamerica|mexico|argentina)\b"),
]


def sin_tildes(texto):
    texto = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in texto if not unicodedata.combining(c))


def descargar(url):
    peticion = urllib.request.Request(url, headers={"User-Agent": "PulsoEconomicoBot/1.0 (+https://github.com)"})
    with urllib.request.urlopen(peticion, timeout=20) as r:
        return r.read()


def leer_fecha(texto):
    if not texto:
        return None
    texto = texto.strip()
    try:
        fecha = parsedate_to_datetime(texto)
    except (TypeError, ValueError):
        try:
            fecha = datetime.fromisoformat(texto.replace("Z", "+00:00"))
        except ValueError:
            return None
    if fecha.tzinfo is None:
        fecha = fecha.replace(tzinfo=timezone.utc)
    return fecha.astimezone(timezone.utc)


def hijo(elemento, *nombres):
    """Devuelve el texto del primer hijo que coincida, ignorando espacios de nombres XML."""
    for e in elemento:
        etiqueta = e.tag.split("}")[-1]
        if etiqueta in nombres:
            if etiqueta == "link" and e.get("href"):
                return e.get("href")
            if e.text and e.text.strip():
                return e.text.strip()
    return ""


def imagen(elemento):
    """Foto que el propio medio ofrece en su RSS (media:content, media:thumbnail o enclosure).
    Solo guardamos la dirección: la imagen se sigue sirviendo desde el medio."""
    mejor, ancho_mejor = "", -1
    for e in elemento.iter():
        etiqueta = e.tag.split("}")[-1]
        url = e.get("url") or ""
        if not url.startswith("https://"):
            continue
        tipo = e.get("type") or e.get("medium") or ""
        if etiqueta in ("content", "thumbnail") or (etiqueta == "enclosure" and "image" in tipo):
            if tipo and "image" not in tipo and etiqueta != "thumbnail":
                continue
            try:
                ancho = int(e.get("width") or 0)
            except ValueError:
                ancho = 0
            if ancho > ancho_mejor:
                mejor, ancho_mejor = url, ancho
    return mejor or None


def leer_rss(fuente, url, seccion_defecto):
    raiz = ET.fromstring(descargar(url))
    elementos = [e for e in raiz.iter() if e.tag.split("}")[-1] in ("item", "entry")]
    noticias = []
    for e in elementos:
        titulo = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", hijo(e, "title"))).strip()
        enlace = hijo(e, "link", "guid")
        if not titulo or not enlace.startswith(("http://", "https://")):
            continue
        fecha = leer_fecha(hijo(e, "pubDate", "published", "updated", "date"))
        seccion, subseccion = clasificar(titulo, seccion_defecto)
        noticias.append({
            "titulo": titulo,
            "enlace": enlace,
            "fuente": fuente,
            "fecha": fecha.isoformat() if fecha else None,
            "seccion": seccion,
            "subseccion": subseccion,
            "imagen": imagen(e),
        })
    return noticias


def clasificar(titulo, seccion_defecto):
    texto = sin_tildes(titulo)
    if seccion_defecto == "Bancos centrales":
        return "Bancos centrales", None
    for seccion, subseccion, patron in REGLAS:
        if re.search(patron, texto):
            return ("Macroeconomía" if seccion == "Macroeconomia" else seccion), subseccion
    return seccion_defecto, None


def tipos_de_cambio():
    """Tipos de cambio oficiales del BCE: el último día y su variación frente al anterior."""
    raiz = ET.fromstring(descargar("https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist-90d.xml"))
    dias = [c for c in raiz.iter() if c.tag.endswith("Cube") and c.get("time")]
    if len(dias) < 2:
        return None
    hoy, ayer = dias[0], dias[1]
    def tabla(dia):
        return {c.get("currency"): float(c.get("rate")) for c in dia}
    t_hoy, t_ayer = tabla(hoy), tabla(ayer)
    divisas = []
    for codigo in ("USD", "GBP", "JPY", "CHF", "CNY"):
        if codigo in t_hoy and codigo in t_ayer:
            variacion = (t_hoy[codigo] / t_ayer[codigo] - 1) * 100
            divisas.append({"par": f"EUR/{codigo}", "valor": t_hoy[codigo], "variacion": round(variacion, 2)})
    return {"fecha": hoy.get("time"), "divisas": divisas}


def principal():
    ahora = datetime.now(timezone.utc)
    limite = ahora - timedelta(hours=HORAS_MAX)
    todas, informe = [], []
    for fuente, url, seccion in FUENTES:
        try:
            noticias = leer_rss(fuente, url, seccion)
            todas.extend(noticias)
            informe.append(f"OK    {len(noticias):3d}  {fuente}  {url}")
        except Exception as error:  # una fuente caída no debe parar al resto
            informe.append(f"FALLO   -  {fuente}  {url}  ({error})")

    # Quitar repetidas (mismo titular en dos fuentes o en dos secciones del mismo medio).
    vistas, unicas = set(), []
    for n in sorted(todas, key=lambda n: n["fecha"] or "", reverse=True):
        clave = re.sub(r"[^a-z0-9]", "", sin_tildes(n["titulo"]))[:80]
        if clave in vistas:
            continue
        if n["fecha"] and datetime.fromisoformat(n["fecha"]) < limite:
            continue
        vistas.add(clave)
        unicas.append(n)

    try:
        cambio = tipos_de_cambio()
        informe.append("OK      -  BCE tipos de cambio")
    except Exception as error:
        cambio = None
        informe.append(f"FALLO   -  BCE tipos de cambio ({error})")

    print("\n".join(informe))
    if not unicas:
        print("No se ha conseguido ninguna noticia: se deja el archivo anterior.")
        sys.exit(0)

    datos = {
        "actualizado": ahora.isoformat(timespec="seconds"),
        "noticias": unicas[:MAX_NOTICIAS],
        "cambio": cambio,
    }
    SALIDA.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Guardadas {len(datos['noticias'])} noticias en {SALIDA.name}")


if __name__ == "__main__":
    principal()
