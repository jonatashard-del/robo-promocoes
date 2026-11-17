# Robô de promoções - Calçados, Tecnologia, Casa e Carro
# Roda no GitHub Actions a cada 10 min (python robo_calcados.py --uma)
# ou no PC (python robo_calcados.py --teste).

import requests, time, json, os, sys, socket, re, hashlib
from html import unescape
import urllib3.util.connection as _uc
_uc.allowed_gai_family = lambda: socket.AF_INET   # força IPv4

# ===== CONFIGURAÇÃO GERAL =====
PASTA = os.path.dirname(os.path.abspath(__file__))
TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
if not TOKEN:
    with open(os.path.join(PASTA, "token.txt"), encoding="utf-8") as _f:
        TOKEN = _f.read().strip()
SHOPEE_APP_ID = os.environ.get("SHOPEE_APP_ID", "").strip()
SHOPEE_SECRET = os.environ.get("SHOPEE_SECRET", "").strip()

CHAT_ID = "-1004445005146"
TOPICO = {"calcados": 7, "tecnologia": 3, "casa": 59, "carro": 62}
INTERVALO = 600                # PC: segundos entre varreduras
MAX_POR_RODADA = 25            # trava contra inundar o grupo
ARQ_VISTOS = os.path.join(PASTA, "vistos.json")
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/130.0 Safari/537.36",
           "Accept-Language": "pt-BR,pt;q=0.9"}

# ----- Calçados -----
DESCONTO_MIN_CALCADOS = 50
TAM_MASC, TAM_FEM = "41", "38"
MARCAS_CALCADOS = ["nike", "adidas", "puma", "new balance", "on running", "olympikus",
                   "asics", "mizuno", "vans", "jordan", "fila", "reebok", "converse"]
LOJAS_VTEX = {
    "Artwalk": "https://www.artwalk.com.br",
    "Authentic Feet": "https://www.authenticfeet.com.br",
}

# ----- Tecnologia -----
SSD_PRECO_MAX = 450.0          # SSD externo >= 1TB abaixo disso: alerta especial
MARCAS_TECH = ["apple", "samsung", "jbl", "sony", "anker", "soundcore", "xiaomi", "redmi",
               "philips", "baseus", "ugreen", "sandisk", "kingston", "lexar", "western digital",
               " wd ", "crucial", "seagate", "edifier", "lenovo", "logitech", "motorola",
               "beats", "bose", "sennheiser", "haylou", "qcy", "omron", "withings", "huawei",
               "amazfit", "multilaser", "elg", "geonav", "intelbras", "positivo"]
BUSCAS_TECH = ["fone de ouvido", "fone bluetooth", "carregador", "power bank",
               "balança bioimpedância", "ssd externo", "ssd portátil"]
TEMP_MIN_TECH = 300            # "temperatura" mínima no Pelando
DESCONTO_MIN_TECH = 30

# ----- Casa -----
BUSCAS_CASA = ["utensílios cozinha", "panela", "jogo de panelas", "air fryer", "aspirador",
               "liquidificador", "cafeteira", "organizador", "jogo de facas", "potes herméticos"]
TEMP_MIN_CASA = 500

# ----- Carro (Nissan Kicks 2017 SL) -----
BUSCAS_CARRO = ["nissan kicks", "kicks", "pneu 205/55 r17", "205/55r17"]
PALAVRAS_CARRO = ["kicks", "205/55", "205 55"]
EXCLUIR_CARRO = ["tênis", "tenis", "sneaker", "chuteira"]

# ----- Shopee Afiliados (só tecnologia em evidência) -----
BUSCAS_SHOPEE = ["ssd externo 1tb", "power bank", "fone de ouvido bluetooth",
                 "carregador turbo usb-c", "balança bioimpedância"]
DESCONTO_MIN_SHOPEE = 50
NOTA_MIN_SHOPEE = 4.6

enviados_na_rodada = 0


# ===== APOIO =====
def carregar_vistos():
    if os.path.exists(ARQ_VISTOS):
        try:
            with open(ARQ_VISTOS) as f:
                return set(json.load(f))
        except Exception:
            pass
    return set()

def salvar_vistos(v):
    with open(ARQ_VISTOS, "w") as f:
        json.dump(sorted(v)[-20000:], f)

def brl(v):
    return "R$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def desconto(de, por):
    return (1 - por / de) * 100 if de and por and de > por else 0

def tg_post(dados, metodo="sendMessage"):
    for tentativa in range(3):
        try:
            r = requests.post(f"https://api.telegram.org/bot{TOKEN}/{metodo}",
                              data=dados, timeout=(10, 60))
            if not r.ok:
                print("Erro no Telegram:", r.text[:200])
            return r.ok
        except requests.RequestException as e:
            print(f"Telegram sem resposta (tentativa {tentativa + 1}/3): {type(e).__name__}")
            time.sleep(5)
    return False

def postar(topico, texto, foto=None):
    """Manda no tópico; tenta com foto e cai pra texto se a imagem falhar."""
    global enviados_na_rodada
    if enviados_na_rodada >= MAX_POR_RODADA:
        return False
    base = {"chat_id": CHAT_ID, "message_thread_id": TOPICO[topico]}
    ok = False
    if foto:
        ok = tg_post({**base, "photo": foto, "caption": texto[:1024]}, "sendPhoto")
    if not ok:
        ok = tg_post({**base, "text": texto, "disable_web_page_preview": "true"})
    if ok:
        enviados_na_rodada += 1
        time.sleep(1.5)
    return ok


# ===== CALÇADOS (lojas VTEX) =====
def genero(texto):
    t = texto.lower()
    if "unissex" in t or "unisex" in t:
        return "Unissex"
    if "femin" in t or "women" in t or "wmns" in t:
        return "Feminino"
    if "mascul" in t or " men" in t:
        return "Masculino"
    return "Unissex"

def tamanho_alvo(g):
    return TAM_FEM if g == "Feminino" else TAM_MASC

def tamanho_do_sku(item):
    for campo in ("Tamanho", "TAMANHO", "tamanho", "Numeração"):
        if item.get(campo):
            return str(item[campo][0]).strip()
    return item.get("name", "").split()[-1] if item.get("name") else ""

def varrer_vtex(loja, base, vistos):
    achados = 0
    for marca in MARCAS_CALCADOS:
        url = f"{base}/api/catalog_system/pub/products/search?ft={marca}&_from=0&_to=49"
        try:
            produtos = requests.get(url, headers=HEADERS, timeout=20).json()
        except Exception:
            continue
        if not isinstance(produtos, list):
            continue
        for p in produtos:
            txt = " ".join([p.get("productName", "")] + p.get("categories", [])
                           + [str(p.get("Gênero", "")), str(p.get("Genero", ""))])
            g = genero(txt)
            alvo = tamanho_alvo(g)
            for item in p.get("items", []):
                if tamanho_do_sku(item) != alvo:
                    continue
                try:
                    seller = item["sellers"][0]
                    oferta = seller["commertialOffer"]
                except (KeyError, IndexError):
                    continue
                de, por = oferta.get("ListPrice", 0), oferta.get("Price", 0)
                if oferta.get("AvailableQuantity", 0) <= 0 or desconto(de, por) < DESCONTO_MIN_CALCADOS:
                    continue
                chave = f"{loja}-{item['itemId']}-{por}"
                if chave in vistos:
                    continue
                link = (f"{base}/checkout/cart/add?sku={item['itemId']}&qty=1"
                        f"&seller={seller.get('sellerId', '1')}&redirect=true&sc=1")
                imgs = item.get("images") or []
                foto = imgs[0].get("imageUrl") if imgs else None
                texto = (f"🔥 {round(desconto(de, por))}% OFF — {loja}\n{p['productName']}\n"
                         f"{g} · tamanho {alvo} disponível\nDe {brl(de)} por {brl(por)}\n"
                         f"🛒 Comprar (já vai pro carrinho): {link}")
                if postar("calcados", texto, foto):
                    vistos.add(chave)
                    achados += 1
    return achados


# ===== PELANDO =====
def _astro(v):
    """Desfaz o formato de dados do Astro ([0, valor] / [1, lista])."""
    if isinstance(v, list) and len(v) == 2 and isinstance(v[0], int):
        t, x = v
        if t == 0:
            return {k: _astro(y) for k, y in x.items()} if isinstance(x, dict) else x
        if t == 1:
            return [_astro(y) for y in x]
        return x
    if isinstance(v, dict):
        return {k: _astro(y) for k, y in v.items()}
    return v

def pelando_buscar(termo):
    url = "https://www.pelando.com.br/busca/" + requests.utils.quote(termo.replace(" ", "-"))
    try:
        html = requests.get(url, headers=HEADERS, timeout=25).text
    except Exception as e:
        print(f"Pelando '{termo}': erro {type(e).__name__}")
        return []
    m = re.search(r'<astro-island[^>]*component-url="[^"]*SearchFeedContent[^"]*"[^>]*props="([^"]*)"', html)
    if not m:
        m = re.search(r'<astro-island[^>]*props="([^"]*SearchFeedContent[^"]*)"', html)
    if not m:
        print(f"Pelando '{termo}': página sem dados (pode ter bloqueado)")
        return []
    try:
        dados = _astro(json.loads(unescape(m.group(1))))
        return dados["initialData"]["deals"]["deals"] or []
    except Exception as e:
        print(f"Pelando '{termo}': não consegui ler ({type(e).__name__})")
        return []

def tb_capacidade(titulo):
    t = titulo.lower().replace(",", ".")
    m = re.search(r"(\d+(?:\.\d+)?)\s*tb", t)
    if m:
        return float(m.group(1))
    m = re.search(r"(\d{3,4})\s*gb", t)
    return float(m.group(1)) / 1000 if m else 0

def eh_ssd_alvo(titulo, preco):
    t = titulo.lower()
    externo = "ssd" in t and any(w in t for w in ("extern", "portátil", "portatil", "portable", "usb"))
    return externo and tb_capacidade(t) >= 1 and preco and preco <= SSD_PRECO_MAX

def post_pelando(topico, d, cabecalho):
    preco = float(d.get("price") or 0)
    loja = (d.get("store") or {}).get("name") or "loja"
    link = f"https://www.pelando.com.br/d/{d.get('slug')}"
    linhas = [cabecalho, d.get("title", "").strip()]
    if preco:
        linhas.append(f"Por {brl(preco)} · {loja}")
    else:
        linhas.append(loja)
    extras = []
    if d.get("discountPercentage"):
        extras.append(f"{d['discountPercentage']}% OFF")
    if d.get("temperature") is not None:
        extras.append(f"🌡️ {d['temperature']}° no Pelando")
    if d.get("freeShipping"):
        extras.append("frete grátis")
    if extras:
        linhas.append(" · ".join(extras))
    linhas.append(f"🔗 Ver oferta e cupom: {link}")
    return postar(topico, "\n".join(linhas), d.get("imageUrl"))

def varrer_pelando(topico, buscas, filtro, vistos):
    achados = 0
    for termo in buscas:
        for d in pelando_buscar(termo):
            if d.get("status") != "active" or d.get("kind") not in (None, "promotion"):
                continue
            chave = f"pelando-{d.get('id')}"
            if chave in vistos:
                continue
            cab = filtro(d)
            if not cab:
                continue
            if post_pelando(topico, d, cab):
                vistos.add(chave)
                achados += 1
        time.sleep(1)
    return achados

def filtro_tech(d):
    t = " " + (d.get("title") or "").lower() + " "
    preco = float(d.get("price") or 0)
    if eh_ssd_alvo(t, preco):
        return f"🎯 SSD NO SEU PREÇO (até {brl(SSD_PRECO_MAX)})"
    if not any(m in t for m in MARCAS_TECH):
        return None
    temp = float(d.get("temperature") or 0)
    pct = float(d.get("discountPercentage") or 0)
    if temp >= TEMP_MIN_TECH or pct >= DESCONTO_MIN_TECH:
        return "🔥 Tecnologia em alta"
    return None

def filtro_casa(d):
    return "🏠 Casa — oferta quente" if float(d.get("temperature") or 0) >= TEMP_MIN_CASA else None

def filtro_carro(d):
    t = (d.get("title") or "").lower()
    if any(x in t for x in EXCLUIR_CARRO):
        return None
    if not any(p in t for p in PALAVRAS_CARRO):
        return None
    return "🚗 Para o seu Kicks"


# ===== SHOPEE AFILIADOS =====
SHOPEE_URL = "https://open-api.affiliate.shopee.com.br/graphql"
SHOPEE_QUERY = ('{productOfferV2(keyword: %s, sortType: 2, page: 1, limit: 30) '
                '{nodes {itemId productName priceMin priceMax priceDiscountRate imageUrl '
                'offerLink shopName ratingStar sales}}}')

def shopee_buscar(termo):
    payload = json.dumps({"query": SHOPEE_QUERY % json.dumps(termo)}, separators=(",", ":"))
    ts = str(int(time.time()))
    assinatura = hashlib.sha256((SHOPEE_APP_ID + ts + payload + SHOPEE_SECRET).encode()).hexdigest()
    h = {"Content-Type": "application/json",
         "Authorization": f"SHA256 Credential={SHOPEE_APP_ID}, Timestamp={ts}, Signature={assinatura}"}
    try:
        r = requests.post(SHOPEE_URL, data=payload, headers=h, timeout=25).json()
        if r.get("errors"):
            print("Shopee:", str(r["errors"])[:200])
            return []
        return r["data"]["productOfferV2"]["nodes"] or []
    except Exception as e:
        print(f"Shopee '{termo}': erro {type(e).__name__}")
        return []

def varrer_shopee(vistos):
    if not (SHOPEE_APP_ID and SHOPEE_SECRET):
        print("Shopee: chaves ainda não cadastradas, pulando")
        return 0
    achados = 0
    for termo in BUSCAS_SHOPEE:
        for n in shopee_buscar(termo):
            nome = n.get("productName") or ""
            t = " " + nome.lower() + " "
            preco = float(n.get("priceMin") or 0)
            pct = float(n.get("priceDiscountRate") or 0)
            nota = float(n.get("ratingStar") or 0)
            chave = f"shopee-{n.get('itemId')}-{preco}"
            if chave in vistos or nota < NOTA_MIN_SHOPEE:
                continue
            if eh_ssd_alvo(t, preco):
                cab = f"🎯 SSD NO SEU PREÇO (até {brl(SSD_PRECO_MAX)}) — Shopee"
            elif any(m in t for m in MARCAS_TECH) and pct >= DESCONTO_MIN_SHOPEE:
                cab = f"🔥 {round(pct)}% OFF — Shopee"
            else:
                continue
            texto = (f"{cab}\n{nome}\nPor {brl(preco)} · {n.get('shopName') or 'Shopee'}\n"
                     f"⭐ {nota:.1f} · {n.get('sales') or 0} vendidos\n"
                     f"🛒 Comprar: {n.get('offerLink')}")
            if postar("tecnologia", texto, n.get("imageUrl")):
                vistos.add(chave)
                achados += 1
        time.sleep(1)
    return achados


# ===== EXECUÇÃO =====
def rodada(vistos):
    global enviados_na_rodada
    enviados_na_rodada = 0
    for loja, base in LOJAS_VTEX.items():
        print(f"Calçados · {loja}: {varrer_vtex(loja, base, vistos)} enviadas")
    print(f"Tecnologia · Pelando: {varrer_pelando('tecnologia', BUSCAS_TECH, filtro_tech, vistos)} enviadas")
    print(f"Tecnologia · Shopee: {varrer_shopee(vistos)} enviadas")
    print(f"Casa · Pelando: {varrer_pelando('casa', BUSCAS_CASA, filtro_casa, vistos)} enviadas")
    print(f"Carro · Pelando: {varrer_pelando('carro', BUSCAS_CARRO, filtro_carro, vistos)} enviadas")
    salvar_vistos(vistos)

if __name__ == "__main__":
    vistos = carregar_vistos()
    if "--uma" in sys.argv:
        rodada(vistos)
    elif "--teste" in sys.argv:
        print("Telegram:", "OK" if tg_post({"chat_id": CHAT_ID, "message_thread_id": TOPICO["calcados"],
                                            "text": "✅ Robô conectado!"}) else "FALHOU")
        rodada(vistos)
    else:
        while True:
            rodada(vistos)
            time.sleep(INTERVALO)
